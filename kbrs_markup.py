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
    SRC-D1 Custom SRC, D1 variant -- pilot hole, no flange (auto-adds a
           '0.5" PILOT HOLE - NO FLANGE' note; reuses CFSRC's layout, not yet
           confirmed against a real D1 example -- see EXTENDED_SKU_PREFIXES)
    SRC-D3 Custom SRC, D3 variant -- flanged (auto-adds the same flange note
           as Blue Traveler; reuses CFSRC's layout, not yet confirmed against
           a real D3 example -- see EXTENDED_SKU_PREFIXES)
Each of the first five was calibrated from one real finished example.
SRC-D1/D3 reuse CFSRC's already-confirmed coordinates rather than a new
guess, since the only known difference is which note gets auto-added -- flag
it if a real example shows the geometry itself actually differs. New product
lines need a sample order form + finished markup to add a profile.

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
import json
import math
import os
import platform
import re
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

import pikepdf
from pypdf import PdfReader, PdfWriter, Transformation
from reportlab.pdfgen import canvas
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.lib.colors import Color
from reportlab.lib.utils import ImageReader
import io

# The default measurement-overlay color ("orange" everywhere in this file)
# is a per-install preference, not a hardcoded constant -- different
# computers running this app can be set to different accent colors (e.g. to
# visually tell whose copy generated a given production sheet) via
# set_accent_color(), persisted here so it survives across launches.
CONFIG_PATH = Path.home() / ".kbrs_markup_config.json"
DEFAULT_ACCENT_HEX = "#f2842f"


def _hex_to_color(hex_str: str) -> Color:
    hex_str = hex_str.lstrip("#")
    r, g, b = (int(hex_str[i:i + 2], 16) / 255 for i in (0, 2, 4))
    return Color(r, g, b)


def _load_config() -> dict:
    try:
        with open(CONFIG_PATH) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError, ValueError):
        return {}


def _save_config(updates: dict) -> None:
    """Merge updates into the existing config rather than overwriting it --
    accent color and default output folder are independent settings sharing
    one file."""
    config = _load_config()
    config.update(updates)
    try:
        CONFIG_PATH.write_text(json.dumps(config))
    except OSError:
        pass


def get_accent_hex() -> str:
    return _load_config().get("accent_color", DEFAULT_ACCENT_HEX)


def set_accent_color(hex_str: str) -> None:
    """Persist a new accent color and apply it for the rest of this run."""
    global ORANGE
    ORANGE = _hex_to_color(hex_str)
    COLOR_MAP["orange"] = ORANGE
    _save_config({"accent_color": hex_str})


def get_default_output_dir() -> str | None:
    return _load_config().get("default_output_dir")


def set_default_output_dir(path: str) -> None:
    _save_config({"default_output_dir": path})


# A rolling history of recently generated orders (newest first), each a full
# snapshot of that order's inputs AND its live-editor markup (dragged item
# positions, brackets, notes, cut line, background rotate/resize) -- lets the
# app reopen one later to make a single quick change without re-marking the
# whole drawing up from scratch. Kept in a separate file from the small
# accent-color/output-dir config since this one can grow much larger.
RECENT_ORDERS_PATH = Path.home() / ".kbrs_markup_recent.json"
MAX_RECENT_ORDERS = 15


def get_recent_orders() -> list:
    try:
        with open(RECENT_ORDERS_PATH) as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (FileNotFoundError, json.JSONDecodeError, OSError, ValueError):
        return []


def save_recent_order(entry: dict) -> None:
    """Push a snapshot to the front of the recent-orders list. Regenerating
    the same order (same output name) replaces its earlier entry instead of
    duplicating it. Capped at MAX_RECENT_ORDERS, oldest dropped first."""
    entries = [e for e in get_recent_orders() if e.get("label") != entry.get("label")]
    entries.insert(0, entry)
    entries = entries[:MAX_RECENT_ORDERS]
    try:
        RECENT_ORDERS_PATH.write_text(json.dumps(entries))
    except OSError:
        pass


def clear_recent_orders() -> None:
    try:
        RECENT_ORDERS_PATH.write_text(json.dumps([]))
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Self-update (Windows packaged build only). build-windows.yml stamps every
# build with the git commit SHA it was built from, both bundled next to the
# exe as version.txt and uploaded standalone as its own tiny release asset --
# the running app can cheaply check "is a newer build published?" on launch
# without downloading the whole ~32MB zip just to find out, then download and
# apply it itself if the user asks to. Every step here is best-effort and
# fails safe: a failed check/download/stage never touches the current,
# working install; only apply_update_and_relaunch() (called after a
# successful download+stage) touches it, and even that keeps the old install
# intact until the new one is confirmed in place.
# ---------------------------------------------------------------------------
GITHUB_REPO = "kbrs-dev/K-COFs-app"
UPDATE_RELEASE_TAG = "windows-latest-build"
_RELEASE_BASE = f"https://github.com/{GITHUB_REPO}/releases/download/{UPDATE_RELEASE_TAG}"
UPDATE_VERSION_URL = f"{_RELEASE_BASE}/version.txt"
UPDATE_ZIP_URL = f"{_RELEASE_BASE}/KBRS-Markup-Windows.zip"


def is_frozen_windows_build() -> bool:
    """True only for an actual packaged Windows .exe (not the Mac build,
    and not a `python3 app.py` source run) -- the only case self-update
    applies to."""
    return bool(getattr(sys, "frozen", False)) and platform.system() == "Windows"


def get_local_version() -> str | None:
    """The git commit SHA this running build was made from. None if this
    isn't a frozen Windows build, or version.txt is missing (e.g. a build
    from before this feature existed)."""
    if not is_frozen_windows_build():
        return None
    try:
        return (Path(os.path.dirname(sys.executable)) / "version.txt").read_text().strip() or None
    except OSError:
        return None


class UpdateCheckError(Exception):
    """Raised when the check itself fails (network/timeout/unexpected
    response) -- distinct from a successful check that just finds no newer
    build, so callers can tell you "the check failed" instead of falsely
    claiming you're already up to date. That distinction was missing before
    (get_remote_version() silently returning None either way), which is
    exactly how a real network failure got reported as "up to date"."""


def get_remote_version(timeout: float = 10.0) -> str:
    """The latest published build's commit SHA. Raises UpdateCheckError
    (never silently swallowed) if the request fails for any reason."""
    req = urllib.request.Request(UPDATE_VERSION_URL, headers={"User-Agent": "KBRS-Markup-Updater"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            text = resp.read().decode("utf-8").strip()
    except Exception as e:
        raise UpdateCheckError(f"{type(e).__name__}: {e}") from e
    if not text:
        raise UpdateCheckError("update server returned an empty response")
    return text


def check_for_update() -> str | None:
    """The newer version's commit SHA if an update is available, None if
    already current. Raises UpdateCheckError if the check itself failed --
    callers must not treat that the same as "no update" (see
    UpdateCheckError's docstring)."""
    local = get_local_version()
    if local is None:
        return None
    remote = get_remote_version()  # raises UpdateCheckError on failure
    if remote == local:
        return None
    return remote


def download_update(progress_cb=None) -> str:
    """Downloads the latest Windows build zip to a temp file and returns its
    path. progress_cb(bytes_read, total_bytes), if given, is called
    periodically (total_bytes is -1 if the server didn't send a length)."""
    fd, zip_path = tempfile.mkstemp(suffix=".zip", prefix="kbrs_update_")
    os.close(fd)
    with urllib.request.urlopen(UPDATE_ZIP_URL, timeout=30) as resp:
        total = int(resp.headers.get("Content-Length", -1))
        read = 0
        with open(zip_path, "wb") as f:
            while True:
                chunk = resp.read(1024 * 256)
                if not chunk:
                    break
                f.write(chunk)
                read += len(chunk)
                if progress_cb:
                    progress_cb(read, total)
    return zip_path


def stage_update(zip_path: str) -> str:
    """Extracts the downloaded zip to a fresh temp staging folder and
    returns the path to the extracted 'KBRS Markup' folder inside it. Never
    touches the current install -- if this raises, nothing has changed."""
    staging_root = tempfile.mkdtemp(prefix="kbrs_update_staged_")
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(staging_root)
    staged_app_dir = os.path.join(staging_root, "KBRS Markup")
    if not os.path.isdir(staged_app_dir):
        raise RuntimeError(
            f"Downloaded update zip didn't contain a 'KBRS Markup' folder as expected "
            f"(found: {os.listdir(staging_root)})"
        )
    return staged_app_dir


def apply_update_and_relaunch(staged_app_dir: str) -> None:
    """Writes a small batch script that waits for this process to fully
    exit (releasing its file locks), swaps the staged new build into place,
    relaunches the app, and cleans up after itself -- then launches that
    script as a fully detached process and exits this one immediately so
    the swap can proceed. If the swap fails for any reason, the script
    restores the previous install rather than leaving a half-updated,
    broken folder; if it can never get exclusive access at all, it gives up
    and relaunches whatever's already there. Only call this after
    stage_update() has already succeeded -- the current install isn't
    touched until this point."""
    app_dir = os.path.dirname(sys.executable)
    exe_name = os.path.basename(sys.executable)
    staging_root = os.path.dirname(staged_app_dir)
    old_dir = app_dir + "_old"
    old_dir_name = os.path.basename(old_dir)

    bat_fd, bat_path = tempfile.mkstemp(suffix=".bat", prefix="kbrs_apply_update_")
    os.close(bat_fd)

    script = (
        "@echo off\r\n"
        "setlocal\r\n"
        f'set "APP_DIR={app_dir}"\r\n'
        f'set "OLD_DIR={old_dir}"\r\n'
        f'set "OLD_DIR_NAME={old_dir_name}"\r\n'
        f'set "STAGED_DIR={staged_app_dir}"\r\n'
        f'set "STAGING_ROOT={staging_root}"\r\n'
        f'set "EXE_NAME={exe_name}"\r\n'
        "\r\n"
        'if exist "%OLD_DIR%" rmdir /s /q "%OLD_DIR%" >nul 2>&1\r\n'
        "\r\n"
        "set tries=0\r\n"
        ":waitloop\r\n"
        'ren "%APP_DIR%" "%OLD_DIR_NAME%" >nul 2>&1\r\n'
        'if exist "%OLD_DIR%" goto renamed\r\n'
        "set /a tries+=1\r\n"
        "if %tries% GEQ 30 goto giveup\r\n"
        "timeout /t 1 /nobreak >nul\r\n"
        "goto waitloop\r\n"
        "\r\n"
        ":renamed\r\n"
        'move /y "%STAGED_DIR%" "%APP_DIR%" >nul 2>&1\r\n'
        'if exist "%APP_DIR%\\%EXE_NAME%" goto success\r\n'
        "\r\n"
        "REM the move failed -- restore the previous install so the app still works\r\n"
        'rmdir /s /q "%APP_DIR%" >nul 2>&1\r\n'
        'move /y "%OLD_DIR%" "%APP_DIR%" >nul 2>&1\r\n'
        'start "" "%APP_DIR%\\%EXE_NAME%"\r\n'
        "goto cleanup\r\n"
        "\r\n"
        ":success\r\n"
        'rmdir /s /q "%OLD_DIR%" >nul 2>&1\r\n'
        'start "" "%APP_DIR%\\%EXE_NAME%"\r\n'
        "goto cleanup\r\n"
        "\r\n"
        ":giveup\r\n"
        "REM couldn't get exclusive access after 30s -- give up and relaunch\r\n"
        "REM whatever's there rather than leaving the app closed\r\n"
        'start "" "%APP_DIR%\\%EXE_NAME%"\r\n'
        "goto cleanup\r\n"
        "\r\n"
        ":cleanup\r\n"
        'rmdir /s /q "%STAGING_ROOT%" >nul 2>&1\r\n'
        'del "%~f0"\r\n'
    )
    Path(bat_path).write_text(script)

    # CREATE_NO_WINDOW suppresses the console window this batch script would
    # otherwise flash on screen. NOT combined with DETACHED_PROCESS -- the
    # two are documented by Microsoft as mutually exclusive, and unnecessary
    # here anyway: this app.exe itself is windowed (console=False in the
    # PyInstaller spec), so it has no console for the child to inherit or
    # need detaching from in the first place.
    CREATE_NEW_PROCESS_GROUP = 0x00000200
    CREATE_NO_WINDOW = 0x08000000
    subprocess.Popen(
        ["cmd.exe", "/c", bat_path],
        creationflags=CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW,
        close_fds=True,
        # Without an explicit cwd, this inherits the CURRENTLY RUNNING app's
        # working directory -- which for a double-clicked frozen .exe is
        # its own app_dir. cmd.exe then holds app_dir as ITS OWN current
        # directory, and Windows refuses to rename a directory a live
        # process is sitting in -- so the :waitloop's `ren` above failed on
        # every single try (all 30 of them, each after a visible 1s
        # `timeout` window) and fell through to :giveup, relaunching the
        # untouched old build every time. cwd=tempfile.gettempdir() keeps
        # this script's own directory completely outside app_dir, so the
        # rename can actually succeed once this process (not cmd.exe) has
        # exited and released its own lock.
        cwd=tempfile.gettempdir(),
    )
    os._exit(0)


ORANGE = _hex_to_color(get_accent_hex())
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
_FLATTENED_PDF_CACHE = {}  # original path -> (mtime, flattened pdf path)


def _flatten_pdf(path: str) -> str:
    """Bakes any fillable AcroForm field values and Adobe comment/markup
    annotations directly into the page content, so they show up the same way
    in the live preview and final export as they do in Acrobat -- without
    having to manually export to JPG first to force the flattening. A no-op
    (returns the original path) if the PDF has no form fields or annotations
    to begin with, or if it can't be opened (encrypted/corrupt -- falls back
    to using the file as-is rather than blocking the whole import)."""
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        mtime = None
    cached = _FLATTENED_PDF_CACHE.get(path)
    if cached and cached[0] == mtime and os.path.isfile(cached[1]):
        return cached[1]

    try:
        with pikepdf.open(path) as pdf:
            has_form = "/AcroForm" in pdf.Root
            has_annots = any("/Annots" in page for page in pdf.pages)
            if not has_form and not has_annots:
                _FLATTENED_PDF_CACHE[path] = (mtime, path)
                return path
            pdf.generate_appearance_streams()
            pdf.flatten_annotations(mode="all")
            fd, out_path = tempfile.mkstemp(suffix=".pdf", prefix="kbrs_flat_")
            os.close(fd)
            pdf.save(out_path)
    except Exception:
        _FLATTENED_PDF_CACHE[path] = (mtime, path)
        return path

    _FLATTENED_PDF_CACHE[path] = (mtime, out_path)
    return out_path


def ensure_pdf(path: str) -> str:
    """If `path` is an image (jpg/png/etc.), wrap it in a one-page PDF sized
    to match the image's own true pixel proportions, and return the path to
    that converted PDF (cached by path+mtime so repeated preview refreshes
    don't reconvert every time). If `path` is already a .pdf, returns it
    unchanged.

    The page is deliberately NOT resized or stretched to Letter (612x792)
    here -- a real order form isn't always that shape (landscape photos,
    forms saved at A4, etc.), and forcing it to fit would visibly distort
    the customer's actual drawing. Every calibrated PROFILES coordinate
    stays defined in a fixed Letter-space reference regardless of the real
    page's size; get_page_size() + the scaling in merge_pdf() (and the live
    editor's canvas math) are what reconcile the two -- the scan itself is
    never touched."""
    ext = Path(path).suffix.lower()
    if ext == ".pdf":
        return _flatten_pdf(path)
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
    img_reader = ImageReader(path)
    img_w, img_h = img_reader.getSize()
    # img_w/img_h are the image's raw PIXEL dimensions -- a modern phone
    # photo can be several thousand pixels on a side, which would otherwise
    # become a page that many POINTS across (tens of inches), forcing
    # constant scrolling to see any of it. Scale down (preserving the image's
    # true proportions -- never distorting it) so the longer edge matches a
    # normal page's long edge instead.
    long_edge = max(img_w, img_h)
    if long_edge > PAGE_H:
        page_scale = PAGE_H / long_edge
        img_w, img_h = img_w * page_scale, img_h * page_scale
    c = canvas.Canvas(out_path, pagesize=(img_w, img_h))
    c.drawImage(img_reader, 0, 0, width=img_w, height=img_h)
    c.save()
    _IMAGE_PDF_CACHE[path] = (mtime, out_path)
    return out_path


def _effective_page_size(page) -> tuple:
    """(width, height) as the page is actually displayed, accounting for its
    /Rotate attribute -- the mediabox stays in the page's own un-rotated
    coordinate space, /Rotate just tells viewers to rotate on display, so a
    90/270-rotated page's effective width/height are swapped from what its
    raw mediabox says."""
    w, h = float(page.mediabox.width), float(page.mediabox.height)
    if page.rotation % 180 == 90:
        w, h = h, w
    return w, h


def get_page_size(order_form_pdf: str) -> tuple:
    """Real (width, height) in points of the order-form PDF's first page as
    displayed, after ensure_pdf() conversion if needed. Used by the live
    editor to scale canvas coordinates between the real page and the fixed
    Letter-space (PAGE_W x PAGE_H) that PROFILES calibration assumes."""
    pdf_path = ensure_pdf(order_form_pdf)
    reader = PdfReader(pdf_path)
    return _effective_page_size(reader.pages[0])


_BG_TRANSFORM_CACHE = {}  # (path, mtime, rotation, scale) -> transformed pdf path
_NORMALIZED_PAGE_CACHE = {}  # (path, mtime) -> normalized-to-portrait pdf path
_BG_RENDER_SCALE = 2.5  # comfortably print-quality even after a downscale


def _render_pil(pdf_path: str):
    import pypdfium2 as pdfium  # local import: only needed for this rare path
    pdf = pdfium.PdfDocument(pdf_path)
    pil_img = pdf[0].render(scale=_BG_RENDER_SCALE).to_pil()
    pdf.close()
    return pil_img


def _wrap_pil_as_pdf(pil_img, page_w: float, page_h: float, offset_x: float = 0.0,
                      offset_y: float = 0.0, draw_w: float = None, draw_h: float = None) -> str:
    """Draws pil_img onto a fresh page_w x page_h PDF page at the given
    offset/size (defaulting to filling the whole page), returns the path."""
    if draw_w is None:
        draw_w, draw_h = page_w, page_h
    fd, out_path = tempfile.mkstemp(suffix=".pdf", prefix="kbrs_bgtransform_")
    os.close(fd)
    c = canvas.Canvas(out_path, pagesize=(page_w, page_h))
    c.drawImage(ImageReader(pil_img), offset_x, offset_y, width=draw_w, height=draw_h)
    c.save()
    return out_path


def normalize_to_portrait_page(order_form_path: str) -> str:
    """Every exported/previewed order form page is always exactly
    PAGE_W x PAGE_H (portrait Letter, 8.5x11) -- a landscape scan (common
    for long linear panels) gets rotated to portrait first; whatever's left
    over after that is fit inside the page preserving its own proportions
    (never stretched/squished), centered with a blank margin on whichever
    axis doesn't exactly fill it. This is the baseline get_transformed_
    order_form() builds on -- combined with merge_pdf() now always scaling
    by the fixed canonical->real ratio, the two together mean that ratio is
    just 1:1 for the overwhelmingly common case, eliminating the whole
    class of scale/aspect distortion bugs at the source rather than
    reconciling them after the fact. Cached by path+mtime.

    Deliberately does NOT auto-rotate a landscape-shaped source to portrait:
    a landscape image could need +90 or -90 to read right-side-up depending
    on which way the customer's camera/scanner happened to be turned, and
    there's no reliable way to tell which from the image alone -- guessing
    wrong actively swaps width/height calibration (worse than just leaving
    it landscape-shaped, letterboxed here). Use the existing manual "Rotate
    drawing" control for that; it already correctly repositions calibrated
    items to match (see rotate_overlay_for_page()), since a human picking
    the direction can just look at the result and try the other way if it's
    wrong."""
    base_path = ensure_pdf(order_form_path)
    try:
        mtime = os.path.getmtime(order_form_path)
    except OSError:
        mtime = None
    cache_key = (order_form_path, mtime)
    cached = _NORMALIZED_PAGE_CACHE.get(cache_key)
    if cached and os.path.isfile(cached):
        return cached

    pil_img = _render_pil(base_path)
    img_w_pts, img_h_pts = pil_img.width / _BG_RENDER_SCALE, pil_img.height / _BG_RENDER_SCALE
    fit_scale = min(PAGE_W / img_w_pts, PAGE_H / img_h_pts)
    draw_w, draw_h = img_w_pts * fit_scale, img_h_pts * fit_scale
    offset_x, offset_y = (PAGE_W - draw_w) / 2, (PAGE_H - draw_h) / 2

    out_path = _wrap_pil_as_pdf(pil_img, PAGE_W, PAGE_H, offset_x, offset_y, draw_w, draw_h)
    _NORMALIZED_PAGE_CACHE[cache_key] = out_path
    return out_path


def get_transformed_order_form(order_form_path: str, rotation: int = 0, scale: float = 1.0,
                                contrast: float = 1.0) -> str:
    """A version of the order-form PDF -- already normalized to a portrait
    PAGE_W x PAGE_H page by normalize_to_portrait_page() -- with an
    additional user-requested rotation (0/90/180/270), scale (1.0 =
    unchanged), and contrast (1.0 = unchanged; >1.0 darkens lines/text
    against the background, for a faint CAD/CAM export like Aspire's PDF
    output or a washed-out scan) applied on top, for reorienting/resizing/
    darkening a drawing that's still awkward after the automatic
    normalization. Cached by path+mtime+rotation+scale+contrast. Returns the
    plain normalized path unchanged if all three are at their defaults (by
    far the common case).

    Implemented by rendering the page to a high-resolution image and
    re-wrapping that at the transformed size (same approach ensure_pdf()
    uses for image scans), rather than a PDF-level rotate/scale -- a PDF
    page's /Rotate flag doesn't change its underlying raw content
    coordinate space, and merge_pdf()'s overlay compositing operates in
    that raw space, so a metadata-only rotation would leave the overlay
    landing in the wrong place relative to the visibly-rotated background.
    Contrast is applied for the same reason it has to go through the image
    pipeline at all: there's no PDF-content-stream equivalent of "make the
    lines darker" for an arbitrary vector or scanned source -- only a
    rendered image can be leveled/contrasted."""
    base_path = normalize_to_portrait_page(order_form_path)
    rotation = rotation % 360
    if rotation == 0 and abs(scale - 1.0) < 0.001 and abs(contrast - 1.0) < 0.001:
        return base_path
    try:
        mtime = os.path.getmtime(order_form_path)
    except OSError:
        mtime = None
    cache_key = (order_form_path, mtime, rotation, round(scale, 3), round(contrast, 3))
    cached = _BG_TRANSFORM_CACHE.get(cache_key)
    if cached and os.path.isfile(cached):
        return cached

    pil_img = _render_pil(base_path)
    if abs(contrast - 1.0) >= 0.001:
        from PIL import ImageEnhance  # local import: only needed for this rare path
        pil_img = ImageEnhance.Contrast(pil_img).enhance(contrast)
    if rotation:
        # PIL rotates counter-clockwise for positive angles; PDF /Rotate and
        # the app's other 90-degree rotations (bracket, cut line) are
        # clockwise, so negate to match that convention.
        pil_img = pil_img.rotate(-rotation, expand=True)
    if abs(scale - 1.0) >= 0.001:
        new_size = (max(1, round(pil_img.width * scale)), max(1, round(pil_img.height * scale)))
        pil_img = pil_img.resize(new_size)

    page_w, page_h = pil_img.width / _BG_RENDER_SCALE, pil_img.height / _BG_RENDER_SCALE
    out_path = _wrap_pil_as_pdf(pil_img, page_w, page_h)
    _BG_TRANSFORM_CACHE[cache_key] = out_path
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
    ("PURPLE", Color(0.29, 0.0, 0.51)),
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
MATERIAL_PRESETS = ["GRAY TRAVELER", "GREEN TRAVELER", "BLUE TRAVELER", "RED TRAVELER", "PURPLE TRAVELER"]


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
    # SRC-D1/SRC-D3: the two drain-hole variants of the same SRC product as
    # CFSRC above (D1 = pilot hole, no flange; D3 = flanged) -- reuse CFSRC's
    # calibrated layout as-is (same physical order form/diagram, confirmed
    # real coordinates, not a new guess) since the only confirmed difference
    # between the variants is which note gets auto-added, not the geometry.
    # If a real D1/D3 example turns out to need different width/length/
    # bracket positions, recalibrate these two independently rather than
    # assuming they'll always match CFSRC.
    "SRC-D1": {
        "name": "Custom SRC - D1 (pilot hole, no flange)",
        "curb_affects_height": False,
        "auto_note": "pilot_hole",  # see make_pilot_hole_note_item() / _sync_pilot_hole_note() in app.py
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
    "SRC-D3": {
        "name": "Custom SRC - D3 (flanged)",
        "curb_affects_height": False,
        "auto_note": "flange",  # see make_flange_note_item() / _sync_flange_note() in app.py
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

# SRC-D1/SRC-D3 (see PROFILES) need a two-segment prefix ("SRC-D1", not just
# "SRC") to tell the two drain-hole variants apart -- SKU_PREFIX_RE above
# only ever captures the plain letters before the first hyphen, which can't
# distinguish them. This list is a best-effort guess at the real SKU format
# (not yet confirmed against an actual SRC-D1/SRC-D3 production order --
# unlike every other calibrated coordinate in this file, this one hasn't
# been seen on a real example); if it turns out KBRS's SKUs don't actually
# look like "SRC-D1-1234", auto-detection just won't match here and falls
# through to manual-only mode same as any other unrecognized SKU -- the
# Product Type override dropdown always works as a fallback regardless.
EXTENDED_SKU_PREFIXES = ("SRC-D1", "SRC-D3")


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
    """34.25 -> '34.25', 35.5 -> '35.5', 36.0 -> '36', 40.1234 -> '40.1234'"""
    s = f"{val:.4f}".rstrip("0").rstrip(".")
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

    # ITEM line, dimensions appear as either (33 1/4"x34 1/2") or (47-1/2 x 33).
    # Case-insensitive: some production orders separate dimensions with a
    # capital "X" (e.g. '60 1/2" X 43 1/2"') instead of lowercase -- a plain
    # lowercase-only "x" here silently failed to parse those (real example:
    # 'CTB-2601-2900: ... 60 1/2" X 43 1/2"').
    item_match = re.search(
        r'([A-Z]+-[\w-]+):\s*(.+?)\s*\(([\d\s/-]+)"?\s*x\s*([\d\s/-]+)"?\)', text, re.IGNORECASE
    )
    if not item_match:
        # Some production orders print dimensions directly after the item
        # name with no parentheses at all, e.g. '...ShowerSlope  80 1/4" x
        # 60" 4701-5000 sq. inches.', and some real orders omit the inch
        # mark on the first number only, e.g. '85 5/8 x 41"'. The second
        # number's inch mark is required as the anchor -- without it, a
        # stray number embedded in the item name could get mistaken for the
        # real dimensions.
        item_match = re.search(
            r'([A-Z]+-[\w-]+):\s*(.+?)\s*([\d\s/-]+)"?\s*x\s*([\d\s/-]+)"', text, re.IGNORECASE
        )
    if not item_match:
        # Rarer real-world formats seen on actual production orders: neither
        # number has an inch mark at all ('60 x 53 HARD CURB'), or the "x"
        # separator itself got mangled into a stray '"' during PDF text
        # extraction ('60 1/2" " 45"'). Neither has a reliable inch-mark
        # anchor, so this tier anchors on the "sq. in./sq. inches." text
        # that KBRS's own production-order generator always prints directly
        # before the dimensions instead.
        item_match = re.search(
            r'([A-Z]+-[\w-]+):\s*(.+?sq\.\s*in\w*\.)\s*([\d\s/-]+)"?\s*(?:x|")\s*([\d\s/-]+)"?',
            text, re.IGNORECASE
        )
    if item_match:
        sku, item_name, raw_w, raw_h = item_match.groups()
        prefix_match = SKU_PREFIX_RE.match(sku)
        sku_prefix = prefix_match.group(1) if prefix_match else sku.split("-")[0]
        # SRC-D1/SRC-D3 need their second hyphen-segment too -- see
        # EXTENDED_SKU_PREFIXES's docstring above.
        segments = sku.split("-")
        if len(segments) >= 2:
            extended_prefix = f"{segments[0]}-{segments[1]}"
            if extended_prefix in EXTENDED_SKU_PREFIXES:
                sku_prefix = extended_prefix
        item_name = item_name.strip()
        raw_width_in = inches_to_decimal(raw_w)
        raw_height_in = inches_to_decimal(raw_h)
    else:
        # A genuinely new/unrecognized product line (e.g. "CUSTOM VANITY
        # VESSEL: Custom Vanity Vessel- 15" x 23" x 6-1/2"") doesn't follow
        # the "SKU-CODE: name (WxH)" format every other product's production
        # order uses -- no SKU code at all, and dimensions can be W x L x T
        # instead of just W x H. Rather than blocking the whole order over
        # it (po_number/so_number above already parsed fine), leave these
        # blank so the caller can still use the order for manual-only markup
        # (no calibrated profile, but the order form background loads and
        # notes/cut-line are still available -- see
        # InteractiveLayout.load_background_only() in app.py).
        sku = item_name = sku_prefix = None
        raw_width_in = raw_height_in = None

    return {
        "po_number": po_number,
        "order_date": order_date,
        "promised_date": promised_date,
        "so_number": so_number,
        "sku": sku,
        "sku_prefix": sku_prefix,
        "item_name": item_name,
        "raw_width_in": raw_width_in,
        "raw_height_in": raw_height_in,
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
    text = thickness if thickness.endswith('"') else thickness + '"'
    return {
        "key": "thickness", "kind": "text", "text": text,
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
    for where the cut goes -- drag it to the real position for that job.
    x0/y0/x1/y1 (rather than a single x + two y's) so the line can be
    rotated to run horizontally too, not just vertically; "orientation"
    tracks which axis the +CUT_FOR_SHIPPING_EXTRA_IN oversize bump applies
    to (see toggle_cut_line/_rotate_cut_line in app.py)."""
    line = {
        "key": "cut_line", "kind": "line", "orientation": "vertical",
        "x0": PAGE_W / 2, "y0": 240.0, "x1": PAGE_W / 2, "y1": 540.0,
        "color": "orange", "line_width": 10.0, "dashed": True, "deletable": True,
        "endpoint_handles": True,
    }
    label = {
        "key": "cut_label", "kind": "text", "text": "Cut for\nshipping",
        "x": PAGE_W / 2 - 90, "y": 390.0, "font_size": 20, "color": "orange",
        "fixed_cover": None, "moved": True, "deletable": True, "editable_text": True,
    }
    return [line, label]


_diagonal_counter = [0]


def make_diagonal_line_item() -> dict:
    """A manual, solid indicator line -- for flagging a diagonal cut or
    angled feature on the drawing that isn't itself a real dimension. Unlike
    the dashed cut-for-shipping line above, this is purely a visual marker:
    it never bumps the oversize width/height, isn't tied to any particular
    product line (linear or not), and multiple can exist (like notes) since
    each gets its own counter-based key. Starts at a plain 45-degree angle;
    draggable as a whole like any other item, and rotatable in 45-degree
    steps in the live editor (right-click -> Rotate 45°) via the same
    rotate_point() mechanism as the origin bracket's neo-angle step. Each
    endpoint also has its own drag handle (like the cut-for-shipping line),
    so its length/exact angle can be adjusted freely too, not just rotated
    in 45-degree steps."""
    _diagonal_counter[0] += 1
    cx, cy = PAGE_W / 2, PAGE_H / 2
    half = 100.0
    return {
        "key": f"diagonal_{_diagonal_counter[0]}", "kind": "line",
        "x0": cx - half, "y0": cy - half, "x1": cx + half, "y1": cy + half,
        "color": "orange", "line_width": 8.0, "dashed": False, "deletable": True,
        "endpoint_handles": True,
    }


_note_counter = [0]


def make_note_item(text: str = "New note", x: float = PAGE_W / 2 - 60, y: float = 400.0,
                    font_size: int = 20, color: str = "orange") -> dict:
    _note_counter[0] += 1
    return {
        "key": f"note_{_note_counter[0]}", "kind": "text", "text": text,
        "x": x, "y": y, "font_size": font_size, "color": color,
        "fixed_cover": None, "moved": True, "deletable": True, "editable_text": True,
    }


# Blue Traveler orders are standardly 1.5" thick with a flange edge on all
# sides -- both auto-fill when that material is selected/detected (see
# InteractiveLayout._sync_flange_note()/SingleOrderTab._maybe_autofill_
# blue_traveler_thickness() in app.py), same "auto-fill unless you've
# overridden it" contract as the CLSS/CLTB drain-A thickness formula and the
# calibrated thickness item -- editable/deletable like any other note.
BLUE_TRAVELER_THICKNESS_IN = "1.5"
FLANGE_NOTE_KEY = "flange_note"
FLANGE_NOTE_TEXT = "FLANGE ON ALL SIDES"


def is_blue_traveler(material: str) -> bool:
    return material.strip().upper() == "BLUE TRAVELER"


def make_flange_note_item() -> dict:
    return {
        "key": FLANGE_NOTE_KEY, "kind": "text", "text": FLANGE_NOTE_TEXT,
        "x": PAGE_W / 2 - 110, "y": 160.0, "font_size": 18, "color": "black",
        "fixed_cover": None, "moved": True, "deletable": True, "editable_text": True,
    }


# Keyhole Linear orders need a drain plate -- toggled by a checkbox (not
# material-driven, unlike the flange note above) rather than auto-detected,
# since it's a configuration choice, not implied by anything else on the
# order. "orange" here is the app's configurable accent-color key (see
# COLOR_MAP/set_accent_color), not literally orange, matching the request
# for it to show in "the highlighted accent color."
DRAIN_PLATE_NOTE_KEY = "drain_plate_note"
DRAIN_PLATE_NOTE_TEXT = "DRAIN PLATE NEEDED"


def make_drain_plate_note_item() -> dict:
    return {
        "key": DRAIN_PLATE_NOTE_KEY, "kind": "text", "text": DRAIN_PLATE_NOTE_TEXT,
        "x": PAGE_W / 2 - 130, "y": 120.0, "font_size": 20, "color": "orange",
        "fixed_cover": None, "moved": True, "deletable": True, "editable_text": True,
    }


# SRC comes in two drain-hole variants that otherwise share the same
# calibrated layout (see PROFILES["SRC-D1"]/["SRC-D3"] below): D3 is flanged
# (auto-adds the same FLANGE_NOTE_TEXT as Blue Traveler -- see
# InteractiveLayout._sync_flange_note() in app.py, which checks a profile's
# "auto_note" key too, not just material), D1 has a pilot hole and no flange
# instead. Driven purely by product type (profile["auto_note"]), unlike the
# material-or-checkbox-driven notes above.
PILOT_HOLE_NOTE_KEY = "pilot_hole_note"
PILOT_HOLE_NOTE_TEXT = '0.5" PILOT HOLE - NO FLANGE'


def make_pilot_hole_note_item() -> dict:
    return {
        "key": PILOT_HOLE_NOTE_KEY, "kind": "text", "text": PILOT_HOLE_NOTE_TEXT,
        "x": PAGE_W / 2 - 130, "y": 140.0, "font_size": 18, "color": "black",
        "fixed_cover": None, "moved": True, "deletable": True, "editable_text": True,
    }


def rotate_point(pt: tuple, pivot: tuple, degrees: float) -> tuple:
    """Rotate pt around pivot by any angle. Exact multiples of 90 take a
    fast path with plain dx/dy swaps (no float drift); anything else (e.g.
    the bracket's 45-degree steps, for neo-angle showers that don't land on
    a clean 90-degree corner) falls back to a normal sin/cos rotation."""
    dx, dy = pt[0] - pivot[0], pt[1] - pivot[1]
    degrees = degrees % 360
    if degrees == 90:
        dx, dy = -dy, dx
    elif degrees == 180:
        dx, dy = -dx, -dy
    elif degrees == 270:
        dx, dy = dy, -dx
    elif degrees != 0:
        rad = math.radians(degrees)
        cos_a, sin_a = math.cos(rad), math.sin(rad)
        dx, dy = dx * cos_a - dy * sin_a, dx * sin_a + dy * cos_a
    return (pivot[0] + dx, pivot[1] + dy)


def _rotate_page_point(x: float, y: float, page_rotation: int) -> tuple:
    """Where (x, y) on the unrotated PAGE_W x PAGE_H canonical page ends up
    after rotating the WHOLE PAGE (not the point around its own pivot) by
    page_rotation degrees (must be a multiple of 90), re-anchored so the
    result still starts at (0, 0) -- the same transform a PDF's own /Rotate
    represents, applied directly to overlay coordinates instead of as page
    metadata (get_transformed_order_form()'s docstring explains why that
    distinction matters for the background image; this is the overlay's
    equivalent, used to keep it from getting non-uniformly stretched by
    merge_pdf()'s canonical->real scaling when the background has been
    rotated)."""
    page_rotation = page_rotation % 360
    if page_rotation == 90:
        return PAGE_H - y, x
    if page_rotation == 180:
        return PAGE_W - x, PAGE_H - y
    if page_rotation == 270:
        return y, PAGE_W - x
    return x, y


def _rotate_bracket_for_page(profile: dict, wide_origin: bool, bracket: dict, page_rotation: int) -> dict:
    """A bracket's offset/rotation describe a delta from the profile's
    calibrated base shape, not an absolute position, so it can't just be
    point-rotated like a plain (x, y) item -- this re-derives an equivalent
    offset (matching the elbow's new, page-rotated position) and rotation
    (the existing manual rotation plus the page's own) that reproduce the
    bracket's correctly page-rotated shape when re-run through
    _bracket_points()."""
    base_pts = profile["bracket_wide"] if (wide_origin and "bracket_wide" in profile) else profile["bracket"]
    base_elbow = base_pts[1]
    current_elbow = _bracket_points(profile, wide_origin, bracket["offset"], bracket["rotation"])[1]
    target_elbow = _rotate_page_point(current_elbow[0], current_elbow[1], page_rotation)
    new_offset = (target_elbow[0] - base_elbow[0], target_elbow[1] - base_elbow[1])
    new_rotation = (bracket["rotation"] + page_rotation) % 360
    return {"offset": new_offset, "rotation": new_rotation}


def rotate_overlay_for_page(profile: dict, wide_origin: bool, items: list, brackets: list,
                             page_rotation: int) -> tuple:
    """Repositions overlay items and bracket(s) to match a background
    that's been rotated by page_rotation degrees (see
    InteractiveLayout._rotate_background() in app.py) -- without this,
    merge_pdf()'s canonical->real scaling has to non-uniformly squash the
    overlay to fit the rotated page's swapped aspect ratio, visibly stretching
    dimension text/lines instead of just repositioning them. Text itself is
    repositioned but not rotated (numbers stay upright and readable, same
    as normal drafting convention). A no-op if page_rotation is 0. Scoped
    to items + brackets -- the material bar isn't repositioned by this yet."""
    page_rotation = page_rotation % 360
    if page_rotation == 0:
        return items, brackets

    new_items = []
    for item in items:
        new_item = dict(item)
        if item["kind"] == "line":
            new_item["x0"], new_item["y0"] = _rotate_page_point(item["x0"], item["y0"], page_rotation)
            new_item["x1"], new_item["y1"] = _rotate_page_point(item["x1"], item["y1"], page_rotation)
        else:
            new_item["x"], new_item["y"] = _rotate_page_point(item["x"], item["y"], page_rotation)
            if item.get("fixed_cover"):
                fx0, fy0, fx1, fy1 = item["fixed_cover"]
                p0 = _rotate_page_point(fx0, fy0, page_rotation)
                p1 = _rotate_page_point(fx1, fy1, page_rotation)
                new_item["fixed_cover"] = (
                    min(p0[0], p1[0]), min(p0[1], p1[1]),
                    max(p0[0], p1[0]), max(p0[1], p1[1]),
                )
        new_items.append(new_item)

    new_brackets = [_rotate_bracket_for_page(profile, wide_origin, b, page_rotation) for b in brackets]
    return new_items, new_brackets


# Fallback material-bar position/size for a product with no calibrated
# PROFILES entry (e.g. Custom Vanity Vessel) -- reuses CLSS's real calibrated
# spot as a reasonable bottom-left default, since the Traveler name is purely
# informational (not a CNC-critical measurement like the dimension callouts
# or origin bracket, which are never drawn without real calibration -- see
# render_page()). Fully draggable in the live editor like any calibrated
# bar, so a wrong guess here just needs a drag to fix, not a wrong cut.
DEFAULT_MATERIAL_BAR = (25.9, 43.85, 220.4, 73.85)
DEFAULT_MATERIAL_TEXT_X = 38.9
DEFAULT_FONT_SIZE_MATERIAL = 24


def _material_bar_rect(profile: dict, material: str, bar_offset: tuple) -> tuple:
    bx0, by0, bx1, by1 = profile["material_bar"] if profile else DEFAULT_MATERIAL_BAR
    bdx, bdy = bar_offset
    bx0, by0, bx1, by1 = bx0 + bdx, by0 + bdy, bx1 + bdx, by1 + bdy
    fsize_material = profile["font_size_material"] if profile else DEFAULT_FONT_SIZE_MATERIAL
    text_w = stringWidth(material.upper(), "Helvetica-Bold", fsize_material)
    bar_w = max(bx1 - bx0, text_w + 10 * 2)
    return bx0, by0, bx0 + bar_w, by1


def _bracket_points(profile: dict, wide_origin: bool, bracket_offset: tuple, bracket_rotation: int) -> list:
    pts = profile["bracket_wide"] if (wide_origin and "bracket_wide" in profile) else profile["bracket"]
    dx, dy = bracket_offset
    pts = [(px + dx, py + dy) for px, py in pts]
    if bracket_rotation:
        pivot = pts[1]  # the elbow -- the actual corner vertex the bracket marks
        pts = [rotate_point(pt, pivot, bracket_rotation) for pt in pts]
    return pts


_DEFAULT_BRACKETS = [{"offset": (0.0, 0.0), "rotation": 0}]


def _content_bbox(profile: dict, material: str, items: list, wide_origin: bool,
                   brackets: list, bar_offset: tuple, page_rotation: int = 0) -> tuple:
    """Bounding box (min_x, min_y, max_x, max_y) of everything render_page()
    is about to draw, unioned with the normal (0,0)-(PAGE_W,PAGE_H) page so
    a bracket/bar/item dragged outside the normal page (e.g. after rotating
    the background drawing) never gets silently clipped on export -- the
    whole overlay gets sized to include it instead, however far out it is.
    When page_rotation is 90/270, the floor swaps to (PAGE_H, PAGE_W) to
    match rotate_overlay_for_page()'s already-repositioned (landscape, if
    the canonical page is portrait) content -- without this, the floor
    would force the overlay back into its original (now wrong) shape and
    undo that fix."""
    floor_w, floor_h = (PAGE_H, PAGE_W) if page_rotation % 180 == 90 else (PAGE_W, PAGE_H)
    min_x, min_y, max_x, max_y = 0.0, 0.0, floor_w, floor_h

    def extend(x, y):
        nonlocal min_x, min_y, max_x, max_y
        min_x, min_y = min(min_x, x), min(min_y, y)
        max_x, max_y = max(max_x, x), max(max_y, y)

    # The material bar always contributes (falls back to a reasonable
    # default position/size without a profile -- see _material_bar_rect()).
    # The origin bracket is different: it's a safety-critical CNC reference
    # point with nothing sane to default to, so it's skipped entirely
    # without a profile (see render_page()'s docstring) -- only the manual
    # items (notes, cut/diagonal lines) and the bar contribute in that case.
    bx0, by0, bx1, by1 = _material_bar_rect(profile, material, bar_offset)
    extend(bx0, by0)
    extend(bx1, by1)

    if profile is not None:
        for bracket in brackets:
            for px, py in _bracket_points(profile, wide_origin, bracket["offset"], bracket["rotation"]):
                extend(px, py)

    for item in items:
        if item["kind"] == "line":
            extend(item["x0"], item["y0"])
            extend(item["x1"], item["y1"])
        else:
            lines = item["text"].split("\n")
            fsize = item["font_size"]
            w = max((stringWidth(ln, "Helvetica-Bold", fsize) for ln in lines), default=0)
            h = fsize * 1.15 * len(lines)
            extend(item["x"], item["y"])
            extend(item["x"] + w, item["y"] + h)

    return min_x, min_y, max_x, max_y


def render_page(profile: dict, material: str, items: list, wide_origin: bool = False,
                 brackets: list = None, bar_offset: tuple = (0.0, 0.0), page_rotation: int = 0) -> tuple:
    """Returns (pdf_bytes, min_x, min_y). min_x/min_y are the canonical
    (0,0)-(PAGE_W,PAGE_H)-space coordinates that ended up at this page's own
    local (0, 0) -- i.e. how far auto-grow (below) shifted everything by.
    merge_pdf() needs these to correctly place the overlay on the real page
    (see its docstring for why) -- pass them straight through, don't just
    take the bytes."""
    # brackets is a list of {"offset": (dx,dy), "rotation": 0/90/180/270} --
    # some orders need more than one CNC/CAD reference point. Defaults to a
    # single un-adjusted bracket at the calibrated position.
    if brackets is None:
        brackets = _DEFAULT_BRACKETS

    # page_rotation only affects the auto-grow floor's shape (see
    # _content_bbox) -- callers rotating the background are expected to
    # have already run items/brackets through rotate_overlay_for_page()
    # themselves; this just keeps the floor from forcing the result back
    # into the wrong (unrotated) shape.
    #
    # Everything is normally within the calibrated (0,0)-(PAGE_W,PAGE_H) box,
    # but a manually dragged bracket/bar/item can end up outside it -- size
    # the overlay's own page to whatever actually needs to fit (never
    # smaller than the normal page) and shift every draw call by the box's
    # origin, so nothing is ever silently cut off. merge_pdf() then places
    # this correctly-sized overlay onto the real target page using min_x/
    # min_y (returned below) plus the fixed canonical->real scale ratio --
    # NOT a scale derived from this page's own (possibly grown) size, which
    # would silently shrink/shift everything else on the page too (the bug
    # this whole tuple return exists to fix).
    min_x, min_y, max_x, max_y = _content_bbox(profile, material, items, wide_origin, brackets, bar_offset,
                                                page_rotation)
    off_x, off_y = -min_x, -min_y
    page_w, page_h = max_x - min_x, max_y - min_y

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(page_w, page_h))

    # material bar, color derived from the material name -- always automatic,
    # even for a product with no calibrated layout yet (falls back to
    # DEFAULT_MATERIAL_BAR/DEFAULT_MATERIAL_TEXT_X/DEFAULT_FONT_SIZE_MATERIAL
    # -- see _material_bar_rect()). Unlike the dimension callouts and origin
    # bracket below, the Traveler name isn't a CNC-critical measurement, so a
    # reasonable default here (fully draggable, same as a calibrated one) is
    # worth having rather than forcing a manual note for every uncalibrated
    # product. Width is sized to fit whatever material text is actually
    # entered (with padding), not just one calibrated example -- a longer
    # name (e.g. "GRAY TRAVELER") would otherwise overflow past a fixed-width
    # bar as invisible white-on-white text past its right edge.
    bar_color = resolve_bar_color(material)
    text_color = resolve_text_color(bar_color)
    bx0, by0, bx1, by1 = _material_bar_rect(profile, material, bar_offset)
    bx0, by0, bx1, by1 = bx0 + off_x, by0 + off_y, bx1 + off_x, by1 + off_y
    fsize_material = profile["font_size_material"] if profile else DEFAULT_FONT_SIZE_MATERIAL
    label_text = material.upper()
    c.setFillColor(bar_color)
    c.rect(bx0, by0, bx1 - bx0, by1 - by0, stroke=0, fill=1)  # square corners, no pill/stadium shape
    c.setFillColor(text_color)
    c.setFont("Helvetica-Bold", fsize_material)
    mx = profile["material_text_pos"][0] if profile else DEFAULT_MATERIAL_TEXT_X
    bdx, _bdy = bar_offset
    mx += bdx + off_x
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
            c.line(item["x0"] + off_x, item["y0"] + off_y, item["x1"] + off_x, item["y1"] + off_y)
            c.setDash([])
        elif item["kind"] == "text":
            ix, iy = item["x"] + off_x, item["y"] + off_y
            lines = item["text"].split("\n")
            fsize = item["font_size"]
            color = COLOR_MAP.get(item["color"], ORANGE)
            # 1) blank out the calibrated original-value area (e.g. hides the
            #    customer's handwritten raw measurement) when present.
            if not item.get("moved") and item.get("fixed_cover"):
                x0, y0, x1, y1 = item["fixed_cover"]
                c.setFillColor(WHITE)
                c.rect(x0 + off_x, y0 + off_y, x1 - x0, y1 - y0, stroke=0, fill=1)
            # 2) always also paint a padded white box snug around the new
            #    text itself, so numbers/thickness stay clearly readable on
            #    top of the drawing even if the scan doesn't line up exactly
            #    with the calibrated cover box above.
            if item.get("cover", True):
                w = max(stringWidth(ln, "Helvetica-Bold", fsize) for ln in lines) if lines else 0
                h = fsize * 1.15 * len(lines)
                pad = 6
                c.setFillColor(WHITE)
                c.rect(ix - pad, iy - pad, w + pad * 2, h + pad * 2, stroke=0, fill=1)
            c.setFillColor(color)
            c.setFont("Helvetica-Bold", fsize)
            for i, ln in enumerate(lines):
                c.drawString(ix, iy - i * fsize * 1.15, ln)

    # origin bracket(s) (CNC/CAD reference corner) -- automatic by default,
    # but draggable, rotatable, and duplicable in the app's live editor when
    # a calibrated position turns out to be wrong or an order needs more
    # than one reference point; each bracket's offset is (0, 0) and rotation
    # is 0 unless the user has manually adjusted it there. Skipped entirely
    # without a profile -- there's no calibrated corner to mark yet, and
    # this is a safety-critical CNC reference point, not something to guess.
    if profile is not None:
        for bracket in brackets:
            pts = _bracket_points(profile, wide_origin, bracket["offset"], bracket["rotation"])
            c.setStrokeColor(ORANGE)
            c.setLineWidth(profile["bracket_width"])
            p = c.beginPath()
            p.moveTo(pts[0][0] + off_x, pts[0][1] + off_y)
            for pt in pts[1:]:
                p.lineTo(pt[0] + off_x, pt[1] + off_y)
            c.drawPath(p, stroke=1, fill=0)

    c.save()
    buf.seek(0)
    return buf.read(), min_x, min_y


def build_overlay(profile: dict, oversize_w: float, oversize_h: float, material: str,
                   thickness: str = "", wide_origin: bool = False) -> tuple:
    """Back-compat wrapper: renders the default (non-edited) item layout.
    Returns (pdf_bytes, min_x, min_y) -- see render_page()."""
    items = compute_default_items(profile, oversize_w, oversize_h, thickness=thickness)
    return render_page(profile, material, items, wide_origin=wide_origin)


def merge_pdf(order_form_pdf: str, production_order_pdf: str, overlay_bytes: bytes,
              out_path: str, rotate_deg: int = 90, min_x: float = 0.0, min_y: float = 0.0):
    """min_x/min_y: the canonical-space origin render_page() returned
    alongside overlay_bytes (0, 0 unless the overlay auto-grew past the
    normal page bounds -- see render_page()'s docstring). Required to place
    the overlay correctly; a caller passing pre-rendered bytes without them
    will misplace anything on a page that auto-grew.

    order_form_pdf must already be fully transformed (normalize_to_portrait_
    page()/get_transformed_order_form(), with any manual rotation/scale the
    caller wants already applied) -- NOT re-normalized here. Re-running
    normalization on an already-rotated page isn't a no-op: a manually-
    rotated (now landscape-shaped) page would get letterbox-fit into
    portrait *again*, silently re-shrinking/repositioning it in a way the
    overlay's already-computed positions (rotate_overlay_for_page()) never
    accounted for -- exactly what caused a real reported bug (bracket
    missing, measurements shifted, after using the manual rotate control)."""
    order_form_pdf = ensure_pdf(order_form_pdf)  # converts image scans (jpg/png/etc.) to PDF; no-op if already a PDF
    overlay_reader = PdfReader(io.BytesIO(overlay_bytes))
    order_reader = PdfReader(order_form_pdf)
    prod_reader = PdfReader(production_order_pdf)

    writer = PdfWriter()
    page0 = order_reader.pages[0]
    overlay_page = overlay_reader.pages[0]
    real_w, real_h = _effective_page_size(page0)
    # Always scale by the FIXED canonical (PAGE_W, PAGE_H) -> real-page
    # ratio -- the same ratio the live editor's drag math always assumes
    # (see InteractiveLayout._pdf_to_canvas/_canvas_to_pdf_delta in app.py)
    # -- never by a ratio derived from the overlay's own current page size.
    # That distinction matters whenever the overlay auto-grew past the
    # normal bounds (render_page()'s "never clip" behavior, e.g. from a
    # bunch of dragged notes): scale_to(real_w, real_h) would derive its
    # ratio from the GROWN size instead of PAGE_W x PAGE_H, silently
    # shrinking/shifting every item on the page relative to where the live
    # preview showed it -- not just the one that triggered the growth.
    # min_x/min_y (also from render_page(), 0 unless auto-grow shifted
    # things) correct for that shift with a translate, composed after the
    # same fixed scale.
    sx, sy = real_w / PAGE_W, real_h / PAGE_H
    transform = Transformation().scale(sx, sy).translate(min_x * sx, min_y * sy)
    overlay_page.add_transformation(transform, expand=True)
    page0.merge_page(overlay_page)
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

    overlay_bytes, min_x, min_y = build_overlay(profile, oversize_w, oversize_h, material,
                                                 thickness=thickness, wide_origin=wide_origin)
    # merge_pdf() expects an already-fully-transformed page (see its
    # docstring) -- the CLI has no live editor/manual rotation to apply, so
    # this is just the plain portrait-normalized baseline.
    normalized_order_form = get_transformed_order_form(order_form_pdf)
    merge_pdf(normalized_order_form, production_order_pdf, overlay_bytes, out_path, rotate_deg=rotate_deg,
              min_x=min_x, min_y=min_y)

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
