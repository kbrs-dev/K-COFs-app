#!/usr/bin/env python3
"""
KBRS Production Markup — desktop app.

A simple window on top of kbrs_markup.py. No paid dependencies: Python,
tkinter (ships with Python), reportlab, and pypdf are all free/open-source
and run entirely on this computer.

Run it:
    python3 app.py
or double-click "KBRS Markup.command" in the same folder.
"""

import copy
import csv
import io
import os
import re
import subprocess
import sys
import threading
import traceback
from pathlib import Path

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog, font as tkfont

import kbrs_markup as engine
from pypdf import PdfReader, PdfWriter

try:
    from tkinterdnd2 import TkinterDnD, DND_FILES
    DND_AVAILABLE = True
except ImportError:
    DND_AVAILABLE = False

try:
    import pypdfium2 as pdfium
    from PIL import ImageTk
    EDITOR_AVAILABLE = True
except ImportError:
    EDITOR_AVAILABLE = False

CANVAS_SCALE = 0.75  # PDF points -> editor canvas pixels
ITEM_COLOR_HEX = {"orange": "#f2842f", "white": "#ffffff", "black": "#000000"}


def parse_dnd_paths(data: str):
    """tkinterdnd2 gives dropped paths space-separated, brace-wrapped if they
    contain spaces, e.g. '{/a/file one.pdf} /a/file2.pdf'."""
    paths, buf, in_brace = [], "", False
    for ch in data:
        if ch == "{":
            in_brace = True
            buf = ""
        elif ch == "}":
            in_brace = False
            paths.append(buf)
            buf = ""
        elif ch == " " and not in_brace:
            if buf:
                paths.append(buf)
                buf = ""
        else:
            buf += ch
    if buf:
        paths.append(buf)
    return paths


def make_drop_target(widget, on_drop):
    """Register widget as a DND drop target if tkinterdnd2 is available.
    on_drop receives the first dropped path."""
    if not DND_AVAILABLE:
        return
    widget.drop_target_register(DND_FILES)
    widget.dnd_bind("<<Drop>>", lambda e: on_drop(parse_dnd_paths(e.data)[0]))


def open_in_finder(path: str):
    try:
        if sys.platform == "darwin":
            subprocess.run(["open", "-R", path])
        elif sys.platform == "win32":
            subprocess.run(["explorer", "/select,", path])
        else:
            subprocess.run(["xdg-open", str(Path(path).parent)])
    except Exception:
        pass


def same_file(a: str, b: str) -> bool:
    """True if both paths point at the same file on disk."""
    if not a or not b:
        return False
    try:
        return os.path.abspath(a) == os.path.abspath(b)
    except Exception:
        return a == b


def validate_production_order_path(path: str):
    """Returns None if the path looks like a usable production-order PDF,
    else a short, friendly error message. The production order always comes
    from KBRS's own system as a real PDF -- no image support needed here."""
    if not path:
        return "No file chosen."
    if not os.path.isfile(path):
        return f"File not found:\n{path}"
    ext = Path(path).suffix.lower()
    if ext != ".pdf":
        return (f"That's a {ext or '(no extension)'} file, not a PDF:\n{os.path.basename(path)}\n\n"
                f"The KBRS production order is always a PDF -- choose that file instead.")
    try:
        PdfReader(path)
    except Exception as e:
        return (f"That PDF couldn't be read ({type(e).__name__}: {e}).\n\n"
                f"It may be corrupted, password-protected, or not actually a PDF "
                f"despite the .pdf extension.")
    return None


def validate_order_form_path(path: str):
    """Returns None if the path looks like a usable order form, else a
    short, friendly error message. Unlike the production order, this one
    accepts PDFs *or* image scans (jpg/png/etc.) -- customer order forms
    often come back as a photo/scan rather than a PDF."""
    if not path:
        return "No file chosen."
    if not os.path.isfile(path):
        return f"File not found:\n{path}"
    ext = Path(path).suffix.lower()
    if ext == ".heic":
        return ("HEIC photos aren't supported -- please export/save it as a JPG or PNG "
                "first (on iPhone: Share > Save as JPG works, or a screenshot).")
    if ext not in ({".pdf"} | engine.IMAGE_EXTS):
        return (f"That's a {ext or '(no extension)'} file:\n{os.path.basename(path)}\n\n"
                f"Choose a PDF or an image scan (JPG/PNG/TIFF/BMP) of the order form instead.")
    try:
        engine.ensure_pdf(path)
    except Exception as e:
        return (f"That file couldn't be read ({type(e).__name__}: {e}).\n\n"
                f"It may be corrupted or not actually a valid {ext} file.")
    return None


class DropZone(tk.Frame):
    """A big click-or-drag target for picking a PDF. Much easier to hit than
    a one-line text field. Shows the chosen filename (and full path in a
    small line underneath) once set; click anywhere in the box to browse,
    or drag a file straight onto it."""

    def __init__(self, master, textvariable, browse_command, validator=validate_order_form_path,
                 placeholder="Drop PDF here, or click to browse", **kwargs):
        super().__init__(master, bg="#f4f4f4", highlightbackground="#aaaaaa",
                          highlightcolor="#aaaaaa", highlightthickness=2, bd=0,
                          cursor="hand2", **kwargs)
        self.var = textvariable
        self.placeholder = placeholder
        self.browse_command = browse_command
        self.validator = validator

        self.name_label = tk.Label(self, bg="#f4f4f4", fg="#777", font=("", 12),
                                    wraplength=460, justify="center")
        self.name_label.pack(expand=True, fill="both", padx=10, pady=(14, 2))
        self.path_label = tk.Label(self, bg="#f4f4f4", fg="#999", font=("", 9),
                                    wraplength=460, justify="center")
        self.path_label.pack(fill="x", padx=10, pady=(0, 10))

        self._refresh()
        self.var.trace_add("write", lambda *_: self._refresh())
        for widget in (self, self.name_label, self.path_label):
            widget.bind("<Button-1>", lambda e: self.browse_command())
        make_drop_target(self, self._on_drop)
        make_drop_target(self.name_label, self._on_drop)
        make_drop_target(self.path_label, self._on_drop)

    def _on_drop(self, path):
        error = self.validator(path)
        if error:
            messagebox.showerror("Not a usable file", error)
            return
        self.var.set(path)

    def _refresh(self):
        val = self.var.get()
        if val:
            self.name_label.config(text=os.path.basename(val), fg="#0a7d2c")
            self.path_label.config(text=val)
            self.config(highlightbackground="#0a7d2c")
        else:
            self.name_label.config(text=self.placeholder, fg="#777")
            self.path_label.config(text="")
            self.config(highlightbackground="#aaaaaa")


def _color_to_hex(color):
    """reportlab Color -> '#rrggbb', for drawing the same colors on a
    Tkinter canvas."""
    r = max(0, min(255, int(round(color.red * 255))))
    g = max(0, min(255, int(round(color.green * 255))))
    b = max(0, min(255, int(round(color.blue * 255))))
    return f"#{r:02x}{g:02x}{b:02x}"


class InteractiveLayout(ttk.Frame):
    """The live preview *is* the editor: shows the order-form background
    with the material bar, origin bracket (both automatic, not draggable),
    and every dimension/thickness/note/cut-line item (draggable) right in
    the main window -- no separate popup. Updates live as the form fields
    change; drag/edit/delete/undo freely, nothing is final until Generate."""

    def __init__(self, master):
        super().__init__(master)
        self.loaded = False
        self.order_form_path = None
        self.production_order_path = None
        self.profile = None
        self.material = ""
        self.oversize_w = None
        self.oversize_h = None
        self.wide_origin = False
        self.has_cut_line = False
        self.items = []
        self.canvas_ids = {}
        self.static_ids = {}
        self.undo_stack = []
        self.redo_stack = []
        self.drag_key = None
        self.bg_photo = None
        self.bracket_offset = (0.0, 0.0)  # manual nudge, PDF points; (0,0) = calibrated default
        self.bracket_rotation = 0  # manual rotation in degrees (0/90/180/270); 0 = calibrated default
        self._bracket_dragging = False

        self.placeholder = ttk.Label(self, text="Load an order form to see it here", foreground="#777",
                                      background="#eeeeee", relief="sunken", wraplength=340, justify="center")
        self.placeholder.pack(fill="both", expand=True)

        self.toolbar = ttk.Frame(self)
        self.cut_btn = ttk.Button(self.toolbar, text="Add cut-for-shipping line", command=self.toggle_cut_line)
        self.cut_btn.pack(side="left", padx=(0, 4))
        ttk.Button(self.toolbar, text="Add note", command=self.add_note).pack(side="left", padx=4)
        self.undo_btn = ttk.Button(self.toolbar, text="Undo", command=self.undo)
        self.undo_btn.pack(side="left", padx=(12, 4))
        self.redo_btn = ttk.Button(self.toolbar, text="Redo", command=self.redo)
        self.redo_btn.pack(side="left", padx=4)

        self.hint = ttk.Label(self, text="Drag items to move · right-click to edit/delete · ⌘Z undo, ⇧⌘Z redo",
                               foreground="#666", font=("", 9))

        self.canvas_frame = ttk.Frame(self)
        vbar = ttk.Scrollbar(self.canvas_frame, orient="vertical")
        hbar = ttk.Scrollbar(self.canvas_frame, orient="horizontal")
        self.canvas = tk.Canvas(self.canvas_frame, bg="white", takefocus=1,
                                 yscrollcommand=vbar.set, xscrollcommand=hbar.set)
        vbar.config(command=self.canvas.yview)
        hbar.config(command=self.canvas.xview)
        vbar.pack(side="right", fill="y")
        hbar.pack(side="bottom", fill="x")
        self.canvas.pack(side="left", fill="both", expand=True)

        # keyboard shortcuts scoped to the canvas only, so they don't hijack
        # normal text-field undo elsewhere in the window
        for seq in ("<Command-z>", "<Control-z>"):
            self.canvas.bind(seq, lambda e: self.undo())
        for seq in ("<Command-Shift-Z>", "<Control-Shift-Z>", "<Control-y>"):
            self.canvas.bind(seq, lambda e: self.redo())

        # mouse wheel / trackpad scrolling (the vbar/hbar scrollbars alone
        # need a precise drag on a thin thumb -- most people expect the
        # wheel/trackpad to just work)
        def _wheel_delta(event):
            delta = event.delta
            if abs(delta) >= 120:  # Windows sends multiples of 120; macOS sends small ints
                delta //= 120
            return int(-delta)
        self.canvas.bind("<MouseWheel>", lambda e: self.canvas.yview_scroll(_wheel_delta(e), "units"))
        self.canvas.bind("<Shift-MouseWheel>", lambda e: self.canvas.xview_scroll(_wheel_delta(e), "units"))
        # Linux/X11 wheel events
        self.canvas.bind("<Button-4>", lambda e: self.canvas.yview_scroll(-1, "units"))
        self.canvas.bind("<Button-5>", lambda e: self.canvas.yview_scroll(1, "units"))

    # -- state / visibility --------------------------------------------------
    def show_placeholder(self, text):
        self.loaded = False
        self.toolbar.pack_forget()
        self.hint.pack_forget()
        self.canvas_frame.pack_forget()
        self.placeholder.config(text=text)
        self.placeholder.pack(fill="both", expand=True)

    def _show_canvas_ui(self):
        self.placeholder.pack_forget()
        self.toolbar.pack(fill="x", pady=(0, 4))
        self.hint.pack(fill="x", pady=(0, 4))
        self.canvas_frame.pack(fill="both", expand=True)

    def matches(self, order_form_path, production_order_path):
        return (self.loaded and self.order_form_path == order_form_path
                and self.production_order_path == production_order_path)

    def get_items(self):
        return self.items

    def get_bracket_offset(self):
        return self.bracket_offset

    def get_bracket_rotation(self):
        return self.bracket_rotation

    # -- coordinate conversion ------------------------------------------------
    def _pdf_to_canvas(self, x, y):
        return x * CANVAS_SCALE, (engine.PAGE_H - y) * CANVAS_SCALE

    def _canvas_to_pdf_delta(self, dcx, dcy):
        return dcx / CANVAS_SCALE, -dcy / CANVAS_SCALE

    # -- loading ---------------------------------------------------------------
    def load_background_only(self, order_form_path):
        """Order form picked, but no valid profile yet (production order not
        read/recognized) -- show just the background, no items."""
        try:
            order_form_pdf_path = engine.ensure_pdf(order_form_path)
            pdf = pdfium.PdfDocument(order_form_pdf_path)
            page = pdf[0]
            bitmap = page.render(scale=CANVAS_SCALE)
            pil_img = bitmap.to_pil()
            pdf.close()
        except Exception as e:
            traceback.print_exc()
            self.show_placeholder(f"Couldn't render a preview of this file ({type(e).__name__}: {e})")
            return False

        self.loaded = False  # background-only isn't a "loaded order" for matches()/get_items() purposes
        self.order_form_path = order_form_path
        self.production_order_path = None
        self.profile = None
        self.items = []
        self.bg_photo = ImageTk.PhotoImage(pil_img)
        img_w, img_h = pil_img.width, pil_img.height
        self._show_canvas_ui()
        self.canvas.delete("all")
        self.canvas.config(width=min(img_w, 420), height=min(img_h, 640), scrollregion=(0, 0, img_w, img_h))
        self.canvas.create_image(0, 0, anchor="nw", image=self.bg_photo)
        self.canvas_ids = {}
        self.static_ids = {}
        return True

    def load_new_order(self, order_form_path, production_order_path, profile, material,
                        oversize_w, oversize_h, thickness, wide_origin):
        """A genuinely different order (or first load) -- resets items,
        undo history, and the cut-line state."""
        try:
            order_form_pdf_path = engine.ensure_pdf(order_form_path)
            pdf = pdfium.PdfDocument(order_form_pdf_path)
            page = pdf[0]
            bitmap = page.render(scale=CANVAS_SCALE)
            pil_img = bitmap.to_pil()
            pdf.close()
        except Exception as e:
            traceback.print_exc()
            self.show_placeholder(f"Couldn't render a preview of this file ({type(e).__name__}: {e})")
            return False

        self.order_form_path = order_form_path
        self.production_order_path = production_order_path
        self.profile = profile
        self.material = material
        self.oversize_w = oversize_w
        self.oversize_h = oversize_h
        self.wide_origin = wide_origin
        self.has_cut_line = False
        self.bracket_offset = (0.0, 0.0)
        self.bracket_rotation = 0
        self.undo_stack = []
        self.redo_stack = []
        self.items = engine.compute_default_items(profile, oversize_w, oversize_h, thickness=thickness)

        self.bg_photo = ImageTk.PhotoImage(pil_img)
        img_w, img_h = pil_img.width, pil_img.height
        self._show_canvas_ui()
        self.canvas.delete("all")
        self.canvas.config(width=min(img_w, 420), height=min(img_h, 640), scrollregion=(0, 0, img_w, img_h))
        self.canvas.create_image(0, 0, anchor="nw", image=self.bg_photo)
        self.canvas_ids = {}
        self.static_ids = {}
        for item in self.items:
            self._draw_item(item)
        self._draw_static_bar_and_bracket()
        self.cut_btn.config(text="Add cut-for-shipping line")
        self._update_undo_redo_buttons()
        self.loaded = True
        return True

    def sync(self, material, oversize_w, oversize_h, thickness, wide_origin):
        """Same order, just a material/thickness/curb-depth field changed --
        update text and the material bar/bracket without touching anything
        the user has manually dragged, edited, or undo history."""
        if not self.loaded:
            return
        self.material = material
        self.wide_origin = wide_origin
        self.oversize_w = oversize_w + (engine.CUT_FOR_SHIPPING_EXTRA_IN if self.has_cut_line else 0)
        self.oversize_h = oversize_h
        self._refresh_width_text()

        height_item = next((i for i in self.items if i["key"] == "height"), None)
        if height_item:
            height_item["text"] = engine.fmt_inches(self.oversize_h)
            if "height" in self.canvas_ids:
                self.canvas.itemconfigure(self.canvas_ids["height"], text=height_item["text"])

        thickness_item = next((i for i in self.items if i["key"] == "thickness"), None)
        if thickness and "thickness_text_pos" in self.profile:
            if thickness_item:
                thickness_item["text"] = thickness
                if "thickness" in self.canvas_ids:
                    self.canvas.itemconfigure(self.canvas_ids["thickness"], text=thickness)
            else:
                new_item = engine.make_thickness_item(self.profile, thickness)
                self.items.append(new_item)
                self._draw_item(new_item)
        elif thickness_item:
            if "thickness" in self.canvas_ids:
                self.canvas.delete(self.canvas_ids["thickness"])
                del self.canvas_ids["thickness"]
            self.items.remove(thickness_item)

        self._draw_static_bar_and_bracket()

    # -- static (non-draggable) material bar + origin bracket -----------------
    def _draw_static_bar_and_bracket(self):
        for cid in self.static_ids.values():
            self.canvas.delete(cid)
        self.static_ids = {}
        if not self.profile:
            return
        profile = self.profile
        bar_color = engine.resolve_bar_color(self.material)
        text_color = engine.resolve_text_color(bar_color)
        bx0, by0, bx1, by1 = profile["material_bar"]
        fsize_material = profile["font_size_material"]
        fsize_px = max(8, int(fsize_material * CANVAS_SCALE))
        label_text = (self.material or "").upper()
        # Size the bar to fit the actual text (measured with the real font
        # Tkinter will draw it in) -- a fixed calibrated width would clip
        # longer material names as invisible white-on-white text past its
        # right edge.
        tk_font = tkfont.Font(family="Helvetica", size=fsize_px, weight="bold")
        text_w_px = tk_font.measure(label_text)
        pad_px = 14
        cx0, cy0 = self._pdf_to_canvas(bx0, by1)
        cx1_default, cy1 = self._pdf_to_canvas(bx1, by0)
        bar_w_px = max(cx1_default - cx0, text_w_px + pad_px * 2)
        cx1 = cx0 + bar_w_px
        self.static_ids["bar"] = self.canvas.create_rectangle(
            cx0, cy0, cx1, cy1, fill=_color_to_hex(bar_color), outline=""
        )
        mx, _my = profile["material_text_pos"]
        baseline_y_pdf = (by0 + by1) / 2 - fsize_material * 0.35
        tcx, tcy = self._pdf_to_canvas(mx, baseline_y_pdf)
        self.static_ids["bar_text"] = self.canvas.create_text(
            tcx, tcy, text=label_text, fill=_color_to_hex(text_color),
            font=("Helvetica", fsize_px, "bold"), anchor="sw", justify="left",
        )
        pts = profile["bracket_wide"] if (self.wide_origin and "bracket_wide" in profile) else profile["bracket"]
        dx_off, dy_off = self.bracket_offset
        pdf_pts = [(px + dx_off, py + dy_off) for px, py in pts]
        if self.bracket_rotation:
            pivot = pdf_pts[1]  # the elbow -- the actual corner vertex the bracket marks
            pdf_pts = [engine.rotate_point(pt, pivot, self.bracket_rotation) for pt in pdf_pts]
        flat_pts = []
        for px, py in pdf_pts:
            cx, cy = self._pdf_to_canvas(px, py)
            flat_pts.extend([cx, cy])
        manually_adjusted = self.bracket_offset != (0.0, 0.0) or self.bracket_rotation != 0
        bracket_color = "#d81b60" if manually_adjusted else "#f2842f"  # flag a manual nudge/rotation
        cid = self.canvas.create_line(
            *flat_pts, fill=bracket_color, width=max(2, int(profile["bracket_width"] * CANVAS_SCALE))
        )
        self.static_ids["bracket"] = cid
        # the origin bracket IS draggable -- calibration can be wrong for a
        # given order/product, and there's no other way to correct it
        self.canvas.tag_bind(cid, "<ButtonPress-1>", self._bracket_press)
        self.canvas.tag_bind(cid, "<B1-Motion>", self._bracket_motion)
        self.canvas.tag_bind(cid, "<ButtonRelease-1>", self._bracket_release)
        self.canvas.tag_bind(cid, "<Button-2>", self._bracket_context_menu)
        self.canvas.tag_bind(cid, "<Button-3>", self._bracket_context_menu)
        for other_cid in self.canvas_ids.values():
            self.canvas.tag_raise(other_cid)  # keep draggable items above the bar/bracket

    # -- drawing draggable items -----------------------------------------------
    def _draw_item(self, item):
        key = item["key"]
        if item["kind"] == "line":
            x1, y1 = self._pdf_to_canvas(item["x"], item["y0"])
            x2, y2 = self._pdf_to_canvas(item["x"], item["y1"])
            cid = self.canvas.create_line(
                x1, y1, x2, y2, fill=ITEM_COLOR_HEX.get(item["color"], "#f2842f"),
                width=4, dash=(6, 4) if item.get("dashed") else None,
            )
        else:
            cx, cy = self._pdf_to_canvas(item["x"], item["y"])
            fsize_px = max(8, int(item["font_size"] * CANVAS_SCALE))
            cid = self.canvas.create_text(
                cx, cy, text=item["text"],
                fill=ITEM_COLOR_HEX.get(item["color"], "#f2842f"),
                font=("Helvetica", fsize_px, "bold"), anchor="sw", justify="left",
            )
        self.canvas_ids[key] = cid
        self.canvas.tag_bind(cid, "<ButtonPress-1>", lambda e, k=key: self._press(e, k))
        self.canvas.tag_bind(cid, "<B1-Motion>", lambda e, k=key: self._motion(e, k))
        self.canvas.tag_bind(cid, "<ButtonRelease-1>", lambda e: self._release())
        self.canvas.tag_bind(cid, "<Button-2>", lambda e, k=key: self._context_menu(e, k))
        self.canvas.tag_bind(cid, "<Button-3>", lambda e, k=key: self._context_menu(e, k))

    def _item(self, key):
        return next(i for i in self.items if i["key"] == key)

    def _press(self, event, key):
        self.canvas.focus_set()  # so ⌘Z/⇧⌘Z work right after clicking an item
        self.drag_key = key
        self._last_xy = (event.x, event.y)
        self._drag_snapshotted = False

    def _motion(self, event, key):
        if self.drag_key != key:
            return
        if not self._drag_snapshotted:
            self._push_undo()  # snapshot the pre-drag position, once per drag
            self._drag_snapshotted = True
        dx_px = event.x - self._last_xy[0]
        dy_px = event.y - self._last_xy[1]
        self._last_xy = (event.x, event.y)
        item = self._item(key)
        cid = self.canvas_ids[key]
        dx_pdf, dy_pdf = self._canvas_to_pdf_delta(dx_px, dy_px)
        if item["kind"] == "line":
            self.canvas.move(cid, dx_px, 0)
            item["x"] += dx_pdf
        else:
            self.canvas.move(cid, dx_px, dy_px)
            item["x"] += dx_pdf
            item["y"] += dy_pdf
            item["moved"] = True

    def _release(self):
        self.drag_key = None

    # -- origin bracket (draggable, since calibration can be off for a given
    #    product/order and there's no other way to correct it) -------------
    def _bracket_press(self, event):
        self.canvas.focus_set()
        self._bracket_dragging = True
        self._last_xy = (event.x, event.y)
        self._drag_snapshotted = False

    def _bracket_motion(self, event):
        if not self._bracket_dragging:
            return
        if not self._drag_snapshotted:
            self._push_undo()  # snapshot the pre-drag position, once per drag
            self._drag_snapshotted = True
        dx_px = event.x - self._last_xy[0]
        dy_px = event.y - self._last_xy[1]
        self._last_xy = (event.x, event.y)
        dx_pdf, dy_pdf = self._canvas_to_pdf_delta(dx_px, dy_px)
        ox, oy = self.bracket_offset
        self.bracket_offset = (ox + dx_pdf, oy + dy_pdf)
        self._draw_static_bar_and_bracket()

    def _bracket_release(self, event=None):
        self._bracket_dragging = False

    def _bracket_context_menu(self, event):
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label="Rotate 90°", command=self._rotate_bracket)
        if self.bracket_offset != (0.0, 0.0) or self.bracket_rotation != 0:
            menu.add_command(label="Reset origin position", command=self._reset_bracket_offset)
        menu.tk_popup(event.x_root, event.y_root)

    def _rotate_bracket(self):
        self._push_undo()
        self.bracket_rotation = (self.bracket_rotation + 90) % 360
        self._draw_static_bar_and_bracket()

    def _reset_bracket_offset(self):
        self._push_undo()
        self.bracket_offset = (0.0, 0.0)
        self.bracket_rotation = 0
        self._draw_static_bar_and_bracket()

    # -- undo/redo -----------------------------------------------------------
    def _snapshot(self):
        return {
            "items": copy.deepcopy(self.items),
            "oversize_w": self.oversize_w,
            "has_cut_line": self.has_cut_line,
            "bracket_offset": self.bracket_offset,
            "bracket_rotation": self.bracket_rotation,
        }

    def _push_undo(self):
        self.undo_stack.append(self._snapshot())
        self.redo_stack.clear()
        self._update_undo_redo_buttons()

    def _restore(self, snap):
        self.items = copy.deepcopy(snap["items"])
        self.oversize_w = snap["oversize_w"]
        self.has_cut_line = snap["has_cut_line"]
        self.bracket_offset = snap.get("bracket_offset", (0.0, 0.0))
        self.bracket_rotation = snap.get("bracket_rotation", 0)
        for cid in self.canvas_ids.values():
            self.canvas.delete(cid)
        self.canvas_ids = {}
        for item in self.items:
            self._draw_item(item)
        self._draw_static_bar_and_bracket()
        self.cut_btn.config(text="Remove cut-for-shipping line" if self.has_cut_line else "Add cut-for-shipping line")
        self._update_undo_redo_buttons()

    def undo(self):
        if not self.undo_stack:
            return
        self.redo_stack.append(self._snapshot())
        snap = self.undo_stack.pop()
        self._restore(snap)

    def redo(self):
        if not self.redo_stack:
            return
        self.undo_stack.append(self._snapshot())
        snap = self.redo_stack.pop()
        self._restore(snap)

    def _update_undo_redo_buttons(self):
        self.undo_btn.state(["!disabled"] if self.undo_stack else ["disabled"])
        self.redo_btn.state(["!disabled"] if self.redo_stack else ["disabled"])

    def _context_menu(self, event, key):
        item = self._item(key)
        menu = tk.Menu(self, tearoff=0)
        if item.get("editable_text"):
            menu.add_command(label="Edit text…", command=lambda: self._edit_text(key))
        if item.get("deletable"):
            menu.add_command(label="Delete", command=lambda: self._delete_item(key))
        if not item.get("editable_text") and not item.get("deletable"):
            menu.add_command(label="(required item — can't edit or delete)", state="disabled")
        menu.tk_popup(event.x_root, event.y_root)

    def _edit_text(self, key):
        item = self._item(key)
        new_text = simpledialog.askstring("Edit text", "Text (use \\n for a line break):",
                                           initialvalue=item["text"].replace("\n", "\\n"), parent=self)
        if new_text is None:
            return
        self._push_undo()
        item["text"] = new_text.replace("\\n", "\n")
        self.canvas.itemconfigure(self.canvas_ids[key], text=item["text"])

    def _delete_item(self, key, _record_undo=True):
        if _record_undo:
            self._push_undo()
        item = self._item(key)
        self.canvas.delete(self.canvas_ids[key])
        del self.canvas_ids[key]
        self.items.remove(item)
        if key == "cut_line":
            # also drop the paired label and revert the width bump
            label = next((i for i in self.items if i["key"] == "cut_label"), None)
            if label:
                self.canvas.delete(self.canvas_ids["cut_label"])
                del self.canvas_ids["cut_label"]
                self.items.remove(label)
            self.has_cut_line = False
            self.oversize_w -= engine.CUT_FOR_SHIPPING_EXTRA_IN
            self._refresh_width_text()
            self.cut_btn.config(text="Add cut-for-shipping line")

    # -- toolbar actions -----------------------------------------------------
    def toggle_cut_line(self):
        if not self.loaded:
            return
        if self.has_cut_line:
            self._delete_item("cut_line")  # pushes its own undo snapshot
            return
        self._push_undo()
        for item in engine.make_cut_line_items():
            self.items.append(item)
            self._draw_item(item)
        self.has_cut_line = True
        self.oversize_w += engine.CUT_FOR_SHIPPING_EXTRA_IN
        self._refresh_width_text()
        self.cut_btn.config(text="Remove cut-for-shipping line")

    def _refresh_width_text(self):
        width_item = next((i for i in self.items if i["key"] == "width"), None)
        if width_item:
            width_item["text"] = engine.fmt_inches(self.oversize_w)
            if "width" in self.canvas_ids:
                self.canvas.itemconfigure(self.canvas_ids["width"], text=width_item["text"])

    def add_note(self):
        if not self.loaded:
            return
        text = simpledialog.askstring("Add note", "Note text (use \\n for a line break):", parent=self)
        if not text:
            return
        self._push_undo()
        item = engine.make_note_item(text=text.replace("\\n", "\n"))
        self.items.append(item)
        self._draw_item(item)


class SingleOrderTab(ttk.Frame):
    def __init__(self, master):
        super().__init__(master, padding=16)
        self.order_form_path = tk.StringVar()
        self.production_order_path = tk.StringVar()
        self.material = tk.StringVar()
        self.thickness = tk.StringVar(value="")
        self.drain_a = tk.StringVar(value="")
        self.curb_depth = tk.StringVar(value="4")
        self.out_dir = tk.StringVar(value=str(Path.home() / "Desktop"))
        self.out_name = tk.StringVar(value="")
        self.preview_text = tk.StringVar(value="Choose both files, then click Preview.")
        self._preview_after_id = None
        self._last_auto_thickness = None  # tracks our own auto-fills so we don't clobber manual overrides
        self._autoread_attempted_for = None
        self._last_auto_outname = None

        outer = ttk.Frame(self)
        outer.pack(fill="both", expand=True)

        # Left column is scrollable so the Generate button/status stay
        # reachable no matter how tall the form gets (window height is
        # fixed, but the field list has grown over time).
        left_canvas = tk.Canvas(outer, width=580, highlightthickness=0)
        left_scrollbar = ttk.Scrollbar(outer, orient="vertical", command=left_canvas.yview)
        left_canvas.configure(yscrollcommand=left_scrollbar.set)
        left_canvas.pack(side="left", fill="y")
        left_scrollbar.pack(side="left", fill="y")
        left = ttk.Frame(left_canvas)
        left_window = left_canvas.create_window((0, 0), window=left, anchor="nw")

        def _sync_scrollregion(event=None):
            left_canvas.configure(scrollregion=left_canvas.bbox("all"))
        left.bind("<Configure>", _sync_scrollregion)

        def _on_mousewheel(event):
            delta = event.delta
            if abs(delta) >= 120:  # Windows sends multiples of 120; macOS sends small ints
                delta //= 120
            left_canvas.yview_scroll(int(-delta), "units")
        left_canvas.bind("<MouseWheel>", _on_mousewheel)
        left.bind("<MouseWheel>", _on_mousewheel)

        right = ttk.Frame(outer, padding=(20, 0, 0, 0))
        right.pack(side="left", fill="both", expand=True)

        drop_hint = "  (drag & drop onto the box below, or click it)" if DND_AVAILABLE else "  (click the box below to browse)"

        row = 0
        ttk.Label(left, text=f"1. Customer order form -- PDF or photo/scan{drop_hint}", font=("", 12, "bold")).grid(
            row=row, column=0, columnspan=3, sticky="w", pady=(0, 4)
        )
        row += 1
        order_form_zone = DropZone(left, self.order_form_path, self.pick_order_form,
                                    validator=validate_order_form_path,
                                    placeholder="Drop the customer order form here (PDF or JPG/PNG scan), or click to browse")
        order_form_zone.grid(row=row, column=0, columnspan=2, sticky="ew", ipady=4)
        ttk.Button(left, text="Browse…", command=self.pick_order_form).grid(row=row, column=2, padx=6, sticky="n")
        row += 1

        ttk.Label(left, text=f"2. KBRS production order PDF{drop_hint}", font=("", 12, "bold")).grid(
            row=row, column=0, columnspan=3, sticky="w", pady=(14, 4)
        )
        row += 1
        production_order_zone = DropZone(left, self.production_order_path, self.pick_production_order,
                                          validator=validate_production_order_path,
                                          placeholder="Drop the KBRS production order PDF here, or click to browse")
        production_order_zone.grid(row=row, column=0, columnspan=2, sticky="ew", ipady=4)
        ttk.Button(left, text="Browse…", command=self.pick_production_order).grid(row=row, column=2, padx=6, sticky="n")
        row += 1

        ttk.Button(left, text="Preview → read dimensions from files", command=self.preview).grid(
            row=row, column=0, columnspan=3, sticky="w", pady=(10, 4)
        )
        row += 1
        preview_label = ttk.Label(left, textvariable=self.preview_text, foreground="#555", wraplength=520, justify="left")
        preview_label.grid(row=row, column=0, columnspan=3, sticky="w", pady=(0, 10))
        row += 1

        ttk.Label(left, text="3. Traveler", font=("", 12, "bold")).grid(row=row, column=0, sticky="w", pady=(6, 4))
        row += 1
        material_combo = ttk.Combobox(
            left, textvariable=self.material, values=engine.MATERIAL_PRESETS, width=28
        )
        material_combo.grid(row=row, column=0, columnspan=2, sticky="w")
        ttk.Label(left, text="pick one or type a new traveler", foreground="#777").grid(
            row=row, column=1, columnspan=2, sticky="w", padx=(180, 0)
        )
        row += 1

        ttk.Label(left, text='4. Drain dimension "A" (Linear ShowerSlope/Tile-Basin only)', font=("", 12, "bold")).grid(
            row=row, column=0, columnspan=3, sticky="w", pady=(10, 4)
        )
        row += 1
        ttk.Entry(left, textvariable=self.drain_a, width=15).grid(row=row, column=0, sticky="w")
        ttk.Label(left, text='From the order form\'s "A" field. Auto-calculates Thickness below for CLSS/CLTB '
                             '(reads it off the form automatically when possible, otherwise type it in).',
                  foreground="#777", wraplength=380, justify="left").grid(
            row=row, column=1, columnspan=2, sticky="w"
        )
        row += 1

        ttk.Label(left, text="5. Thickness (optional, any product)", font=("", 12, "bold")).grid(
            row=row, column=0, columnspan=3, sticky="w", pady=(10, 4)
        )
        row += 1
        ttk.Entry(left, textvariable=self.thickness, width=15).grid(row=row, column=0, sticky="w")
        ttk.Label(left, text='Blank = not shown. Auto-filled for CLSS/CLTB if "A" above is set (still editable). '
                             'Works on anything with a calibrated spot.',
                  foreground="#777", wraplength=380, justify="left").grid(
            row=row, column=1, columnspan=2, sticky="w"
        )
        row += 1

        ttk.Label(left, text="6. Curb depth (only used for Tile-Basin products)", font=("", 12, "bold")).grid(
            row=row, column=0, columnspan=3, sticky="w", pady=(10, 4)
        )
        row += 1
        ttk.Entry(left, textvariable=self.curb_depth, width=15).grid(row=row, column=0, sticky="w")
        ttk.Label(left, text='Default 4" (HardCurb) — change if a different curb applies', foreground="#777").grid(
            row=row, column=1, columnspan=2, sticky="w"
        )
        row += 1

        ttk.Label(left, text="File name to save as:", font=("", 12, "bold")).grid(row=row, column=0, sticky="w", pady=(14, 4))
        row += 1
        ttk.Entry(left, textvariable=self.out_name, width=30).grid(row=row, column=0, sticky="w")
        ttk.Label(left, text='Suggested from the PO/SO numbers — paste/type over it to rename ".pdf" added automatically.',
                  foreground="#777", wraplength=380, justify="left").grid(
            row=row, column=1, columnspan=2, sticky="w"
        )
        row += 1

        ttk.Label(left, text="Save finished PDF to:", font=("", 12, "bold")).grid(row=row, column=0, sticky="w", pady=(14, 4))
        row += 1
        out_dir_entry = ttk.Entry(left, textvariable=self.out_dir, width=55)
        out_dir_entry.grid(row=row, column=0, columnspan=2, sticky="ew")
        ttk.Button(left, text="Browse…", command=self.pick_out_dir).grid(row=row, column=2, padx=6)
        make_drop_target(out_dir_entry, lambda p: self.out_dir.set(p if os.path.isdir(p) else str(Path(p).parent)))
        row += 1

        gen_btn = ttk.Button(left, text="Generate", command=self.generate)
        gen_btn.grid(row=row, column=0, sticky="w", pady=16)

        row += 1
        self.status = ttk.Label(left, text="", foreground="#0a7d2c", wraplength=520, justify="left")
        self.status.grid(row=row, column=0, columnspan=3, sticky="w")

        for c in range(2):
            left.columnconfigure(c, weight=1)

        # -- live preview / editor panel -------------------------------------
        ttk.Label(right, text="Live preview & editor", font=("", 12, "bold")).pack(anchor="w")
        if EDITOR_AVAILABLE:
            preview_caption = "Updates automatically as you fill things in. Drag any item to move it, right-click to edit/delete."
        else:
            preview_caption = "Preview/editor needs pypdfium2 + Pillow (auto-installed next launch)."
        ttk.Label(right, text=preview_caption, foreground="#777", wraplength=380, justify="left").pack(anchor="w", pady=(0, 8))
        self.layout = InteractiveLayout(right)
        self.layout.pack(fill="both", expand=True)
        if not EDITOR_AVAILABLE:
            self.layout.show_placeholder(preview_caption)
        self._loaded_signature = None

        # auto-refresh the live preview whenever any relevant field changes
        for var in (self.order_form_path, self.production_order_path, self.material,
                    self.thickness, self.drain_a, self.curb_depth):
            var.trace_add("write", lambda *_: self._schedule_preview_update())
        self._schedule_preview_update()

    def _schedule_preview_update(self):
        """Debounced live preview: waits for a short pause in typing/loading
        before actually re-rendering, so it doesn't re-render on every
        keystroke while you're typing a material name."""
        if self._preview_after_id is not None:
            self.after_cancel(self._preview_after_id)
        self._preview_after_id = self.after(400, self._update_preview_now)

    def _maybe_autoread_drain_a(self, order_form):
        """Best-effort: if the order form happens to have a real text layer
        with a 'drain dimension A' value, pull it in automatically. Most
        forms are flattened scans with no text at all, so this quietly does
        nothing most of the time -- that's expected, not a bug."""
        if self.drain_a.get().strip():
            return  # already has a value (auto-read earlier, or typed in) -- don't clobber it
        if self._autoread_attempted_for == order_form:
            return
        self._autoread_attempted_for = order_form
        try:
            found = engine.try_extract_drain_a(order_form)
        except Exception:
            found = None
        if found:
            self.drain_a.set(found)

    def _maybe_autocalc_thickness(self, meta):
        """For CLSS/CLTB, auto-fill Thickness from the drain-dimension-A
        formula once both A and the raw width are known -- but only if the
        user hasn't since typed something else into Thickness by hand."""
        if not meta or meta["sku_prefix"] not in engine.LINEAR_THICKNESS_PREFIXES:
            return
        drain_a_raw = self.drain_a.get().strip()
        if not drain_a_raw:
            return
        try:
            drain_a_val = engine.inches_to_decimal(drain_a_raw)
            calc = engine.compute_linear_thickness(meta["raw_width_in"], drain_a_val)
        except Exception:
            return  # unparseable "A" value -- leave Thickness alone
        calc_text = engine.fmt_inches(calc)
        current = self.thickness.get().strip()
        if current and current != self._last_auto_thickness:
            return  # user has manually overridden the auto-filled value -- respect it
        self._last_auto_thickness = calc_text
        if current != calc_text:
            self.thickness.set(calc_text)

    def _maybe_autofill_outname(self, meta):
        """Suggest a default file name (PO-SO.pdf) once the production
        order is read, but never overwrite a name you've typed/pasted in
        by hand -- same override-respecting pattern as thickness above."""
        if not meta:
            return
        default_name = f"{meta['po_number']}-{meta['so_number']}"
        current = self.out_name.get().strip()
        if current and current != self._last_auto_outname:
            return  # user typed/pasted a custom name -- leave it alone
        self._last_auto_outname = default_name
        if current != default_name:
            self.out_name.set(default_name)

    def _update_preview_now(self):
        self._preview_after_id = None
        order_form = self.order_form_path.get()
        production_order = self.production_order_path.get()

        # -- parse the production order + auto-calc linear thickness; none
        # of this needs pdfium, so it runs even if the visual preview can't --
        meta = profile = oversize_w = oversize_h = wide_origin = None
        if (order_form and production_order and os.path.isfile(production_order)
                and not same_file(order_form, production_order)):
            try:
                meta = engine.parse_production_order(production_order)
                profile = engine.PROFILES.get(meta["sku_prefix"])
                if profile:
                    try:
                        curb = float(self.curb_depth.get() or engine.DEFAULT_CURB_DEPTH_IN)
                    except ValueError:
                        curb = engine.DEFAULT_CURB_DEPTH_IN
                    oversize_w = meta["raw_width_in"] + 1
                    oversize_h = (meta["raw_height_in"] - curb + 1) if profile.get("curb_affects_height") \
                        else meta["raw_height_in"] + 1
                    wide_origin = "bracket_wide" in profile and meta["raw_width_in"] > engine.WIDE_PANEL_THRESHOLD_IN
            except Exception:
                pass  # production order not parseable yet -- still show the plain background below

        if order_form and os.path.isfile(order_form):
            self._maybe_autoread_drain_a(order_form)
        self._maybe_autocalc_thickness(meta)
        self._maybe_autofill_outname(meta)
        # an auto-fill above triggers its own StringVar write -> another
        # debounced call shortly; this pass continues with whatever was
        # already in the fields so the visuals aren't left stale meanwhile

        if not EDITOR_AVAILABLE:
            return
        if not order_form or not os.path.isfile(order_form):
            self.layout.show_placeholder("Load an order form to see it here")
            self._loaded_signature = None
            return
        if production_order and same_file(order_form, production_order):
            self.layout.show_placeholder(
                "Order form and production order are the same file.\n\n"
                "Field 2 needs the plain KBRS production order PDF "
                "(just text, no diagram) -- not this file."
            )
            self._loaded_signature = None
            return

        thickness = self.thickness.get().strip()
        material = self.material.get().strip() or "TRAVELER"

        if profile is None:
            # can't compute annotation items yet -- just show the background
            sig = ("bg-only", order_form)
            if self._loaded_signature != sig:
                ok = self.layout.load_background_only(order_form)
                self._loaded_signature = sig if ok else None
            return

        sig = (order_form, production_order)
        if self._loaded_signature != sig:
            ok = self.layout.load_new_order(order_form, production_order, profile, material,
                                             oversize_w, oversize_h, thickness, bool(wide_origin))
            self._loaded_signature = sig if ok else None
        else:
            self.layout.sync(material, oversize_w, oversize_h, thickness, bool(wide_origin))

    def pick_order_form(self):
        p = filedialog.askopenfilename(
            title="Choose order form (PDF or photo/scan)",
            filetypes=[("PDF or image", "*.pdf *.jpg *.jpeg *.png *.tif *.tiff *.bmp *.gif"),
                       ("PDF", "*.pdf"), ("Images", "*.jpg *.jpeg *.png *.tif *.tiff *.bmp *.gif")],
        )
        if not p:
            return
        error = validate_order_form_path(p)
        if error:
            messagebox.showerror("Not a usable file", error)
            return
        self.order_form_path.set(p)

    def pick_production_order(self):
        p = filedialog.askopenfilename(title="Choose production order PDF", filetypes=[("PDF", "*.pdf")])
        if not p:
            return
        error = validate_production_order_path(p)
        if error:
            messagebox.showerror("Not a usable PDF", error)
            return
        self.production_order_path.set(p)

    def pick_out_dir(self):
        p = filedialog.askdirectory(title="Choose output folder")
        if p:
            self.out_dir.set(p)

    def preview(self):
        po_path = self.production_order_path.get()
        if not po_path:
            self.preview_text.set("Choose the production order PDF first.")
            return
        try:
            meta = engine.parse_production_order(po_path)
            profile = engine.PROFILES.get(meta["sku_prefix"])
            lines = [
                f"PO {meta['po_number']}  /  SO {meta['so_number']}",
                f"Item: {meta['item_name']} ({meta['sku']})",
                f"Raw size: {meta['raw_width_in']}\" x {meta['raw_height_in']}\"",
            ]
            if profile:
                lines[0] = f"{profile['name']}  —  " + lines[0]
                try:
                    curb = float(self.curb_depth.get() or engine.DEFAULT_CURB_DEPTH_IN)
                except ValueError:
                    curb = engine.DEFAULT_CURB_DEPTH_IN
                oversize_w = meta["raw_width_in"] + 1
                if profile.get("curb_affects_height"):
                    oversize_h = meta["raw_height_in"] - curb + 1
                    lines.append(f"Oversize: {oversize_w}\" x {oversize_h}\"  (height uses curb depth {curb}\")")
                else:
                    oversize_h = meta["raw_height_in"] + 1
                    lines.append(f"Oversize: {oversize_w}\" x {oversize_h}\"")
                thickness_val = self.thickness.get().strip()
                if "thickness_text_pos" in profile:
                    lines.append(f"Thickness: {'will show “' + thickness_val + '”' if thickness_val else 'blank — nothing shown'}")
                elif thickness_val:
                    lines.append(f"⚠ You entered a thickness, but {profile['name']} has no calibrated spot for it yet — it will be skipped.")
                else:
                    lines.append("No thickness callout for this product yet (none entered, none needed).")
                if "bracket_wide" in profile and meta["raw_width_in"] > engine.WIDE_PANEL_THRESHOLD_IN:
                    lines.append(f"⚠ WIDE PANEL (>{engine.WIDE_PANEL_THRESHOLD_IN}\") — origin bracket will move to bottom-left. Verify on output.")
            else:
                lines.append(f"⚠ No annotation layout yet for SKU prefix '{meta['sku_prefix']}'. Send a sample form for this product line.")
            self.preview_text.set("\n".join(lines))
        except Exception as e:
            self.preview_text.set(f"Could not read that file: {e}")

    def _validate_and_prepare(self):
        """Shared setup for Generate and Edit-before-generating. Returns a
        dict of everything needed, or None (after showing an error)."""
        order_form = self.order_form_path.get()
        production_order = self.production_order_path.get()
        material = self.material.get().strip()
        thickness = self.thickness.get().strip() or None
        out_dir = self.out_dir.get().strip()
        try:
            curb_depth = float(self.curb_depth.get() or engine.DEFAULT_CURB_DEPTH_IN)
        except ValueError:
            messagebox.showerror("Invalid curb depth", "Curb depth must be a number, e.g. 4")
            return None

        if not order_form or not production_order:
            messagebox.showerror("Missing files", "Choose both the order form and production order PDFs.")
            return None
        if same_file(order_form, production_order):
            messagebox.showerror(
                "Same file selected twice",
                "The order form and production order fields both point to the same file:\n\n"
                f"{order_form}\n\n"
                "Field 1 needs the customer's order form (the diagram + written-in dimensions). "
                "Field 2 needs the separate KBRS production order PDF (plain text, no diagram, no dimensions). "
                "Please choose the two different files.",
            )
            return None
        if not material:
            messagebox.showerror("Missing traveler", "Enter a traveler name (e.g. GRAY TRAVELER).")
            return None
        if not out_dir:
            messagebox.showerror("Missing output folder", "Choose where to save the finished PDF.")
            return None

        try:
            meta = engine.parse_production_order(production_order)
        except Exception as e:
            messagebox.showerror("Couldn't read production order", str(e))
            return None
        profile = engine.PROFILES.get(meta["sku_prefix"])
        if not profile:
            messagebox.showerror(
                "Unknown product",
                f"No annotation layout yet for SKU prefix '{meta['sku_prefix']}'. Send a sample form for this product line.",
            )
            return None

        oversize_w = meta["raw_width_in"] + 1
        if profile.get("curb_affects_height"):
            oversize_h = meta["raw_height_in"] - curb_depth + 1
        else:
            oversize_h = meta["raw_height_in"] + 1
        wide_origin = "bracket_wide" in profile and meta["raw_width_in"] > engine.WIDE_PANEL_THRESHOLD_IN

        typed_name = self.out_name.get().strip()
        if typed_name:
            out_name = typed_name if typed_name.lower().endswith(".pdf") else typed_name + ".pdf"
        else:
            out_name = f"{meta['po_number']}-{meta['so_number']}.pdf"
        out_path = str(Path(out_dir) / out_name)

        return {
            "order_form": order_form, "production_order": production_order,
            "material": material, "thickness": thickness or "", "curb_depth": curb_depth,
            "meta": meta, "profile": profile, "oversize_w": oversize_w, "oversize_h": oversize_h,
            "wide_origin": wide_origin, "out_path": out_path,
        }

    def generate(self):
        # force the live layout to reflect the very latest field values
        # before reading it, in case Generate is clicked faster than the
        # 400ms debounce
        if self._preview_after_id is not None:
            self.after_cancel(self._preview_after_id)
            self._preview_after_id = None
        self._update_preview_now()

        ctx = self._validate_and_prepare()
        if ctx is None:
            return

        self.status.config(text="Working…", foreground="#555")
        self.update_idletasks()

        # use whatever's currently in the live layout (including any drags,
        # edits, notes, or a cut-for-shipping line) if it matches this exact
        # order; otherwise fall back to fresh default positions
        if self.layout.matches(ctx["order_form"], ctx["production_order"]):
            items = self.layout.get_items()
            oversize_w = self.layout.oversize_w  # includes the cut-for-shipping bump, if present
            wide_origin = self.layout.wide_origin
            bracket_offset = self.layout.get_bracket_offset()  # manual nudge from the live preview, if any
            bracket_rotation = self.layout.get_bracket_rotation()  # manual rotation, if any
        else:
            items = engine.compute_default_items(ctx["profile"], ctx["oversize_w"], ctx["oversize_h"],
                                                   thickness=ctx["thickness"])
            oversize_w = ctx["oversize_w"]
            wide_origin = ctx["wide_origin"]
            bracket_offset = (0.0, 0.0)
            bracket_rotation = 0

        try:
            overlay_bytes = engine.render_page(ctx["profile"], ctx["material"], items, wide_origin=wide_origin,
                                                bracket_offset=bracket_offset, bracket_rotation=bracket_rotation)
            engine.merge_pdf(ctx["order_form"], ctx["production_order"], overlay_bytes, ctx["out_path"])
        except Exception as e:
            traceback.print_exc()
            messagebox.showerror("Failed", str(e))
            self.status.config(text="Failed — see message.", foreground="#b00020")
            return

        # verify what actually landed on disk -- if page 2 or its rotation
        # is somehow missing, say so loudly instead of a silent "Done"
        page_note = ""
        try:
            check = PdfReader(ctx["out_path"])
            n_pages = len(check.pages)
            rotation = int(check.pages[1].get("/Rotate", 0)) if n_pages > 1 else None
            if n_pages != 2:
                page_note = f"  ⚠ Expected 2 pages, file has {n_pages} — check the file."
            elif rotation != 90:
                page_note = f"  ⚠ Page 2 rotation is {rotation}°, expected 90° — check the file."
        except Exception as e:
            page_note = f"  ⚠ Couldn't verify the saved file ({type(e).__name__}: {e})."

        thickness_unsupported = bool(ctx["thickness"]) and "thickness_text_pos" not in ctx["profile"]
        wide_msg = "  ⚠ WIDE PANEL: origin moved to bottom-left, please verify." if wide_origin else ""
        thick_msg = "  ⚠ Thickness entered but not supported for this product yet — it was skipped." if thickness_unsupported else ""
        status_color = "#b00020" if page_note else "#0a7d2c"
        self.status.config(text=f"Done → {ctx['out_path']} (2 pages, page 2 rotated){wide_msg}{thick_msg}{page_note}",
                            foreground=status_color)
        open_in_finder(ctx["out_path"])


class BatchTab(ttk.Frame):
    def __init__(self, master):
        super().__init__(master, padding=16)
        self.folder = tk.StringVar()
        self.manifest = tk.StringVar()
        self.out_dir = tk.StringVar(value=str(Path.home() / "Desktop" / "KBRS Markup Output"))

        drop_hint = " (or drag & drop it here)" if DND_AVAILABLE else ""

        row = 0
        ttk.Label(self, text=f"Folder of paired PDFs{drop_hint}", font=("", 12, "bold")).grid(row=row, column=0, columnspan=3, sticky="w")
        row += 1
        ttk.Label(
            self,
            text="Each order = 2 files whose names both contain the PO number, e.g. PO247946_orderform.pdf and PO247946_production.pdf",
            foreground="#555", wraplength=520, justify="left",
        ).grid(row=row, column=0, columnspan=3, sticky="w", pady=(0, 6))
        row += 1
        folder_entry = ttk.Entry(self, textvariable=self.folder, width=55)
        folder_entry.grid(row=row, column=0, columnspan=2, sticky="ew")
        ttk.Button(self, text="Browse…", command=self.pick_folder).grid(row=row, column=2, padx=6)
        make_drop_target(folder_entry, lambda p: self.folder.set(p if os.path.isdir(p) else str(Path(p).parent)))
        row += 1

        ttk.Label(self, text=f"Manifest CSV (material + thickness/curb per PO){drop_hint}", font=("", 12, "bold")).grid(
            row=row, column=0, columnspan=3, sticky="w", pady=(14, 4)
        )
        row += 1
        manifest_entry = ttk.Entry(self, textvariable=self.manifest, width=55)
        manifest_entry.grid(row=row, column=0, columnspan=2, sticky="ew")
        ttk.Button(self, text="Browse…", command=self.pick_manifest).grid(row=row, column=2, padx=6)
        make_drop_target(manifest_entry, self.manifest.set)
        row += 1
        ttk.Button(self, text="Create manifest template from folder…", command=self.make_manifest_template).grid(
            row=row, column=0, sticky="w", pady=(4, 10)
        )
        row += 1

        ttk.Label(self, text=f"Output folder{drop_hint}", font=("", 12, "bold")).grid(row=row, column=0, sticky="w", pady=(10, 4))
        row += 1
        batch_out_entry = ttk.Entry(self, textvariable=self.out_dir, width=55)
        batch_out_entry.grid(row=row, column=0, columnspan=2, sticky="ew")
        ttk.Button(self, text="Browse…", command=self.pick_out_dir).grid(row=row, column=2, padx=6)
        make_drop_target(batch_out_entry, lambda p: self.out_dir.set(p if os.path.isdir(p) else str(Path(p).parent)))
        row += 1

        ttk.Button(self, text="Run batch", command=self.run_batch).grid(row=row, column=0, sticky="w", pady=16)
        row += 1

        self.log = tk.Text(self, height=14, width=72, state="disabled")
        self.log.grid(row=row, column=0, columnspan=3, sticky="nsew")
        self.rowconfigure(row, weight=1)
        for c in range(2):
            self.columnconfigure(c, weight=1)

    def pick_folder(self):
        p = filedialog.askdirectory(title="Choose folder with order form + production order PDFs")
        if p:
            self.folder.set(p)

    def pick_manifest(self):
        p = filedialog.askopenfilename(title="Choose manifest.csv", filetypes=[("CSV", "*.csv")])
        if p:
            self.manifest.set(p)

    def pick_out_dir(self):
        p = filedialog.askdirectory(title="Choose output folder")
        if p:
            self.out_dir.set(p)

    def _log(self, msg):
        self.log.config(state="normal")
        self.log.insert("end", msg + "\n")
        self.log.see("end")
        self.log.config(state="disabled")

    def make_manifest_template(self):
        folder = self.folder.get()
        if not folder:
            messagebox.showerror("Choose a folder first", "Pick the folder of PDFs before creating a manifest template.")
            return
        po_re = re.compile(r"(PO\d+)", re.IGNORECASE)
        pos = set()
        for f in Path(folder).glob("*.pdf"):
            m = po_re.search(f.name)
            if m:
                pos.add(m.group(1).upper())
        if not pos:
            messagebox.showwarning("No PO numbers found", "Couldn't find any 'PO#####' patterns in that folder's filenames.")
            return
        save_path = filedialog.asksaveasfilename(
            title="Save manifest template", defaultextension=".csv",
            initialfile="manifest.csv", filetypes=[("CSV", "*.csv")],
        )
        if not save_path:
            return
        with open(save_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["po_number", "material", "thickness", "curb_depth"])
            for po in sorted(pos):
                writer.writerow([po, "", "", ""])
        self.manifest.set(save_path)
        messagebox.showinfo(
            "Template created",
            f"Created {save_path} with {len(pos)} PO number(s).\n\n"
            "Fill in 'material' for each (required). 'thickness' is optional on any product "
            "(blank = not shown; mostly used for Linear/SRC, but you can add it to others too — "
            "unsupported products will just skip it with a warning in the log). 'curb_depth' only "
            "matters for Tile-Basin products (blank = 4\"). Then Run batch.",
        )

    def run_batch(self):
        folder = self.folder.get()
        manifest = self.manifest.get()
        outdir = self.out_dir.get()
        if not folder or not manifest or not outdir:
            messagebox.showerror("Missing info", "Choose the folder, manifest.csv, and output folder.")
            return

        def worker():
            self._log(f"Starting batch from {folder} …")
            Path(outdir).mkdir(parents=True, exist_ok=True)
            manifest_rows = {}
            with open(manifest, newline="") as f:
                for r in csv.DictReader(f):
                    manifest_rows[r["po_number"].strip().upper()] = r

            po_re = re.compile(r"(PO\d+)", re.IGNORECASE)
            pairs = {}
            for f in Path(folder).glob("*.pdf"):
                m = po_re.search(f.name)
                if not m:
                    self._log(f"SKIP (no PO# in filename): {f.name}")
                    continue
                po = m.group(1).upper()
                pairs.setdefault(po, {})
                if "production" in f.name.lower() or "purchaseorder" in f.name.lower():
                    pairs[po]["production"] = str(f)
                else:
                    pairs[po]["order_form"] = str(f)

            ok, fail = 0, 0
            for po, files in sorted(pairs.items()):
                if "order_form" not in files or "production" not in files:
                    self._log(f"SKIP {po}: missing order form or production order file")
                    fail += 1
                    continue
                row = manifest_rows.get(po, {})
                material = (row.get("material") or "").strip()
                thickness = (row.get("thickness") or "").strip() or None
                try:
                    curb_depth = float(row["curb_depth"]) if row.get("curb_depth") else engine.DEFAULT_CURB_DEPTH_IN
                except ValueError:
                    curb_depth = engine.DEFAULT_CURB_DEPTH_IN
                if not material:
                    self._log(f"SKIP {po}: no material in manifest.csv")
                    fail += 1
                    continue
                try:
                    result = engine.build_output(
                        files["order_form"], files["production"], material,
                        str(Path(outdir) / f"{po}.pdf"),
                        thickness=thickness, curb_depth_in=curb_depth,
                    )
                    wide_note = "  ⚠ WIDE PANEL, verify origin" if result["wide_origin"] else ""
                    thick_note = "  ⚠ thickness not supported for this product, skipped" if result["thickness_unsupported"] else ""
                    self._log(f"OK {po}: {result['oversize_width_in']}\" x {result['oversize_height_in']}\"{wide_note}{thick_note}")
                    ok += 1
                except Exception as e:
                    self._log(f"FAIL {po}: {e}")
                    fail += 1
            self._log(f"\nDone. {ok} succeeded, {fail} skipped/failed. Output in: {outdir}")

        threading.Thread(target=worker, daemon=True).start()


def main():
    root = TkinterDnD.Tk() if DND_AVAILABLE else tk.Tk()
    root.title("KBRS Production Markup")
    root.geometry("1040x860")

    nb = ttk.Notebook(root)
    nb.pack(fill="both", expand=True)
    nb.add(SingleOrderTab(nb), text="Single order")
    nb.add(BatchTab(nb), text="Batch")

    if not DND_AVAILABLE:
        ttk.Label(
            root,
            text="Drag & drop isn't available (tkinterdnd2 not installed) — use the Browse buttons instead.",
            foreground="#b00020",
        ).pack(pady=(0, 6))

    root.mainloop()


if __name__ == "__main__":
    main()
