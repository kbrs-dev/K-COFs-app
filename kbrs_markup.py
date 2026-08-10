#!/usr/bin/env python3
"""
KBRS production markup generator.

Takes the two files you already get per order:
  1. The customer's filled-in order form PDF (the diagram + dims)
  2. KBRS's internal Production Order PDF (auto-generated, has PO#/SO#/dates/SKU)

...and produces the combined, annotated production sheet you currently build
by hand in PowerPoint: page 1 = order form with orange oversize dims / material
label / corner bracket, page 2 = the production order rotated 90 degrees.

USAGE (single order):
    python3 kbrs_markup.py \
        --order-form "order_form.pdf" \
        --production-order "PurchaseOrder RO PO247946.pdf" \
        --material "GRAY TRAVELER" \
        --out "PO247946-SO243810.pdf"

USAGE (batch):
    Put pairs of files in a folder, named so each pair shares the PO number
    somewhere in the filename, e.g.:
        PO247946_orderform.pdf
        PO247946_production.pdf
    Put a manifest.csv next to them with columns: po_number,material,thickness,curb_depth
    Then run:
        python3 kbrs_markup.py --batch ./incoming --manifest manifest.csv --outdir ./done

PRODUCT LINES COVERED (SKU prefix -> product):
    CLSS   Custom Linear ShowerSlope
    CSS    Custom (point-drain) ShowerSlope
    CLTB   Custom Linear Tile-Basin
    CTB    Custom (point-drain) Tile-Basin
    CFSRC  Custom Flanged Surface Ready Core (SRC)
Each was calibrated from one real finished example. New product lines need a
sample order form + finished markup to add a profile.

DIMENSION RULES:
    - Oversize width = raw width + 1" for every product line (confirmed on all 5).
    - Oversize height = raw height + 1" for ShowerSlope/SRC, but for Tile-Basin
      (point AND linear) the curb eats into that dimension first:
          oversize_height = raw_height - curb_depth + 1
      curb_depth defaults to 4" (HardCurb, seen on both real examples) --
      override per order if a different curb type/depth applies.

THICKNESS ANNOTATION:
    Thickness is optional and can apply to ANY product line -- mostly needed
    for SRC and linear products, but occasionally added for others too (per
    KBRS: "thickness can also be used for other products, its mostly for src
    and linears, but sometimes i have to add them for others"). Default is
    always blank (nothing shown, nothing painted over). Whatever you type in
    gets added to the form. Only CLSS, CLTB, and CFSRC have a calibrated
    position for it so far -- entering a thickness for CSS or CTB will print
    a warning and skip drawing it until a real example is available to
    calibrate that position.

MATERIAL BAR COLOR:
    Derived from the material name's color word (GRAY/GREEN/BLUE all
    confirmed from real examples: gray, green, and blue bars respectively).
    Unrecognized color words fall back to a dark neutral gray -- verify/tell
    me the right color if you hit one that's not in the table.

WIDE-PANEL ORIGIN RULE (Linear ShowerSlope only, so far):
    Drain is normally on the right, origin bracket marks the top-right
    corner. When raw width > 85", origin moves to the bottom-left corner
    instead (the diagram/labels don't change, only the bracket). Confirmed
    against a real 101.5"-wide example -- coordinates are exact, not a
    guess. Not yet extended to CLTB/CFSRC (ask before assuming the same
    threshold applies there too).

CUT-FOR-SHIPPING:
    For oversized panels that need a field cut to ship, a dashed vertical
    line + "Cut for shipping" label can be added. There's no fixed rule for
    where the cut goes (placed by hand per job), so this is edit/drag-only,
    not automatic. Confirmed: adds an extra 0.5" to the width oversize on
    top of the normal +1" (so +1.5" total) whenever present.

EDITABLE LAYOUT:
    The desktop app (app.py) has an editor that shows every draggable item
    (dimension labels, thickness, cut line/label, freeform notes) on top of
    the actual order-form background and lets you drag, add, edit, or
    delete before generating. This module's item-based functions
    (compute_default_items, make_cut_line_items, make_note_item, render_page)
    back that editor; build_overlay()/build_output() still work exactly as
    before for the CLI and batch mode (non-interactive, default positions).
"""

import argparse
import csv
import math
import os
import re
import tempfile
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen import canvas
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.lib.colors import Color
from reportlab.lib.utils import ImageReader
import io

ORANGE = Color(0.9490196, 0.5137255, 0.1490196)
WHITE = Color(1, 1, 1)
BLACK = Color(0, 0, 0)
COLOR_MAP = {"orange": ORANGE, "white": WHITE, "black": BLACK}
PAGE_W, PAGE_H = 612, 792  # US Letter, points

WIDE_PANEL_THRESHOLD_IN = 85.0
DEFAULT_CURB_DEPTH_IN = 4.0
# Extra width added (on top of the normal +1") when a cut-for-shipping line
# is present, confirmed from a real example (101.5" -> 103", not 102.5").
CUT_FOR_SHIPPING_EXTRA_IN = 0.5

# Customer order forms often come back as a scanned JPG/PNG rather than a
# PDF. ensure_pdf() below wraps an image in a Letter-size PDF page so all the
# calibrated annotation coordinates (which assume a 612x792pt page) still
# line up. HEIC isn't supported (Pillow can't open it without an extra
# plugin) -- ask the sender to export as JPG or PNG instead.
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".gif"}
_IMAGE_PDF_CACHE = {}  # original path -> (mtime, converted pdf path)


def ensure_pdf(path: str) -> str:
    """If `path` is an image (jpg/png/etc.), convert it to a one-page,
    Letter-size (612x792pt) PDF and return the path to that converted PDF
    (cached by path+mtime so repeated preview refreshes don't reconvert
    every time). If `path` is already a .pdf, returns it unchanged.

    The image is stretched to fill the full page -- the real order-form PDFs
    this app was calibrated against are themselves just a full-page scanned
    image wrapped in a PDF, so this matches that exactly as long as the scan
    captures the whole page edge-to-edge."""
    ext = Path(path).suffix.lower()
    if ext == ".pdf":
        return path
    if ext not in IMAGE_EXTS:
        raise ValueError(
            f"Unsupported order-form file type '{ext or '(no extension)'}'. "
            f"Use a PDF or a JPG/PNG/TIFF/BMP scan."
        )
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        mtime = None
    cached = _IMAGE_PDF_CACHE.get(path)
    if cached and cached[0] == mtime and os.path.isfile(cached[1]):
        return cached[1]

    fd, out_path = tempfile.mkstemp(suffix=".pdf", prefix="kbrs_scan_")
    os.close(fd)
    c = canvas.Canvas(out_path, pagesize=(PAGE_W, PAGE_H))
    c.drawImage(ImageReader(path), 0, 0, width=PAGE_W, height=PAGE_H)
    c.save()
    _IMAGE_PDF_CACHE[path] = (mtime, out_path)
    return out_path

# Material name -> bar fill color. Matched as a substring, case-insensitive,
# checked in order (first match wins). Confirmed from real examples: GRAY,
# GREEN, BLUE. RED added on request. Others are reasonable guesses -- verify
# before trusting them.
MATERIAL_COLOR_WORDS = [
    ("GRAY", Color(0.5019608, 0.5019608, 0.5019608)),
    ("GREY", Color(0.5019608, 0.5019608, 0.5019608)),
    ("GREEN", Color(0.0, 0.5019608, 0.0)),
    ("BLUE", Color(0.0, 0.572549, 0.8392157)),
    ("RED", Color(0.75, 0.11, 0.11)),
    ("BLACK", Color(0.15, 0.15, 0.15)),
    ("WHITE", Color(0.92, 0.92, 0.92)),
    ("BEIGE", Color(0.76, 0.70, 0.60)),
    ("TAN", Color(0.76, 0.64, 0.47)),
    ("BROWN", Color(0.40, 0.26, 0.13)),
    ("TAUPE", Color(0.56, 0.52, 0.47)),
]
DEFAULT_BAR_COLOR = Color(0.35, 0.35, 0.35)

# Dropdown presets for the app UI -- the "<color> TRAVELER" materials
# actually seen/requested so far. The combobox stays editable so any other
# material name can still be typed in directly.
MATERIAL_PRESETS = ["GRAY TRAVELER", "GREEN TRAVELER", "BLUE TRAVELER", "RED TRAVELER"]


def resolve_bar_color(material: str):
    m = (material or "").upper()
    for word, color in MATERIAL_COLOR_WORDS:
        if word in m:
            return color
    return DEFAULT_BAR_COLOR


def resolve_text_color(bar_color: Color):
    # simple luminance check so text stays readable on light bars (e.g. WHITE)
    luminance = 0.299 * bar_color.red + 0.587 * bar_color.green + 0.114 * bar_color.blue
    return BLACK if luminance > 0.6 else WHITE


# ---------------------------------------------------------------------------
# Product profiles: annotation coordinates calibrated per order-form layout.
# Coordinates are in reportlab space (origin bottom-left), derived from the
# top-down pdfplumber coordinates of a real annotated example
# (y_reportlab = PAGE_H - y_pdfplumber_bottom).
# ---------------------------------------------------------------------------
PROFILES = {
    "CLSS": {  # Custom Linear ShowerSlope
        "name": "Custom Linear ShowerSlope",
        "curb_affects_height": False,
        "width_cover": (0.0, PAGE_H - 331.0, 99.0, PAGE_H - 284.9),
        "width_text_pos": (19.0, PAGE_H - 327.5),
        "length_cover": (395.3, PAGE_H - 255.1, 503.6, PAGE_H - 209.0),
        "length_text_pos": (410.4, PAGE_H - 251.7),
        "thickness_cover": (331.0, PAGE_H - 495.2, 439.3, PAGE_H - 449.2),
        "thickness_text_pos": (368.3, PAGE_H - 491.9),
        "material_bar": (25.9, PAGE_H - 748.15, 220.4, PAGE_H - 718.15),
        "material_text_pos": (38.9, PAGE_H - 741.9),
        "bracket": [(576.859, PAGE_H - 305.0363), (576.859, PAGE_H - 247.0738), (515.874, PAGE_H - 247.0738)],
        # Confirmed against a real >85" example (PO247376, 101.5" wide): the
        # computed 180-degree mirror landed within 0.1" of the real bracket.
        # These are the exact real coordinates.
        "bracket_wide": [(31.097, 297.728), (31.097, 239.765), (92.082, 239.765)],
        "bracket_width": 10.0,
        "font_size_dim": 32,
        "font_size_material": 24,
    },
    "CSS": {  # Custom (point-drain) ShowerSlope
        "name": "Custom ShowerSlope (point drain)",
        "curb_affects_height": False,
        # no thickness_cover/thickness_text_pos yet -- no real example showed
        # one; entering a thickness for this product will warn and skip it.
        "width_cover": (48.08, PAGE_H - 344.81, 121.37, PAGE_H - 298.76),
        "width_text_pos": (67.6, PAGE_H - 341.4),
        "length_cover": (392.64, PAGE_H - 255.09, 500.94, PAGE_H - 209.04),
        "length_text_pos": (416.3, PAGE_H - 251.7),
        "material_bar": (25.9, PAGE_H - 748.15, 220.4, PAGE_H - 718.15),
        "material_text_pos": (38.9, PAGE_H - 741.9),
        "bracket": [(119.217, PAGE_H - 191.9602), (61.255, PAGE_H - 191.9602), (61.255, PAGE_H - 252.9448)],
        "bracket_width": 10.0,
        "font_size_dim": 32,
        "font_size_material": 24,
    },
    "CLTB": {  # Custom Linear Tile-Basin
        "name": "Custom Linear Tile-Basin",
        "curb_affects_height": True,
        "width_cover": (14.84, PAGE_H - 374.6, 100.02, PAGE_H - 333.4),
        "width_text_pos": (23.2, PAGE_H - 370.8),
        "length_cover": (351.96, PAGE_H - 243.44, 469.29, PAGE_H - 202.24),
        "length_text_pos": (368.9, PAGE_H - 239.7),
        "thickness_cover": (183.19, PAGE_H - 369.07, 260.7, PAGE_H - 327.88),
        "thickness_text_pos": (195.5, PAGE_H - 365.3),
        "material_bar": (40.66, PAGE_H - 737.42, 253.17, PAGE_H - 707.42),
        "material_text_pos": (53.7, PAGE_H - 731.1),
        "bracket": [(122.852, PAGE_H - 245.582), (64.889, PAGE_H - 245.582), (64.889, PAGE_H - 306.566)],
        "bracket_width": 10.0,
        "font_size_dim": 28,
        "font_size_material": 24,
    },
    "CTB": {  # Custom (point-drain) Tile-Basin
        "name": "Custom Tile-Basin (point drain)",
        "curb_affects_height": True,
        # no thickness_cover/thickness_text_pos yet -- see CSS note above.
        "width_cover": (18.33, PAGE_H - 381.21, 107.14, PAGE_H - 340.02),
        "width_text_pos": (28.6, PAGE_H - 377.5),
        "length_cover": (357.1, PAGE_H - 243.44, 454.77, PAGE_H - 202.24),
        "length_text_pos": (390.9, PAGE_H - 239.7),
        "material_bar": (18.75, PAGE_H - 609.6, 231.25, PAGE_H - 579.6),
        "material_text_pos": (31.75, PAGE_H - 603.3),
        "bracket": [(122.852, PAGE_H - 245.582), (64.889, PAGE_H - 245.582), (64.889, PAGE_H - 306.566)],
        "bracket_width": 10.0,
        "font_size_dim": 28,
        "font_size_material": 24,
    },
    "CFSRC": {  # Custom Flanged Surface Ready Core
        "name": "Custom Flanged SRC",
        "curb_affects_height": False,
        # SRC is always 1.5" per KBRS, but no auto-fill -- type it in each time.
        "width_cover": (42.43, PAGE_H - 375.87, 126.0, PAGE_H - 329.82),
        "width_text_pos": (67.1, PAGE_H - 372.4),
        "length_cover": (428.4, PAGE_H - 246.6, 513.69, PAGE_H - 200.55),
        "length_text_pos": (440.5, PAGE_H - 243.3),
        "thickness_cover": (306.0, PAGE_H - 458.26, 449.76, PAGE_H - 407.37),
        "thickness_text_pos": (343.9, PAGE_H - 454.2),
        "material_bar": (37.97, PAGE_H - 756.6, 230.75, PAGE_H - 726.6),
        "material_text_pos": (51.0, PAGE_H - 750.3),
        "bracket": [(193.696, PAGE_H - 225.7176), (135.734, PAGE_H - 225.7176), (135.734, PAGE_H - 286.7022)],
        "bracket_width": 10.0,
        "font_size_dim": 32,
        "font_size_material": 24,
        "font_size_thickness": 36,
    },
}

SKU_PREFIX_RE = re.compile(r"^([A-Z]+)-")


def inches_to_decimal(s: str) -> float:
    """'33 1/4' -> 33.25, '47-1/2' -> 47.5, '36' -> 36.0"""
    s = s.strip().replace("-", " ")
    parts = s.split()
    total = 0.0
    for p in parts:
        if "/" in p:
            num, den = p.split("/")
            total += float(num) / float(den)
        else:
            total += float(p)
    return total


def fmt_inches(val: float) -> str:
    """34.25 -> '34.25', 35.5 -> '35.5', 36.0 -> '36'"""
    s = f"{val:.2f}".rstrip("0").rstrip(".")
    return s if s else "0"


# ---------------------------------------------------------------------------
# Linear thickness formula -- CLSS (Linear ShowerSlope) and CLTB (Linear
# Tile-Basin) only. Per KBRS's reference chart: raw thickness = drain height
# (1.25") + 2% grade x (raw width - drain dimension "A"), rounded UP to the
# nearest 0.5". Confirmed against KBRS's own worked example: width 45, A 10
# -> distance 35 -> raw 1.95" -> rounds up to 2.0" -- matches exactly, and
# the formula's band edges (12.5/37.5/62.5/87.5") line up with the chart's
# visual step boundaries near the 12"/36"/60"/88" tick marks.
# ---------------------------------------------------------------------------
LINEAR_THICKNESS_PREFIXES = ("CLSS", "CLTB")
DRAIN_HEIGHT_IN = 1.25
SLOPE_GRADE = 0.02

DRAIN_A_RE = re.compile(
    r'drain dimension\s*["“]?a["”]?\s*[:\-]?\s*\(?([\d\s/.\-]+)"?\)?',
    re.IGNORECASE,
)


def compute_linear_thickness(raw_width_in: float, drain_a_in: float) -> float:
    """1.25" drain height + 2% grade over (width - A), rounded up to the
    nearest 0.5". Only meaningful for CLSS/CLTB (linear-drain products)."""
    distance = raw_width_in - drain_a_in
    raw = DRAIN_HEIGHT_IN + SLOPE_GRADE * distance
    return math.ceil(raw / 0.5) * 0.5


def try_extract_drain_a(order_form_path: str):
    """Best-effort: look for a real, extractable-text 'drain dimension A'
    value on the order form. Most order forms (PDF or image) are flattened
    scans with no text layer at all, so this usually finds nothing -- that's
    expected, not an error; the app falls back to manual entry. Returns the
    matched string (e.g. '6' or '10 1/2') or None."""
    if Path(order_form_path).suffix.lower() != ".pdf":
        return None  # images have no text layer to search at all
    try:
        reader = PdfReader(order_form_path)
        text = reader.pages[0].extract_text() or ""
    except Exception:
        return None
    m = DRAIN_A_RE.search(text)
    if not m:
        return None
    val = m.group(1).strip().strip('"')
    try:
        inches_to_decimal(val)  # validate it actually parses as a number
    except Exception:
        return None
    return val


def parse_production_order(pdf_path: str) -> dict:
    reader = PdfReader(pdf_path)
    text = reader.pages[0].extract_text()

    def grab(label, pattern=r"([^\n]+)"):
        m = re.search(re.escape(label) + r"\s*\n" + pattern, text)
        return m.group(1).strip() if m else None

    po_number = grab("Order No.:")
    order_date = grab("Date:")
    promised_date = grab("Promised Date:")
    so_number = grab("SO Number:")

    # ITEM line, dimensions appear as either (33 1/4"x34 1/2") or (47-1/2 x 33)
    item_match = re.search(
        r'([A-Z]+-[\w-]+):\s*(.+?)\s*\(([\d\s/-]+)"?\s*x\s*([\d\s/-]+)"?\)', text
    )
    if not item_match:
        raise ValueError(f"Could not find item/dimension line in {pdf_path}. Raw text:\n{text}")

    sku, item_name, raw_w, raw_h = item_match.groups()
    prefix_match = SKU_PREFIX_RE.match(sku)
    sku_prefix = prefix_match.group(1) if prefix_match else sku.split("-")[0]

    return {
        "po_number": po_number,
        "order_date": order_date,
        "promised_date": promised_date,
        "so_number": so_number,
        "sku": sku,
        "sku_prefix": sku_prefix,
        "item_name": item_name.strip(),
        "raw_width_in": inches_to_decimal(raw_w),
        "raw_height_in": inches_to_decimal(raw_h),
    }


# ---------------------------------------------------------------------------
# Item-based rendering. An "item" is a draggable annotation (dimension label,
# thickness, cut-for-shipping line/label, or a freeform note) as a plain
# dict, so the desktop app's editor can show/move/add/delete them before the
# final PDF is baked. Material bar/text and the origin bracket are always
# drawn automatically from the profile -- not part of the draggable items
# (the bracket especially: it's rule-driven and safety-critical for the CNC
# machine, so it isn't meant to be nudged by hand).
# ---------------------------------------------------------------------------

def make_height_item(profile: dict, oversize_h: float) -> dict:
    fsize = profile["font_size_dim"]
    x, y = profile["width_text_pos"]
    return {
        "key": "height", "kind": "text", "text": fmt_inches(oversize_h),
        "x": x, "y": y - fsize * 0.78, "font_size": fsize, "color": "orange",
        "fixed_cover": profile.get("width_cover"), "moved": False,
        "deletable": False, "editable_text": False,
    }


def make_width_item(profile: dict, oversize_w: float) -> dict:
    fsize = profile["font_size_dim"]
    x, y = profile["length_text_pos"]
    return {
        "key": "width", "kind": "text", "text": fmt_inches(oversize_w),
        "x": x, "y": y - fsize * 0.78, "font_size": fsize, "color": "orange",
        "fixed_cover": profile.get("length_cover"), "moved": False,
        "deletable": False, "editable_text": False,
    }


def make_thickness_item(profile: dict, thickness: str) -> dict:
    fsize = profile["font_size_dim"]
    tsize = profile.get("font_size_thickness", fsize)
    x, y = profile["thickness_text_pos"]
    return {
        "key": "thickness", "kind": "text", "text": thickness,
        "x": x, "y": y - tsize * 0.78, "font_size": tsize, "color": "orange",
        "fixed_cover": profile.get("thickness_cover"), "moved": False,
        "deletable": False, "editable_text": True,
    }


def compute_default_items(profile: dict, oversize_w: float, oversize_h: float, thickness: str = "") -> list:
    items = [make_height_item(profile, oversize_h), make_width_item(profile, oversize_w)]
    if thickness and "thickness_text_pos" in profile:
        items.append(make_thickness_item(profile, thickness))
    return items


def make_cut_line_items() -> list:
    """Default cut-for-shipping dashed line + label. There's no fixed rule
    for where the cut goes -- drag it to the real position for that job."""
    line = {
        "key": "cut_line", "kind": "line", "x": PAGE_W / 2, "y0": 240.0, "y1": 540.0,
        "color": "orange", "line_width": 10.0, "dashed": True, "deletable": True,
    }
    label = {
        "key": "cut_label", "kind": "text", "text": "Cut for\nshipping",
        "x": PAGE_W / 2 - 90, "y": 390.0, "font_size": 20, "color": "orange",
        "fixed_cover": None, "moved": True, "deletable": True, "editable_text": True,
    }
    return [line, label]


_note_counter = [0]


def make_note_item(text: str = "New note", x: float = PAGE_W / 2 - 60, y: float = 400.0,
                    font_size: int = 20, color: str = "orange") -> dict:
    _note_counter[0] += 1
    return {
        "key": f"note_{_note_counter[0]}", "kind": "text", "text": text,
        "x": x, "y": y, "font_size": font_size, "color": color,
        "fixed_cover": None, "moved": True, "deletable": True, "editable_text": True,
    }


def rotate_point(pt: tuple, pivot: tuple, degrees: int) -> tuple:
    """Rotate pt around pivot by an exact multiple of 90 degrees (no float
    drift, unlike a general sin/cos rotation)."""
    dx, dy = pt[0] - pivot[0], pt[1] - pivot[1]
    degrees = degrees % 360
    if degrees == 90:
        dx, dy = -dy, dx
    elif degrees == 180:
        dx, dy = -dx, -dy
    elif degrees == 270:
        dx, dy = dy, -dx
    return (pivot[0] + dx, pivot[1] + dy)


def render_page(profile: dict, material: str, items: list, wide_origin: bool = False,
                 bracket_offset: tuple = (0.0, 0.0), bracket_rotation: int = 0) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(PAGE_W, PAGE_H))

    # material bar, color derived from the material name (always automatic).
    # Width is sized to fit whatever material text is actually entered
    # (with padding), not just the one calibrated example -- a longer name
    # (e.g. "GRAY TRAVELER") would otherwise overflow past a fixed-width bar
    # as invisible white-on-white text past its right edge.
    bar_color = resolve_bar_color(material)
    text_color = resolve_text_color(bar_color)
    bx0, by0, bx1, by1 = profile["material_bar"]
    fsize_material = profile["font_size_material"]
    label_text = material.upper()
    text_w = stringWidth(label_text, "Helvetica-Bold", fsize_material)
    pad = 10
    bar_w = max(bx1 - bx0, text_w + pad * 2)
    c.setFillColor(bar_color)
    c.rect(bx0, by0, bar_w, by1 - by0, stroke=0, fill=1)  # square corners, no pill/stadium shape
    c.setFillColor(text_color)
    c.setFont("Helvetica-Bold", fsize_material)
    mx, _my = profile["material_text_pos"]
    # Center the text vertically within the bar itself (rather than trusting
    # the originally-calibrated y position), so it always sits on the bar
    # regardless of small calibration drift.
    baseline_y = (by0 + by1) / 2 - fsize_material * 0.35
    c.drawString(mx, baseline_y, label_text)

    # draggable items
    for item in items:
        if item["kind"] == "line":
            c.setStrokeColor(COLOR_MAP.get(item["color"], ORANGE))
            c.setLineWidth(item.get("line_width", 10.0))
            c.setDash([6, 6] if item.get("dashed") else [])
            c.line(item["x"], item["y0"], item["x"], item["y1"])
            c.setDash([])
        elif item["kind"] == "text":
            lines = item["text"].split("\n")
            fsize = item["font_size"]
            color = COLOR_MAP.get(item["color"], ORANGE)
            # 1) blank out the calibrated original-value area (e.g. hides the
            #    customer's handwritten raw measurement) when present.
            if not item.get("moved") and item.get("fixed_cover"):
                x0, y0, x1, y1 = item["fixed_cover"]
                c.setFillColor(WHITE)
                c.rect(x0, y0, x1 - x0, y1 - y0, stroke=0, fill=1)
            # 2) always also paint a padded white box snug around the new
            #    text itself, so numbers/thickness stay clearly readable on
            #    top of the drawing even if the scan doesn't line up exactly
            #    with the calibrated cover box above.
            if item.get("cover", True):
                w = max(stringWidth(ln, "Helvetica-Bold", fsize) for ln in lines) if lines else 0
                h = fsize * 1.15 * len(lines)
                pad = 6
                c.setFillColor(WHITE)
                c.rect(item["x"] - pad, item["y"] - pad, w + pad * 2, h + pad * 2, stroke=0, fill=1)
            c.setFillColor(color)
            c.setFont("Helvetica-Bold", fsize)
            for i, ln in enumerate(lines):
                c.drawString(item["x"], item["y"] - i * fsize * 1.15, ln)

    # origin bracket (CNC/CAD reference corner) -- automatic by default, but
    # draggable and rotatable in the app's live editor when a calibrated
    # position turns out to be wrong for a given order; bracket_offset is
    # (0, 0) and bracket_rotation is 0 unless the user has manually adjusted
    # it there.
    pts = profile["bracket_wide"] if (wide_origin and "bracket_wide" in profile) else profile["bracket"]
    dx, dy = bracket_offset
    pts = [(px + dx, py + dy) for px, py in pts]
    if bracket_rotation:
        pivot = pts[1]  # the elbow -- the actual corner vertex the bracket marks
        pts = [rotate_point(pt, pivot, bracket_rotation) for pt in pts]
    c.setStrokeColor(ORANGE)
    c.setLineWidth(profile["bracket_width"])
    p = c.beginPath()
    p.moveTo(pts[0][0], pts[0][1])
    for pt in pts[1:]:
        p.lineTo(pt[0], pt[1])
    c.drawPath(p, stroke=1, fill=0)

    c.save()
    buf.seek(0)
    return buf.read()


def build_overlay(profile: dict, oversize_w: float, oversize_h: float, material: str,
                   thickness: str = "", wide_origin: bool = False) -> bytes:
    """Back-compat wrapper: renders the default (non-edited) item layout."""
    items = compute_default_items(profile, oversize_w, oversize_h, thickness=thickness)
    return render_page(profile, material, items, wide_origin=wide_origin)


def merge_pdf(order_form_pdf: str, production_order_pdf: str, overlay_bytes: bytes,
              out_path: str, rotate_deg: int = 90):
    order_form_pdf = ensure_pdf(order_form_pdf)  # converts image scans (jpg/png/etc.) to PDF
    overlay_reader = PdfReader(io.BytesIO(overlay_bytes))
    order_reader = PdfReader(order_form_pdf)
    prod_reader = PdfReader(production_order_pdf)

    writer = PdfWriter()
    page0 = order_reader.pages[0]
    page0.merge_page(overlay_reader.pages[0])
    writer.add_page(page0)

    page1 = prod_reader.pages[0]
    page1.rotate(rotate_deg)
    writer.add_page(page1)

    with open(out_path, "wb") as f:
        writer.write(f)


def build_output(order_form_pdf: str, production_order_pdf: str, material: str,
                  out_path: str, thickness: str = None, curb_depth_in: float = DEFAULT_CURB_DEPTH_IN,
                  rotate_deg: int = 90):
    meta = parse_production_order(production_order_pdf)
    profile = PROFILES.get(meta["sku_prefix"])
    if not profile:
        raise ValueError(
            f"No annotation profile for SKU prefix '{meta['sku_prefix']}' "
            f"(item: {meta['item_name']}). Known profiles: {list(PROFILES)}. "
            f"Send a sample blank order form + finished markup for this product line to add it."
        )

    oversize_w = meta["raw_width_in"] + 1
    if profile.get("curb_affects_height"):
        oversize_h = meta["raw_height_in"] - curb_depth_in + 1
    else:
        oversize_h = meta["raw_height_in"] + 1

    wide_origin = "bracket_wide" in profile and meta["raw_width_in"] > WIDE_PANEL_THRESHOLD_IN

    thickness = (thickness or "").strip()
    thickness_unsupported = bool(thickness) and "thickness_text_pos" not in profile

    overlay_bytes = build_overlay(profile, oversize_w, oversize_h, material,
                                   thickness=thickness, wide_origin=wide_origin)
    merge_pdf(order_form_pdf, production_order_pdf, overlay_bytes, out_path, rotate_deg=rotate_deg)

    return {
        **meta,
        "oversize_width_in": oversize_w,
        "oversize_height_in": oversize_h,
        "material": material,
        "thickness": thickness,
        "thickness_unsupported": thickness_unsupported,
        "curb_depth_in": curb_depth_in if profile.get("curb_affects_height") else None,
        "out_path": out_path,
        "wide_origin": wide_origin,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--order-form")
    ap.add_argument("--production-order")
    ap.add_argument("--material", default="")
    ap.add_argument("--thickness", default=None, help="e.g. 2\" or 1.5\" (blank = not shown; works on any product with a calibrated position)")
    ap.add_argument("--curb-depth", type=float, default=DEFAULT_CURB_DEPTH_IN)
    ap.add_argument("--out")
    ap.add_argument("--rotate", type=int, default=90)
    ap.add_argument("--batch")
    ap.add_argument("--manifest")
    ap.add_argument("--outdir", default="./done")
    args = ap.parse_args()

    if args.batch:
        folder = Path(args.batch)
        outdir = Path(args.outdir)
        outdir.mkdir(parents=True, exist_ok=True)
        manifest = {}
        if args.manifest:
            with open(args.manifest, newline="") as f:
                for row in csv.DictReader(f):
                    manifest[row["po_number"].strip().upper()] = row

        po_re = re.compile(r"(PO\d+)", re.IGNORECASE)
        candidate_exts = {".pdf"} | IMAGE_EXTS
        pairs = {}
        for f in folder.iterdir():
            if not f.is_file() or f.suffix.lower() not in candidate_exts:
                continue
            m = po_re.search(f.name)
            if not m:
                print(f"SKIP (no PO# in filename): {f.name}")
                continue
            po = m.group(1).upper()
            pairs.setdefault(po, {})
            if f.suffix.lower() == ".pdf" and (
                "production" in f.name.lower() or "purchaseorder" in f.name.lower()
            ):
                pairs[po]["production"] = str(f)
            else:
                pairs[po]["order_form"] = str(f)

        for po, files in pairs.items():
            if "order_form" not in files or "production" not in files:
                print(f"SKIP {po}: missing one of order_form/production files -> {files}")
                continue
            row = manifest.get(po, {})
            material = (row.get("material") or "").strip()
            thickness = (row.get("thickness") or "").strip() or None
            curb_depth = float(row["curb_depth"]) if row.get("curb_depth") else DEFAULT_CURB_DEPTH_IN
            if not material:
                print(f"SKIP {po}: no material specified in manifest.csv")
                continue
            try:
                meta = build_output(
                    files["order_form"], files["production"], material,
                    str(outdir / f"{po}.pdf"), thickness=thickness, curb_depth_in=curb_depth,
                )
                wide_note = "  [WIDE PANEL -> origin moved to bottom-left, verify!]" if meta["wide_origin"] else ""
                thick_note = "  [THICKNESS ENTERED BUT NOT SUPPORTED FOR THIS PRODUCT -- skipped]" if meta["thickness_unsupported"] else ""
                print(f"OK {po}: -> {meta['out_path']} ({meta['oversize_width_in']} x {meta['oversize_height_in']}){wide_note}{thick_note}")
            except Exception as e:
                print(f"FAIL {po}: {e}")
        return

    if not (args.order_form and args.production_order and args.out):
        ap.error("single-order mode requires --order-form --production-order --out (or use --batch)")
    if not args.material:
        ap.error("--material is required (e.g. \"GRAY TRAVELER\")")

    meta = build_output(args.order_form, args.production_order, args.material, args.out,
                         thickness=args.thickness, curb_depth_in=args.curb_depth, rotate_deg=args.rotate)
    print(f"Wrote {meta['out_path']}")
    print(f"  PO {meta['po_number']} / SO {meta['so_number']}  ({meta['sku']})")
    print(f"  Raw: {meta['raw_width_in']}\" x {meta['raw_height_in']}\"  ->  Oversize: {meta['oversize_width_in']}\" x {meta['oversize_height_in']}\"")
    if meta["curb_depth_in"] is not None:
        print(f"  Curb depth used: {meta['curb_depth_in']}\"")
    print(f"  Material: {meta['material']}   Thickness: {meta['thickness'] or '(none shown)'}")
    if meta["thickness_unsupported"]:
        print(f"  ⚠ Thickness '{meta['thickness']}' entered but this product ({meta['sku_prefix']}) has no calibrated "
              f"position for it yet -- not drawn. Send a sample so I can add it.")
    if meta["wide_origin"]:
        print(f"  WIDE PANEL (width {meta['raw_width_in']}\" > {WIDE_PANEL_THRESHOLD_IN}\"): origin moved to bottom-left. Verify placement.")


if __name__ == "__main__":
    main()
