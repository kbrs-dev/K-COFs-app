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
import io
import os
import platform
import re
import threading
import traceback
from datetime import datetime
from pathlib import Path

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog, colorchooser, font as tkfont

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
ITEM_COLOR_HEX = {"orange": engine.get_accent_hex(), "white": "#ffffff", "black": "#000000"}


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
                                    wraplength=230, justify="center")
        self.name_label.pack(expand=True, fill="both", padx=10, pady=(10, 2))
        self.path_label = tk.Label(self, bg="#f4f4f4", fg="#999", font=("", 9),
                                    wraplength=230, justify="center")
        self.path_label.pack(fill="x", padx=10, pady=(0, 8))

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
        self.cover_ids = {}  # dynamic white box tracking each item's text
        self.fixed_cover_ids = {}  # calibrated white box blanking the original scan value, pre-drag only
        self.line_handle_ids = {}  # key -> (start_handle_cid, end_handle_cid), for extendable lines
        self.static_ids = {}
        self.undo_stack = []
        self.redo_stack = []
        self.drag_key = None
        self._endpoint_drag = None  # which cut-line endpoint (0/1) is being dragged, if any
        self.bg_photo = None
        # A list, not a single bracket -- some orders need more than one
        # CNC/CAD reference point. Each entry: {"offset": (dx,dy) PDF points
        # from the calibrated default, "rotation": 0/90/180/270}. Always at
        # least one; never let the last one be deleted.
        self.brackets = [{"offset": (0.0, 0.0), "rotation": 0}]
        self.bracket_canvas_ids = {}  # bracket index -> canvas line id
        self._dragging_bracket = None  # index of the bracket currently being dragged, or None
        self.bar_offset = (0.0, 0.0)  # manual nudge for the Traveler/material bar, PDF points
        self._bar_dragging = False
        self.real_page_w = engine.PAGE_W  # actual order-form page size, set per-order in load_*
        self.real_page_h = engine.PAGE_H
        self.preview_page = 1  # 1 = order form + editor, 2 = read-only production order preview
        self._page2_photo = None
        self.bg_rotation = 0  # manual rotation of the customer drawing itself (0/90/180/270)
        self.bg_scale = 1.0  # manual resize of the customer drawing itself
        # tracks whether the user deliberately deleted the auto-added Blue
        # Traveler flange note for this order, so _sync_flange_note() doesn't
        # just re-add it on the next field edit -- reset per order load
        self._flange_note_dismissed = False
        # same idea for the checkbox-driven Keyhole Linear drain-plate note
        self._drain_plate_note_dismissed = False

        self.placeholder = ttk.Label(self, text="Load an order form to see it here", foreground="#777",
                                      background="#eeeeee", relief="sunken", wraplength=340, justify="center")
        self.placeholder.pack(fill="both", expand=True)

        self.page_nav = ttk.Frame(self)
        self.page1_btn = ttk.Button(self.page_nav, text="◀ Page 1 (order form)", command=lambda: self.show_page(1))
        self.page1_btn.pack(side="left")
        self.page2_btn = ttk.Button(self.page_nav, text="Page 2 (production order) ▶", command=lambda: self.show_page(2))
        self.page2_btn.pack(side="left", padx=(6, 0))

        self.toolbar = ttk.Frame(self)
        self.cut_btn = ttk.Button(self.toolbar, text="Add cut-for-shipping line", command=self.toggle_cut_line)
        self.cut_btn.pack(side="left", padx=(0, 4))
        ttk.Button(self.toolbar, text="Add note", command=self.add_note).pack(side="left", padx=4)
        ttk.Button(self.toolbar, text="Add bracket", command=self.add_bracket).pack(side="left", padx=4)
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
        self.page_nav.pack_forget()
        self.toolbar.pack_forget()
        self.hint.pack_forget()
        self.canvas_frame.pack_forget()
        self.placeholder.config(text=text)
        self.placeholder.pack(fill="both", expand=True)

    def _show_canvas_ui(self):
        self.placeholder.pack_forget()
        self.page_nav.pack(fill="x", pady=(0, 4))
        self.canvas_frame.pack(fill="both", expand=True)
        self._update_page_nav()
        if self.preview_page == 1:
            self.toolbar.pack(fill="x", pady=(0, 4), before=self.canvas_frame)
            self.hint.pack(fill="x", pady=(0, 4), before=self.canvas_frame)

    def _update_page_nav(self):
        self.page1_btn.state(["disabled"] if self.preview_page == 1 else ["!disabled"])
        self.page2_btn.state(["disabled"] if self.preview_page == 2 else ["!disabled"])

    def show_page(self, page_num):
        """Switch the live preview between page 1 (order form + the
        interactive editor) and page 2 (a read-only preview of the
        production order, rotated 90 -- matching the final merged output).
        Only meaningful once an order form is loaded."""
        if not self.order_form_path:
            return
        self.preview_page = page_num
        self._update_page_nav()
        if page_num == 1:
            self.toolbar.pack(fill="x", pady=(0, 4), before=self.canvas_frame)
            self.hint.pack(fill="x", pady=(0, 4), before=self.canvas_frame)
            self._draw_page1()
        else:
            self.toolbar.pack_forget()
            self.hint.pack_forget()
            self._draw_page2()

    def _draw_page1(self):
        if self.bg_photo is None:
            return
        self.canvas.delete("all")
        self.canvas.config(width=min(self.bg_photo.width(), 420), height=min(self.bg_photo.height(), 640),
                            scrollregion=(0, 0, self.bg_photo.width(), self.bg_photo.height()))
        bg_id = self.canvas.create_image(0, 0, anchor="nw", image=self.bg_photo)
        self.canvas.tag_bind(bg_id, "<Button-2>", self._bg_context_menu)
        self.canvas.tag_bind(bg_id, "<Button-3>", self._bg_context_menu)
        self.canvas_ids = {}
        self.cover_ids = {}
        self.fixed_cover_ids = {}
        self.line_handle_ids = {}
        self.static_ids = {}
        for item in self.items:
            self._draw_item(item)
        self._draw_static_bar_and_bracket()
        self._sync_scrollregion_to_content()

    def _sync_scrollregion_to_content(self):
        """Extends the canvas's scrollable area to include anything dragged
        outside the background image's own bounds (e.g. a dimension label
        moved near/past the edge) -- export already never clips this (see
        render_page()'s auto-grow), but without this the preview's own
        scrollregion stayed fixed to just the background image, so a
        dragged-out item could still LOOK cut off there even though it
        wasn't actually missing from the generated PDF."""
        content_bbox = self.canvas.bbox("all")
        if content_bbox is None:
            return
        bg_w, bg_h = self.bg_photo.width(), self.bg_photo.height()
        min_x = min(0, content_bbox[0])
        min_y = min(0, content_bbox[1])
        max_x = max(bg_w, content_bbox[2])
        max_y = max(bg_h, content_bbox[3])
        self.canvas.config(scrollregion=(min_x, min_y, max_x, max_y))

    # -- rotating/resizing the customer drawing itself (not an overlay item,
    #    the background scan) -- useful for a simple drawing scanned
    #    sideways or awkwardly small/large on the page. Dimension items etc.
    #    stay where they are in the page's own coordinate space and may need
    #    to be dragged back into place afterward; they don't rotate along
    #    with the drawing. ------------------------------------------------
    def _bg_context_menu(self, event):
        if not self.order_form_path:
            return
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label="Rotate drawing 90°", command=self._rotate_background)
        menu.add_command(label="Make drawing bigger (+10%)", command=lambda: self._resize_background(1.1))
        menu.add_command(label="Make drawing smaller (-10%)", command=lambda: self._resize_background(0.9))
        if self.bg_rotation != 0 or abs(self.bg_scale - 1.0) > 0.001:
            menu.add_command(label="Reset drawing rotation/size", command=self._reset_background_transform)
        menu.tk_popup(event.x_root, event.y_root)

    def _reload_background(self):
        try:
            pil_img, real_page_w, real_page_h = self._render_background(self.order_form_path)
        except Exception as e:
            traceback.print_exc()
            messagebox.showerror("Couldn't apply", f"Couldn't re-render the drawing: {e}")
            return
        self.real_page_w, self.real_page_h = real_page_w, real_page_h
        self.bg_photo = ImageTk.PhotoImage(pil_img)
        if self.preview_page == 1:
            self._draw_page1()

    def _rotate_background(self):
        self.bg_rotation = (self.bg_rotation + 90) % 360
        self._reload_background()

    def _resize_background(self, factor):
        self.bg_scale = max(0.3, min(3.0, self.bg_scale * factor))
        self._reload_background()

    def _reset_background_transform(self):
        self.bg_rotation = 0
        self.bg_scale = 1.0
        self._reload_background()

    def _draw_page2(self):
        if not self.production_order_path or not os.path.isfile(self.production_order_path):
            self.canvas.delete("all")
            self.canvas.create_text(10, 10, anchor="nw", text="No production order PDF loaded yet.")
            return
        try:
            pdf = pdfium.PdfDocument(self.production_order_path)
            page = pdf[0]
            bitmap = page.render(scale=CANVAS_SCALE)
            pil_img = bitmap.to_pil().rotate(-90, expand=True)  # matches the final output's page-2 rotation
            pdf.close()
        except Exception as e:
            traceback.print_exc()
            self.canvas.delete("all")
            self.canvas.create_text(10, 10, anchor="nw", text=f"Couldn't render page 2: {e}")
            return
        self._page2_photo = ImageTk.PhotoImage(pil_img)  # keep a reference so it isn't garbage-collected
        self.canvas.delete("all")
        self.canvas.config(width=min(pil_img.width, 420), height=min(pil_img.height, 640),
                            scrollregion=(0, 0, pil_img.width, pil_img.height))
        self.canvas.create_image(0, 0, anchor="nw", image=self._page2_photo)

    def matches(self, order_form_path, production_order_path):
        return (self.loaded and self.order_form_path == order_form_path
                and self.production_order_path == production_order_path)

    def get_items(self):
        return self.items

    def get_brackets(self):
        return self.brackets

    def get_bar_offset(self):
        return self.bar_offset

    # -- coordinate conversion ------------------------------------------------
    # Every calibrated item coordinate (PROFILES, dragged positions) lives in
    # a fixed canonical Letter-space (engine.PAGE_W x engine.PAGE_H), but the
    # actual order-form page being shown/dragged over might be a different
    # real size (landscape photo, A4 scan, etc. -- ensure_pdf() no longer
    # forces it to Letter, to avoid distorting the scan). self.real_page_w/h
    # track that real size; these conversions scale between the two spaces
    # so dragging stays visually accurate against the true background while
    # item positions stay in the canonical space merge_pdf() scales onto the
    # real page at export time.
    def _pdf_to_canvas(self, x, y):
        sx = self.real_page_w / engine.PAGE_W
        sy = self.real_page_h / engine.PAGE_H
        real_x, real_y = x * sx, y * sy
        return real_x * CANVAS_SCALE, (self.real_page_h - real_y) * CANVAS_SCALE

    def _canvas_to_pdf_delta(self, dcx, dcy):
        sx = self.real_page_w / engine.PAGE_W
        sy = self.real_page_h / engine.PAGE_H
        real_dx, real_dy = dcx / CANVAS_SCALE, -dcy / CANVAS_SCALE
        return real_dx / sx, real_dy / sy

    # -- loading ---------------------------------------------------------------
    def _render_background(self, order_form_path):
        """Render order_form_path (through get_transformed_order_form(), so
        any manual rotate/resize the user applied to the drawing is
        included) to a PIL image, plus its real page size. Shared by the
        two load_* methods and _reload_background()."""
        transformed_path = engine.get_transformed_order_form(order_form_path, self.bg_rotation, self.bg_scale)
        pdf = pdfium.PdfDocument(transformed_path)
        page = pdf[0]
        real_page_w, real_page_h = page.get_size()
        bitmap = page.render(scale=CANVAS_SCALE)
        pil_img = bitmap.to_pil()
        pdf.close()
        return pil_img, real_page_w, real_page_h

    def load_background_only(self, order_form_path):
        """Order form picked, but no valid profile yet (production order not
        read/recognized) -- show just the background, no items."""
        self.bg_rotation = 0
        self.bg_scale = 1.0
        try:
            pil_img, real_page_w, real_page_h = self._render_background(order_form_path)
        except Exception as e:
            traceback.print_exc()
            self.show_placeholder(f"Couldn't render a preview of this file ({type(e).__name__}: {e})")
            return False

        self.loaded = False  # background-only isn't a "loaded order" for matches()/get_items() purposes
        self.order_form_path = order_form_path
        self.production_order_path = None
        self.profile = None
        self.real_page_w, self.real_page_h = real_page_w, real_page_h
        self.items = []
        self.bg_photo = ImageTk.PhotoImage(pil_img)
        self.preview_page = 1
        self._show_canvas_ui()
        self._draw_page1()
        return True

    def load_new_order(self, order_form_path, production_order_path, profile, material,
                        oversize_w, oversize_h, thickness, wide_origin, keyhole_linear=False, restore_state=None):
        """A genuinely different order (or first load) -- resets items,
        undo history, and the cut-line state to fresh defaults, unless
        restore_state is given (reopening a recent order for a quick edit --
        see get_recent_order_layout_state()/SingleOrderTab.open_recent_order),
        in which case the previously saved markup is put back instead."""
        self.bg_rotation = restore_state["bg_rotation"] if restore_state else 0
        self.bg_scale = restore_state["bg_scale"] if restore_state else 1.0
        try:
            pil_img, real_page_w, real_page_h = self._render_background(order_form_path)
        except Exception as e:
            traceback.print_exc()
            self.show_placeholder(f"Couldn't render a preview of this file ({type(e).__name__}: {e})")
            return False

        self.order_form_path = order_form_path
        self.production_order_path = production_order_path
        self.profile = profile
        self.real_page_w, self.real_page_h = real_page_w, real_page_h
        self.material = material
        self.oversize_w = oversize_w
        self.oversize_h = oversize_h
        self.wide_origin = wide_origin
        self.bracket_canvas_ids = {}
        self.undo_stack = []
        self.redo_stack = []
        if restore_state:
            self.has_cut_line = restore_state["has_cut_line"]
            self.brackets = copy.deepcopy(restore_state["brackets"])
            self.bar_offset = restore_state["bar_offset"]
            self.items = copy.deepcopy(restore_state["items"])
            # infer whether the flange note was deliberately dismissed in the
            # saved markup (Blue Traveler but no flange note present), so
            # sync() doesn't immediately re-add it against the restored state
            self._flange_note_dismissed = (
                engine.is_blue_traveler(material)
                and not any(i["key"] == engine.FLANGE_NOTE_KEY for i in self.items)
            )
            self._drain_plate_note_dismissed = (
                keyhole_linear
                and not any(i["key"] == engine.DRAIN_PLATE_NOTE_KEY for i in self.items)
            )
        else:
            self.has_cut_line = False
            self.brackets = [{"offset": (0.0, 0.0), "rotation": 0}]
            self.bar_offset = (0.0, 0.0)
            self.items = engine.compute_default_items(profile, oversize_w, oversize_h, thickness=thickness)
            self._flange_note_dismissed = False
            self._sync_flange_note(material)
            self._drain_plate_note_dismissed = False
            self._sync_drain_plate_note(keyhole_linear)

        self.bg_photo = ImageTk.PhotoImage(pil_img)
        self.preview_page = 1
        self._show_canvas_ui()
        self._draw_page1()
        self.cut_btn.config(text="Remove cut-for-shipping line" if self.has_cut_line else "Add cut-for-shipping line")
        self._update_undo_redo_buttons()
        self.loaded = True
        return True

    def get_recent_order_layout_state(self):
        """Full live-editor markup state for persisting to the recent-orders
        list -- everything load_new_order()'s restore_state needs to put the
        exact same markup back when this order is reopened later."""
        return {
            "items": copy.deepcopy(self.items),
            "brackets": copy.deepcopy(self.brackets),
            "bar_offset": list(self.bar_offset),
            "has_cut_line": self.has_cut_line,
            "bg_rotation": self.bg_rotation,
            "bg_scale": self.bg_scale,
        }

    def sync(self, material, oversize_w, oversize_h, thickness, wide_origin, keyhole_linear=False):
        """Same order, just a material/thickness/curb-depth field changed --
        update text and the material bar/bracket without touching anything
        the user has manually dragged, edited, or undo history."""
        if not self.loaded:
            return
        self.material = material
        self.wide_origin = wide_origin
        extra_w, extra_h = self._cut_line_bump()
        self.oversize_w = oversize_w + extra_w
        self.oversize_h = oversize_h + extra_h
        # never delete+recreate an item that's actively being dragged -- it
        # would sever Tkinter's in-progress drag tracking (same class of bug
        # as the old bracket-redraw-during-motion issue); _refresh_*_text
        # already guard against that.
        self._refresh_width_text()
        self._refresh_height_text()

        thickness_item = next((i for i in self.items if i["key"] == "thickness"), None)
        if thickness and "thickness_text_pos" in self.profile:
            if thickness_item:
                # go through make_thickness_item so the trailing " stays
                # consistent, instead of writing the raw field value straight
                # through and dropping it.
                thickness_item["text"] = engine.make_thickness_item(self.profile, thickness)["text"]
                if "thickness" in self.canvas_ids and self.drag_key != "thickness":
                    self._clear_canvas_for("thickness")
                    self._draw_item(thickness_item)
            else:
                new_item = engine.make_thickness_item(self.profile, thickness)
                self.items.append(new_item)
                self._draw_item(new_item)
        elif thickness_item and self.drag_key != "thickness":
            self._clear_canvas_for("thickness")
            self.items.remove(thickness_item)

        self._sync_flange_note(material)
        self._sync_drain_plate_note(keyhole_linear)

        if self._dragging_bracket is None and not self._bar_dragging:
            self._draw_static_bar_and_bracket()

    def _sync_flange_note(self, material):
        """Blue Traveler orders standardly need a 'FLANGE ON ALL SIDES' note
        -- auto-add one when that material is selected/detected, same on/off-
        driven-by-a-field pattern as the thickness item above. Deleting it
        manually (right-click) marks it dismissed for this order so it won't
        just come back on the next field edit; picking a different material
        and back to Blue Traveler again re-offers it (dismissal is cleared as
        soon as the material isn't Blue Traveler, whether or not there was
        still a note left to remove at that point)."""
        needs_flange = engine.is_blue_traveler(material)
        existing = next((i for i in self.items if i["key"] == engine.FLANGE_NOTE_KEY), None)
        if not needs_flange:
            self._flange_note_dismissed = False
            if existing and self.drag_key != engine.FLANGE_NOTE_KEY:
                self._clear_canvas_for(engine.FLANGE_NOTE_KEY)
                self.items.remove(existing)
            return
        if not existing and not self._flange_note_dismissed:
            item = engine.make_flange_note_item()
            self.items.append(item)
            if self.loaded:
                self._draw_item(item)

    def _sync_drain_plate_note(self, needed):
        """Keyhole Linear orders (checkbox, not auto-detected) need a
        'DRAIN PLATE NEEDED' note in the accent color -- same on/off/
        dismiss-tracking pattern as _sync_flange_note above."""
        existing = next((i for i in self.items if i["key"] == engine.DRAIN_PLATE_NOTE_KEY), None)
        if not needed:
            self._drain_plate_note_dismissed = False
            if existing and self.drag_key != engine.DRAIN_PLATE_NOTE_KEY:
                self._clear_canvas_for(engine.DRAIN_PLATE_NOTE_KEY)
                self.items.remove(existing)
            return
        if not existing and not self._drain_plate_note_dismissed:
            item = engine.make_drain_plate_note_item()
            self.items.append(item)
            if self.loaded:
                self._draw_item(item)

    # -- static (non-draggable) material bar + origin bracket -----------------
    def _draw_static_bar_and_bracket(self):
        for cid in self.static_ids.values():
            self.canvas.delete(cid)
        self.static_ids = {}
        for cid in self.bracket_canvas_ids.values():
            self.canvas.delete(cid)
        self.bracket_canvas_ids = {}
        if not self.profile:
            return
        profile = self.profile
        bar_color = engine.resolve_bar_color(self.material)
        text_color = engine.resolve_text_color(bar_color)
        bx0, by0, bx1, by1 = profile["material_bar"]
        bdx, bdy = self.bar_offset
        bx0, by0, bx1, by1 = bx0 + bdx, by0 + bdy, bx1 + bdx, by1 + bdy
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
        bar_manually_adjusted = self.bar_offset != (0.0, 0.0)
        self.static_ids["bar"] = self.canvas.create_rectangle(
            cx0, cy0, cx1, cy1, fill=_color_to_hex(bar_color), outline="#d81b60" if bar_manually_adjusted else "",
            width=2 if bar_manually_adjusted else 0,
        )
        mx, _my = profile["material_text_pos"]
        mx += bdx
        baseline_y_pdf = (by0 + by1) / 2 - fsize_material * 0.35
        tcx, tcy = self._pdf_to_canvas(mx, baseline_y_pdf)
        self.static_ids["bar_text"] = self.canvas.create_text(
            tcx, tcy, text=label_text, fill=_color_to_hex(text_color),
            font=("Helvetica", fsize_px, "bold"), anchor="sw", justify="left",
        )
        # the material/Traveler bar is draggable too -- in case it ends up
        # covering something on the order form it shouldn't.
        for cid in (self.static_ids["bar"], self.static_ids["bar_text"]):
            self.canvas.tag_bind(cid, "<ButtonPress-1>", self._bar_press)
            self.canvas.tag_bind(cid, "<B1-Motion>", self._bar_motion)
            self.canvas.tag_bind(cid, "<ButtonRelease-1>", self._bar_release)
            self.canvas.tag_bind(cid, "<Button-2>", self._bar_context_menu)
            self.canvas.tag_bind(cid, "<Button-3>", self._bar_context_menu)
        # the origin bracket IS draggable -- calibration can be wrong for a
        # given order/product, and there's no other way to correct it. Not
        # just one either: some orders need more than one CNC/CAD reference
        # point, so this loops over self.brackets (always at least one).
        base_pts = profile["bracket_wide"] if (self.wide_origin and "bracket_wide" in profile) else profile["bracket"]
        for i, bracket in enumerate(self.brackets):
            dx_off, dy_off = bracket["offset"]
            rotation = bracket["rotation"]
            pdf_pts = [(px + dx_off, py + dy_off) for px, py in base_pts]
            if rotation:
                pivot = pdf_pts[1]  # the elbow -- the actual corner vertex the bracket marks
                pdf_pts = [engine.rotate_point(pt, pivot, rotation) for pt in pdf_pts]
            flat_pts = []
            for px, py in pdf_pts:
                cx, cy = self._pdf_to_canvas(px, py)
                flat_pts.extend([cx, cy])
            manually_adjusted = bracket["offset"] != (0.0, 0.0) or rotation != 0
            bracket_color = "#d81b60" if manually_adjusted else ITEM_COLOR_HEX["orange"]  # flag a manual nudge/rotation
            cid = self.canvas.create_line(
                *flat_pts, fill=bracket_color, width=max(2, int(profile["bracket_width"] * CANVAS_SCALE))
            )
            self.bracket_canvas_ids[i] = cid
            self.canvas.tag_bind(cid, "<ButtonPress-1>", lambda e, idx=i: self._bracket_press(e, idx))
            self.canvas.tag_bind(cid, "<B1-Motion>", lambda e, idx=i: self._bracket_motion(e, idx))
            self.canvas.tag_bind(cid, "<ButtonRelease-1>", lambda e: self._bracket_release())
            self.canvas.tag_bind(cid, "<Button-2>", lambda e, idx=i: self._bracket_context_menu(e, idx))
            self.canvas.tag_bind(cid, "<Button-3>", lambda e, idx=i: self._bracket_context_menu(e, idx))
        for other_cid in self.canvas_ids.values():
            self.canvas.tag_raise(other_cid)  # keep draggable items above the bar/bracket

    # -- drawing draggable items -----------------------------------------------
    def _clear_canvas_for(self, key):
        """Delete every canvas object (text + cover boxes + line endpoint
        handles) tied to a key, without touching self.items."""
        for d in (self.canvas_ids, self.cover_ids, self.fixed_cover_ids):
            cid = d.pop(key, None)
            if cid is not None:
                self.canvas.delete(cid)
        handles = self.line_handle_ids.pop(key, None)
        if handles:
            for h in handles:
                self.canvas.delete(h)

    def _draw_item(self, item):
        key = item["key"]
        if item["kind"] == "line":
            cx0, cy0 = self._pdf_to_canvas(item["x0"], item["y0"])
            cx1, cy1 = self._pdf_to_canvas(item["x1"], item["y1"])
            color_hex = ITEM_COLOR_HEX.get(item["color"], ITEM_COLOR_HEX["orange"])
            cid = self.canvas.create_line(
                cx0, cy0, cx1, cy1, fill=color_hex,
                width=4, dash=(6, 4) if item.get("dashed") else None,
            )
            targets = (cid,)
            if key == "cut_line":
                # small draggable handles at each end so the line can be
                # extended/shortened, not just moved as a whole
                r = 5
                h0 = self.canvas.create_oval(cx0 - r, cy0 - r, cx0 + r, cy0 + r, fill=color_hex, outline="")
                h1 = self.canvas.create_oval(cx1 - r, cy1 - r, cx1 + r, cy1 + r, fill=color_hex, outline="")
                self.canvas.tag_bind(h0, "<ButtonPress-1>", lambda e: self._cutline_endpoint_press(e, 0))
                self.canvas.tag_bind(h0, "<B1-Motion>", lambda e: self._cutline_endpoint_motion(e, 0))
                self.canvas.tag_bind(h0, "<ButtonRelease-1>", lambda e: self._cutline_endpoint_release())
                self.canvas.tag_bind(h1, "<ButtonPress-1>", lambda e: self._cutline_endpoint_press(e, 1))
                self.canvas.tag_bind(h1, "<B1-Motion>", lambda e: self._cutline_endpoint_motion(e, 1))
                self.canvas.tag_bind(h1, "<ButtonRelease-1>", lambda e: self._cutline_endpoint_release())
                self.line_handle_ids[key] = (h0, h1)
        else:
            cx, cy = self._pdf_to_canvas(item["x"], item["y"])
            fsize_px = max(8, int(item["font_size"] * CANVAS_SCALE))
            tk_font = tkfont.Font(family="Helvetica", size=fsize_px, weight="bold")
            lines = item["text"].split("\n")
            text_w = max((tk_font.measure(ln) for ln in lines), default=0)
            text_h = tk_font.metrics("linespace") * len(lines)
            pad = 4
            # Match the final PDF's white-cover-box behavior (kbrs_markup.py's
            # render_page): a calibrated box blanking the original scanned
            # value (only until the item is moved), plus a padded box that
            # always follows the text itself so it stays legible over any
            # background -- the live preview previously drew neither, so
            # orange text could get lost against a busy scan.
            if item.get("fixed_cover") and not item.get("moved"):
                fx0, fy0, fx1, fy1 = item["fixed_cover"]
                fcx0, fcy0 = self._pdf_to_canvas(fx0, fy0)
                fcx1, fcy1 = self._pdf_to_canvas(fx1, fy1)
                self.fixed_cover_ids[key] = self.canvas.create_rectangle(
                    fcx0, fcy0, fcx1, fcy1, fill="white", outline=""
                )
            cover_id = self.canvas.create_rectangle(
                cx - pad, cy + pad, cx + text_w + pad, cy - text_h - pad,
                fill="white", outline=""
            )
            self.cover_ids[key] = cover_id
            cid = self.canvas.create_text(
                cx, cy, text=item["text"],
                fill=ITEM_COLOR_HEX.get(item["color"], ITEM_COLOR_HEX["orange"]),
                font=("Helvetica", fsize_px, "bold"), anchor="sw", justify="left",
            )
            targets = (cid,)  # cover_id is purely visual, not its own drag target
        self.canvas_ids[key] = cid
        for target in targets:
            self.canvas.tag_bind(target, "<ButtonPress-1>", lambda e, k=key: self._press(e, k))
            self.canvas.tag_bind(target, "<B1-Motion>", lambda e, k=key: self._motion(e, k))
            self.canvas.tag_bind(target, "<ButtonRelease-1>", lambda e: self._release())
            self.canvas.tag_bind(target, "<Button-2>", lambda e, k=key: self._context_menu(e, k))
            self.canvas.tag_bind(target, "<Button-3>", lambda e, k=key: self._context_menu(e, k))

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
            self.canvas.move(cid, dx_px, dy_px)
            item["x0"] += dx_pdf
            item["y0"] += dy_pdf
            item["x1"] += dx_pdf
            item["y1"] += dy_pdf
            for h in self.line_handle_ids.get(key, ()):
                self.canvas.move(h, dx_px, dy_px)
        else:
            self.canvas.move(cid, dx_px, dy_px)
            cover_id = self.cover_ids.get(key)
            if cover_id is not None:
                self.canvas.move(cover_id, dx_px, dy_px)
            fixed_cover_id = self.fixed_cover_ids.pop(key, None)
            if fixed_cover_id is not None:
                self.canvas.delete(fixed_cover_id)  # matches render_page: only shown pre-move
            item["x"] += dx_pdf
            item["y"] += dy_pdf
            item["moved"] = True

    def _release(self):
        self.drag_key = None
        self._sync_scrollregion_to_content()

    # -- cut-line endpoint handles (extend/shorten the line, as opposed to
    #    _press/_motion/_release above which move the whole line) ----------
    def _cutline_endpoint_press(self, event, which):
        self.canvas.focus_set()
        self._endpoint_drag = which
        self._last_xy = (event.x, event.y)
        self._drag_snapshotted = False

    def _cutline_endpoint_motion(self, event, which):
        if self._endpoint_drag != which:
            return
        if not self._drag_snapshotted:
            self._push_undo()
            self._drag_snapshotted = True
        dx_px = event.x - self._last_xy[0]
        dy_px = event.y - self._last_xy[1]
        self._last_xy = (event.x, event.y)
        item = self._item("cut_line")
        dx_pdf, dy_pdf = self._canvas_to_pdf_delta(dx_px, dy_px)
        xkey, ykey = ("x0", "y0") if which == 0 else ("x1", "y1")
        item[xkey] += dx_pdf
        item[ykey] += dy_pdf
        # move just this handle and update the line's coords in place --
        # never delete+recreate mid-drag (see _bracket_motion for why that
        # breaks Tk's in-progress drag tracking).
        handles = self.line_handle_ids.get("cut_line")
        if handles:
            self.canvas.move(handles[which], dx_px, dy_px)
        line_cid = self.canvas_ids.get("cut_line")
        if line_cid is not None:
            ncx0, ncy0 = self._pdf_to_canvas(item["x0"], item["y0"])
            ncx1, ncy1 = self._pdf_to_canvas(item["x1"], item["y1"])
            self.canvas.coords(line_cid, ncx0, ncy0, ncx1, ncy1)

    def _cutline_endpoint_release(self, event=None):
        self._endpoint_drag = None
        self._sync_scrollregion_to_content()

    # -- origin bracket (draggable, since calibration can be off for a given
    #    product/order and there's no other way to correct it; more than one
    #    can exist for orders that need multiple CNC/CAD reference points) --
    def _bracket_press(self, event, index):
        self.canvas.focus_set()
        self._dragging_bracket = index
        self._last_xy = (event.x, event.y)
        self._drag_snapshotted = False

    def _bracket_motion(self, event, index):
        if self._dragging_bracket != index:
            return
        cid = self.bracket_canvas_ids.get(index)
        if not self._drag_snapshotted:
            self._push_undo()  # snapshot the pre-drag position, once per drag
            self._drag_snapshotted = True
            if cid is not None:
                # set the "manually nudged" color once, on the first motion
                # event of the drag, not every single one -- itemconfig() on
                # every pixel of movement was adding needless per-frame cost
                # and made dragging feel sluggish.
                self.canvas.itemconfig(cid, fill="#d81b60")
        dx_px = event.x - self._last_xy[0]
        dy_px = event.y - self._last_xy[1]
        self._last_xy = (event.x, event.y)
        dx_pdf, dy_pdf = self._canvas_to_pdf_delta(dx_px, dy_px)
        ox, oy = self.brackets[index]["offset"]
        self.brackets[index]["offset"] = (ox + dx_pdf, oy + dy_pdf)
        # Move the existing canvas item in place (like _motion does for every
        # other draggable item) instead of a full _draw_static_bar_and_bracket()
        # redraw. A redraw deletes and recreates the item with a new id and
        # fresh bindings on every motion event, which breaks Tkinter's
        # in-progress drag tracking (tied to the original item) and stalls
        # the drag right after it starts.
        if cid is not None:
            self.canvas.move(cid, dx_px, dy_px)

    def _bracket_release(self, event=None):
        self._dragging_bracket = None
        self._sync_scrollregion_to_content()

    def _bracket_context_menu(self, event, index):
        bracket = self.brackets[index]
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label="Rotate 90°", command=lambda: self._rotate_bracket(index, 90))
        # 45-degree step, separate from the 90 above -- for neo-angle/odd
        # showers where the true CNC/CAD origin corner doesn't land on a
        # clean 90-degree turn and 90-only rotation can't line it up.
        menu.add_command(label="Rotate 45°", command=lambda: self._rotate_bracket(index, 45))
        menu.add_command(label="Duplicate this bracket", command=lambda: self._duplicate_bracket(index))
        if bracket["offset"] != (0.0, 0.0) or bracket["rotation"] != 0:
            menu.add_command(label="Reset this bracket's position", command=lambda: self._reset_bracket_offset(index))
        if len(self.brackets) > 1:
            menu.add_command(label="Delete this bracket", command=lambda: self._delete_bracket(index))
        menu.tk_popup(event.x_root, event.y_root)

    def _rotate_bracket(self, index, step=90):
        self._push_undo()
        self.brackets[index]["rotation"] = (self.brackets[index]["rotation"] + step) % 360
        self._draw_static_bar_and_bracket()

    def _reset_bracket_offset(self, index):
        self._push_undo()
        self.brackets[index]["offset"] = (0.0, 0.0)
        self.brackets[index]["rotation"] = 0
        self._draw_static_bar_and_bracket()

    def add_bracket(self):
        """A fresh, un-adjusted bracket at the calibrated default position --
        for an order that needs a second independent reference point rather
        than a copy of one that's already been repositioned."""
        if not self.loaded:
            return
        self._push_undo()
        self.brackets.append({"offset": (0.0, 0.0), "rotation": 0})
        self._draw_static_bar_and_bracket()

    def _duplicate_bracket(self, index):
        self._push_undo()
        src = self.brackets[index]
        # nudge slightly so the copy doesn't sit exactly on top of the
        # original, making it obvious there are now two and easy to grab
        ox, oy = src["offset"]
        self.brackets.append({"offset": (ox + 20.0, oy - 20.0), "rotation": src["rotation"]})
        self._draw_static_bar_and_bracket()

    def _delete_bracket(self, index):
        if len(self.brackets) <= 1:
            return  # always keep at least one -- it's the CNC/CAD reference point
        self._push_undo()
        del self.brackets[index]
        self._draw_static_bar_and_bracket()

    # -- material/Traveler bar (draggable, in case it covers something on the
    #    order form it shouldn't) --------------------------------------------
    def _bar_press(self, event):
        self.canvas.focus_set()
        self._bar_dragging = True
        self._last_xy = (event.x, event.y)
        self._drag_snapshotted = False

    def _bar_motion(self, event):
        if not self._bar_dragging:
            return
        if not self._drag_snapshotted:
            self._push_undo()
            self._drag_snapshotted = True
            bar_cid = self.static_ids.get("bar")
            if bar_cid is not None:
                # once per drag, not once per motion event -- see the
                # matching comment in _bracket_motion.
                self.canvas.itemconfig(bar_cid, outline="#d81b60", width=2)
        dx_px = event.x - self._last_xy[0]
        dy_px = event.y - self._last_xy[1]
        self._last_xy = (event.x, event.y)
        dx_pdf, dy_pdf = self._canvas_to_pdf_delta(dx_px, dy_px)
        ox, oy = self.bar_offset
        self.bar_offset = (ox + dx_pdf, oy + dy_pdf)
        # Move the existing items in place rather than a full redraw -- see
        # the comment in _bracket_motion for why a redraw mid-drag breaks
        # Tkinter's drag tracking.
        for key in ("bar", "bar_text"):
            cid = self.static_ids.get(key)
            if cid is not None:
                self.canvas.move(cid, dx_px, dy_px)

    def _bar_release(self, event=None):
        self._bar_dragging = False
        self._sync_scrollregion_to_content()

    def _bar_context_menu(self, event):
        menu = tk.Menu(self, tearoff=0)
        if self.bar_offset != (0.0, 0.0):
            menu.add_command(label="Reset Traveler bar position", command=self._reset_bar_offset)
        else:
            menu.add_command(label="(drag the bar to move it)", state="disabled")
        menu.tk_popup(event.x_root, event.y_root)

    def _reset_bar_offset(self):
        self._push_undo()
        self.bar_offset = (0.0, 0.0)
        self._draw_static_bar_and_bracket()

    # -- undo/redo -----------------------------------------------------------
    def _snapshot(self):
        return {
            "items": copy.deepcopy(self.items),
            "oversize_w": self.oversize_w,
            "oversize_h": self.oversize_h,
            "has_cut_line": self.has_cut_line,
            "brackets": copy.deepcopy(self.brackets),
            "bar_offset": self.bar_offset,
        }

    def _push_undo(self):
        self.undo_stack.append(self._snapshot())
        self.redo_stack.clear()
        self._update_undo_redo_buttons()

    def _restore(self, snap):
        self.items = copy.deepcopy(snap["items"])
        self.oversize_w = snap["oversize_w"]
        self.oversize_h = snap.get("oversize_h", self.oversize_h)
        self.has_cut_line = snap["has_cut_line"]
        self.brackets = copy.deepcopy(snap.get("brackets", [{"offset": (0.0, 0.0), "rotation": 0}]))
        self.bar_offset = snap.get("bar_offset", (0.0, 0.0))
        for cid in (list(self.canvas_ids.values()) + list(self.cover_ids.values())
                    + list(self.fixed_cover_ids.values()) + [h for pair in self.line_handle_ids.values() for h in pair]):
            self.canvas.delete(cid)
        self.canvas_ids = {}
        self.cover_ids = {}
        self.fixed_cover_ids = {}
        self.line_handle_ids = {}
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
        if key.startswith("note_"):
            other = "orange" if item.get("color") == "black" else "black"
            menu.add_command(label=f"Change to {other} text", command=lambda: self._toggle_note_color(key))
        if key == "cut_line":
            menu.add_command(label="Rotate 90°", command=self._rotate_cut_line)
        if item.get("deletable"):
            menu.add_command(label="Delete", command=lambda: self._delete_item(key))
        if not item.get("editable_text") and not item.get("deletable"):
            menu.add_command(label="(required item — can't edit or delete)", state="disabled")
        menu.tk_popup(event.x_root, event.y_root)

    def _toggle_note_color(self, key):
        item = self._item(key)
        self._push_undo()
        if item.get("color") == "black":
            item["color"] = "orange"
            item["font_size"] = 20
        else:
            item["color"] = "black"
            item["font_size"] = 14
        self._clear_canvas_for(key)
        self._draw_item(item)

    def _rotate_cut_line(self):
        """Swap the cut line between vertical and horizontal, and move its
        +CUT_FOR_SHIPPING_EXTRA_IN oversize bump to the axis it now runs
        across -- a horizontal cut affects the height dimension, not width."""
        item = self._item("cut_line")
        self._push_undo()
        cx = (item["x0"] + item["x1"]) / 2
        cy = (item["y0"] + item["y1"]) / 2
        pivot = (cx, cy)
        item["x0"], item["y0"] = engine.rotate_point((item["x0"], item["y0"]), pivot, 90)
        item["x1"], item["y1"] = engine.rotate_point((item["x1"], item["y1"]), pivot, 90)
        was_vertical = item.get("orientation") == "vertical"
        item["orientation"] = "horizontal" if was_vertical else "vertical"
        if was_vertical:
            self.oversize_w -= engine.CUT_FOR_SHIPPING_EXTRA_IN
            self.oversize_h += engine.CUT_FOR_SHIPPING_EXTRA_IN
        else:
            self.oversize_h -= engine.CUT_FOR_SHIPPING_EXTRA_IN
            self.oversize_w += engine.CUT_FOR_SHIPPING_EXTRA_IN
        self._clear_canvas_for("cut_line")
        self._draw_item(item)
        self._refresh_width_text()
        self._refresh_height_text()

    def _edit_text(self, key):
        item = self._item(key)
        new_text = simpledialog.askstring("Edit text", "Text (use \\n for a line break):",
                                           initialvalue=item["text"].replace("\n", "\\n"), parent=self)
        if new_text is None:
            return
        self._push_undo()
        item["text"] = new_text.replace("\\n", "\n")
        self._clear_canvas_for(key)
        self._draw_item(item)  # recreate so the cover box resizes to the new text

    def _delete_item(self, key, _record_undo=True):
        if _record_undo:
            self._push_undo()
        item = self._item(key)
        self._clear_canvas_for(key)
        self.items.remove(item)
        if key == engine.FLANGE_NOTE_KEY:
            self._flange_note_dismissed = True
        if key == engine.DRAIN_PLATE_NOTE_KEY:
            self._drain_plate_note_dismissed = True
        if key == "cut_line":
            # also drop the paired label and revert the oversize bump from
            # whichever axis it's currently on (may have been rotated since
            # it was added)
            label = next((i for i in self.items if i["key"] == "cut_label"), None)
            if label:
                self._clear_canvas_for("cut_label")
                self.items.remove(label)
            if item.get("orientation") == "horizontal":
                self.oversize_h -= engine.CUT_FOR_SHIPPING_EXTRA_IN
                self._refresh_height_text()
            else:
                self.oversize_w -= engine.CUT_FOR_SHIPPING_EXTRA_IN
                self._refresh_width_text()
            self.has_cut_line = False
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
        # the "Cut for shipping" label's cover box is drawn after (so above)
        # the line and starts out overlapping it -- without this, a click
        # right where they overlap silently hits the label's (non-
        # interactive) cover box instead of the draggable line.
        line_cid = self.canvas_ids.get("cut_line")
        if line_cid is not None:
            self.canvas.tag_raise(line_cid)
            for h in self.line_handle_ids.get("cut_line", ()):
                self.canvas.tag_raise(h)
        self.has_cut_line = True
        self.oversize_w += engine.CUT_FOR_SHIPPING_EXTRA_IN
        self._refresh_width_text()
        self.cut_btn.config(text="Remove cut-for-shipping line")

    def _refresh_width_text(self):
        width_item = next((i for i in self.items if i["key"] == "width"), None)
        if width_item:
            width_item["text"] = engine.fmt_inches(self.oversize_w)
            if "width" in self.canvas_ids and self.drag_key != "width":
                self._clear_canvas_for("width")
                self._draw_item(width_item)

    def _refresh_height_text(self):
        height_item = next((i for i in self.items if i["key"] == "height"), None)
        if height_item:
            height_item["text"] = engine.fmt_inches(self.oversize_h)
            if "height" in self.canvas_ids and self.drag_key != "height":
                self._clear_canvas_for("height")
                self._draw_item(height_item)

    def _cut_line_bump(self):
        """(extra_w, extra_h) currently added by the cut-for-shipping line,
        if present -- applied to whichever axis it currently runs across
        (width if vertical, height if horizontal), not always width."""
        if not self.has_cut_line:
            return 0.0, 0.0
        item = next((i for i in self.items if i["key"] == "cut_line"), None)
        if item is None:
            return 0.0, 0.0
        if item.get("orientation") == "horizontal":
            return 0.0, engine.CUT_FOR_SHIPPING_EXTRA_IN
        return engine.CUT_FOR_SHIPPING_EXTRA_IN, 0.0

    def add_note(self):
        if not self.loaded:
            return
        text = simpledialog.askstring("Add note", "Note text (use \\n for a line break):", parent=self)
        if not text:
            return
        use_black = messagebox.askyesno(
            "Note color",
            "Use black text (smaller) for this note?\n\nNo = orange, matching the other measurements.",
            parent=self,
        )
        self._push_undo()
        if use_black:
            item = engine.make_note_item(text=text.replace("\\n", "\n"), color="black", font_size=14)
        else:
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
        self.thickness_warning = tk.StringVar(value="")
        self.drain_a = tk.StringVar(value="")
        self.curb_depth = tk.StringVar(value="")
        # Some Tile-Basin orders have a curb on both the width and height
        # sides (e.g. an L-shaped/corner basin), not just height -- this
        # varies per order, not by product type, so it's a per-order toggle
        # rather than baked into the CTB/CLTB profile.
        self.curb_affects_width = tk.BooleanVar(value=False)
        # Keyhole Linear orders need a drain plate -- checked here adds a
        # "DRAIN PLATE NEEDED" note to the drawing in the accent color.
        self.keyhole_linear = tk.BooleanVar(value=False)
        # Raw width/height normally come from parsing the production order
        # PDF's text -- these are the manual fallback/override for when that
        # parse fails or gets a handwritten/nonstandard order wrong, same
        # idea as the Drain A field already having a manual fallback.
        self.raw_width = tk.StringVar(value="")
        self.raw_height = tk.StringVar(value="")
        # Applied in _resolve_production_meta() so it corrects EVERYTHING
        # downstream (oversize calc, wide-panel bracket check, the drawing
        # itself) regardless of whether the mixed-up values came from the
        # parse or were typed into the override fields above.
        self.swap_width_height = tk.BooleanVar(value=False)
        self.product_type_override = tk.StringVar(value="")
        self.out_dir = tk.StringVar(value=engine.get_default_output_dir() or str(Path.home() / "Desktop"))
        self.out_name = tk.StringVar(value="")
        self.preview_text = tk.StringVar(value="Choose both files, then click Preview.")
        self._preview_after_id = None
        self._last_auto_thickness = None  # tracks our own auto-fills so we don't clobber manual overrides
        self._autoread_attempted_for = None
        self._last_auto_outname = None
        self._last_auto_raw_width = None
        self._last_auto_raw_height = None
        self._pending_restore_state = None  # set by open_recent_order(), consumed by the next load
        self.on_recent_orders_changed = None  # callback set by main() to refresh the File > Recent Orders menu

        outer = ttk.Frame(self)
        outer.pack(fill="both", expand=True)

        # Left column is scrollable so the Generate button/status stay
        # reachable no matter how tall the form gets, and so the panel
        # doesn't get clipped on a narrower window. A real horizontal
        # scrollbar is included too, not just vertical -- trackpad/wheel
        # scroll can be unreliable over native ttk widgets on macOS (the
        # event doesn't always reach Tk's dispatcher, no binding trick fixes
        # that), but dragging a scrollbar thumb is a direct, reliable
        # interaction that doesn't depend on wheel-event delivery at all.
        left_container = ttk.Frame(outer)
        left_container.pack(side="left", fill="y")
        canvas_row = ttk.Frame(left_container)
        canvas_row.pack(side="top", fill="both", expand=True)
        left_canvas = tk.Canvas(canvas_row, width=700, highlightthickness=0)
        left_vscroll = ttk.Scrollbar(canvas_row, orient="vertical", command=left_canvas.yview)
        left_canvas.configure(yscrollcommand=left_vscroll.set)
        left_canvas.pack(side="left", fill="both", expand=True)
        left_vscroll.pack(side="left", fill="y")
        left_hscroll = ttk.Scrollbar(left_container, orient="horizontal", command=left_canvas.xview)
        left_canvas.configure(xscrollcommand=left_hscroll.set)
        left_hscroll.pack(side="bottom", fill="x")
        left = ttk.Frame(left_canvas)
        left_window = left_canvas.create_window((0, 0), window=left, anchor="nw")

        def _sync_scrollregion(event=None):
            left_canvas.configure(scrollregion=left_canvas.bbox("all"))
        left.bind("<Configure>", _sync_scrollregion)

        # A plain bind() on left_canvas/left only fires when the pointer is
        # directly over empty canvas space -- the panel is packed with real
        # child widgets (Entry, Combobox, Label...), and Tk delivers
        # wheel/trackpad events to whichever specific widget is under the
        # pointer, not bubbled up to ancestors. A bind_all + ancestry-check
        # didn't reliably fix it either, likely because ttk's own class
        # bindings for Entry/Combobox on Aqua run before the "all" bindtag
        # and can swallow the event first. Binding directly on every
        # descendant widget (below, after the panel is fully built) fires at
        # the highest-priority instance-binding level, ahead of any class
        # binding.
        def _on_mousewheel(event):
            delta = event.delta
            if abs(delta) >= 120:  # Windows sends multiples of 120; macOS sends small ints
                delta //= 120
            left_canvas.yview_scroll(int(-delta), "units")

        def _on_shift_mousewheel(event):
            delta = event.delta
            if abs(delta) >= 120:
                delta //= 120
            left_canvas.xview_scroll(int(-delta), "units")

        def _on_button4(event):
            left_canvas.yview_scroll(-1, "units")

        def _on_button5(event):
            left_canvas.yview_scroll(1, "units")

        def _bind_scroll_recursive(widget):
            widget.bind("<MouseWheel>", _on_mousewheel, add="+")
            widget.bind("<Shift-MouseWheel>", _on_shift_mousewheel, add="+")
            widget.bind("<Button-4>", _on_button4, add="+")  # Linux/X11 wheel
            widget.bind("<Button-5>", _on_button5, add="+")
            for child in widget.winfo_children():
                _bind_scroll_recursive(child)

        right = ttk.Frame(outer, padding=(20, 0, 0, 0))
        right.pack(side="left", fill="both", expand=True)

        row = 0
        files_frame = ttk.Frame(left)
        files_frame.grid(row=row, column=0, columnspan=3, sticky="ew", pady=(0, 14))
        files_frame.columnconfigure(0, weight=1)
        files_frame.columnconfigure(1, weight=1)

        ttk.Label(files_frame, text="Customer Drawing", font=("", 12, "bold")).grid(
            row=0, column=0, sticky="w", padx=(0, 6)
        )
        order_form_zone = DropZone(files_frame, self.order_form_path, self.pick_order_form,
                                    validator=validate_order_form_path,
                                    placeholder="Drop the customer order form here (PDF or JPG/PNG scan), or click to browse")
        order_form_zone.grid(row=1, column=0, sticky="new", padx=(0, 6), ipady=4)
        ttk.Button(files_frame, text="Browse…", command=self.pick_order_form).grid(
            row=2, column=0, sticky="w", padx=(0, 6), pady=(4, 0)
        )

        ttk.Label(files_frame, text="Customer Purchase Order", font=("", 12, "bold")).grid(
            row=0, column=1, sticky="w", padx=(6, 0)
        )
        production_order_zone = DropZone(files_frame, self.production_order_path, self.pick_production_order,
                                          validator=validate_production_order_path,
                                          placeholder="Drop the KBRS production order PDF here, or click to browse")
        production_order_zone.grid(row=1, column=1, sticky="new", padx=(6, 0), ipady=4)
        ttk.Button(files_frame, text="Browse…", command=self.pick_production_order).grid(
            row=2, column=1, sticky="w", padx=(6, 0), pady=(4, 0)
        )
        row += 1

        ttk.Button(left, text="Preview → read dimensions from files", command=self.preview).grid(
            row=row, column=0, columnspan=3, sticky="w", pady=(10, 4)
        )
        row += 1
        preview_label = ttk.Label(left, textvariable=self.preview_text, foreground="#555", wraplength=520, justify="left")
        preview_label.grid(row=row, column=0, columnspan=3, sticky="w", pady=(0, 10))
        row += 1

        ttk.Label(left, text="Raw width/height override", font=("", 11, "bold")).grid(
            row=row, column=0, columnspan=3, sticky="w", pady=(0, 4)
        )
        row += 1
        raw_dim_frame = ttk.Frame(left)
        raw_dim_frame.grid(row=row, column=0, sticky="w")
        ttk.Label(raw_dim_frame, text="Width:").pack(side="left")
        ttk.Entry(raw_dim_frame, textvariable=self.raw_width, width=8).pack(side="left", padx=(4, 12))
        ttk.Label(raw_dim_frame, text="Height:").pack(side="left")
        ttk.Entry(raw_dim_frame, textvariable=self.raw_height, width=8).pack(side="left", padx=(4, 0))
        ttk.Label(left, text='Auto-filled when Preview reads the production order OK. Only type here if that file '
                             "can't be read, or reads a handwritten/nonstandard order wrong — e.g. 78 or 78 1/4.",
                  foreground="#777", wraplength=380, justify="left").grid(
            row=row, column=1, columnspan=2, sticky="w"
        )
        row += 1
        ttk.Checkbutton(
            left, text="Swap width/height", variable=self.swap_width_height,
        ).grid(row=row, column=0, sticky="w", pady=(2, 0))
        ttk.Label(left, text="In case the production order (or a manual entry above) has them switched.",
                  foreground="#777").grid(row=row, column=1, columnspan=2, sticky="w", pady=(2, 0))
        row += 1

        ttk.Label(left, text="Product type override", font=("", 11, "bold")).grid(
            row=row, column=0, columnspan=3, sticky="w", pady=(6, 4)
        )
        row += 1
        ttk.Combobox(
            left, textvariable=self.product_type_override, values=[""] + sorted(engine.PROFILES.keys()), width=13
        ).grid(row=row, column=0, sticky="w")
        ttk.Label(left, text="Leave blank to auto-detect from the production order PDF. Only needed if that file "
                             "can't be read at all.", foreground="#777", wraplength=380, justify="left").grid(
            row=row, column=1, columnspan=2, sticky="w"
        )
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
        ttk.Checkbutton(
            left, text="Keyhole Linear", variable=self.keyhole_linear,
        ).grid(row=row, column=0, sticky="w", pady=(4, 0))
        ttk.Label(left, text='Adds a "DRAIN PLATE NEEDED" note to the drawing, in the accent color.',
                  foreground="#777").grid(row=row, column=1, columnspan=2, sticky="w", pady=(4, 0))
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
        # Not every product has a calibrated spot for a thickness callout
        # (currently CSS/CTB don't) -- typing one there used to just get
        # silently skipped on export with no live sign anything was wrong,
        # which read as a random "sometimes it doesn't post" glitch. This
        # shows up immediately, right where you're typing, instead of only
        # after Preview or Generate.
        ttk.Label(left, textvariable=self.thickness_warning, foreground="#b00020",
                  wraplength=520, justify="left").grid(
            row=row, column=0, columnspan=3, sticky="w", pady=(0, 4)
        )
        row += 1

        ttk.Label(left, text="6. Curb depth (only used for Tile-Basin products)", font=("", 12, "bold")).grid(
            row=row, column=0, columnspan=3, sticky="w", pady=(10, 4)
        )
        row += 1
        ttk.Entry(left, textvariable=self.curb_depth, width=15).grid(row=row, column=0, sticky="w")
        ttk.Label(left, text='Blank = curbless (0"). Type a depth if this order has a curb, e.g. 4 for standard HardCurb.',
                  foreground="#777", wraplength=380, justify="left").grid(
            row=row, column=1, columnspan=2, sticky="w"
        )
        row += 1
        ttk.Checkbutton(
            left, text="Curb also affects width",
            variable=self.curb_affects_width,
        ).grid(row=row, column=0, sticky="w", pady=(2, 0))
        ttk.Label(left, text="Double curb — e.g. an L-shaped/corner basin", foreground="#777").grid(
            row=row, column=1, columnspan=2, sticky="w", pady=(2, 0)
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

        gen_frame = ttk.Frame(left)
        gen_frame.grid(row=row, column=0, columnspan=2, sticky="w", pady=16)
        gen_btn = ttk.Button(gen_frame, text="Generate", command=self.generate)
        gen_btn.pack(side="left")
        ttk.Button(gen_frame, text="Start new order", command=self.start_new_order).pack(side="left", padx=(8, 0))
        ttk.Label(left, text="Generate opens a Save dialog — pick or confirm the folder there.",
                  foreground="#777").grid(row=row, column=1, columnspan=2, sticky="w", pady=16, padx=(140, 0))

        row += 1
        self.status = ttk.Label(left, text="", foreground="#0a7d2c", wraplength=520, justify="left")
        self.status.grid(row=row, column=0, columnspan=3, sticky="w")

        for c in range(2):
            left.columnconfigure(c, weight=1)

        _bind_scroll_recursive(left_canvas)  # covers left_canvas + every field widget inside left

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
                    self.thickness, self.drain_a, self.curb_depth, self.curb_affects_width,
                    self.keyhole_linear, self.swap_width_height,
                    self.raw_width, self.raw_height, self.product_type_override):
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

    def _maybe_autofill_blue_traveler_thickness(self):
        """Blue Traveler orders are standardly 1.5" thick -- auto-fill
        Thickness when that material is selected/typed, same override-
        respecting pattern (and the same _last_auto_thickness tracker, since
        the two are mutually exclusive by material) as the CLSS/CLTB drain-A
        formula in _maybe_autocalc_thickness above."""
        current = self.thickness.get().strip()
        if current and current != self._last_auto_thickness:
            return  # user has manually overridden the auto-filled value -- respect it
        self._last_auto_thickness = engine.BLUE_TRAVELER_THICKNESS_IN
        if current != engine.BLUE_TRAVELER_THICKNESS_IN:
            self.thickness.set(engine.BLUE_TRAVELER_THICKNESS_IN)

    def _maybe_autofill_outname(self, meta):
        """Suggest a default file name (PO-SO.pdf) once the production
        order is read, but never overwrite a name you've typed/pasted in
        by hand -- same override-respecting pattern as thickness above."""
        if not meta or not meta["po_number"] or not meta["so_number"]:
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
            meta, profile, _error = self._resolve_production_meta()
            # _error is ignored here -- an unreadable/unresolved production
            # order just means we can't load the editor yet (still show the
            # plain background below); preview()/_validate_and_prepare()
            # are what actually surface the error text to the user.
            if profile:
                try:
                    curb = float(self.curb_depth.get().strip() or "0")
                except ValueError:
                    curb = engine.DEFAULT_CURB_DEPTH_IN
                oversize_w = (meta["raw_width_in"] - curb + 1) \
                    if (profile.get("curb_affects_height") and self.curb_affects_width.get()) \
                    else meta["raw_width_in"] + 1
                oversize_h = (meta["raw_height_in"] - curb + 1) if profile.get("curb_affects_height") \
                    else meta["raw_height_in"] + 1
                wide_origin = "bracket_wide" in profile and meta["raw_width_in"] > engine.WIDE_PANEL_THRESHOLD_IN

        if order_form and os.path.isfile(order_form):
            self._maybe_autoread_drain_a(order_form)
        if engine.is_blue_traveler(self.material.get()):
            self._maybe_autofill_blue_traveler_thickness()
        else:
            self._maybe_autocalc_thickness(meta)
        self._maybe_autofill_outname(meta)
        # an auto-fill above triggers its own StringVar write -> another
        # debounced call shortly; this pass continues with whatever was
        # already in the fields so the visuals aren't left stale meanwhile

        if profile and self.thickness.get().strip() and "thickness_text_pos" not in profile:
            self.thickness_warning.set(
                f"⚠ {profile['name']} has no calibrated spot for a thickness callout yet — "
                f"this won't show up on the drawing. Use Add note instead if you need it noted."
            )
        else:
            self.thickness_warning.set("")

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
                                             oversize_w, oversize_h, thickness, bool(wide_origin),
                                             keyhole_linear=self.keyhole_linear.get(),
                                             restore_state=self._pending_restore_state)
            self._pending_restore_state = None
            self._loaded_signature = sig if ok else None
        else:
            self.layout.sync(material, oversize_w, oversize_h, thickness, bool(wide_origin),
                              keyhole_linear=self.keyhole_linear.get())

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

    def _resolve_production_meta(self):
        """Merge a production-order-PDF parse with the manual raw
        width/height/product-type overrides. On a successful parse, also
        auto-fills the override fields (unless the user's already typed
        something different) so a wrong read is easy to spot and correct --
        same override-respecting pattern as thickness/drain-A.

        Returns (meta, profile, error). meta's po_number/so_number/item_name/
        sku are None if the file itself couldn't be parsed at all (manual
        entry only); error is a user-facing string, or None on success."""
        po_path = self.production_order_path.get()
        parsed = None
        parse_error = None
        if po_path:
            try:
                parsed = engine.parse_production_order(po_path)
            except Exception as e:
                parse_error = str(e)

        if parsed:
            for field, var, last_attr in (
                ("raw_width_in", self.raw_width, "_last_auto_raw_width"),
                ("raw_height_in", self.raw_height, "_last_auto_raw_height"),
            ):
                auto_text = engine.fmt_inches(parsed[field])
                current = var.get().strip()
                if (not current or current == getattr(self, last_attr)) and current != auto_text:
                    var.set(auto_text)  # StringVar.set() fires its trace unconditionally, even
                    # to the same value -- writing every cycle re-armed the debounce timer
                    # forever, which meant sync() (and its destructive item redraws) kept
                    # firing every ~400ms and interrupting any drag in progress.
                setattr(self, last_attr, auto_text)

        sku_prefix = self.product_type_override.get().strip() or (parsed["sku_prefix"] if parsed else None)
        raw_w_text = self.raw_width.get().strip()
        raw_h_text = self.raw_height.get().strip()
        try:
            raw_width_in = engine.inches_to_decimal(raw_w_text) if raw_w_text else (parsed["raw_width_in"] if parsed else None)
            raw_height_in = engine.inches_to_decimal(raw_h_text) if raw_h_text else (parsed["raw_height_in"] if parsed else None)
        except ValueError:
            return None, None, 'Raw width/height must be a number or fraction, e.g. 78 or "78 1/4".'

        if raw_width_in is None or raw_height_in is None or sku_prefix is None:
            if parse_error is not None:
                return None, None, f"Could not read the production order file: {parse_error}"
            return None, None, "Fill in the Raw width/height and Product type overrides below, or choose a readable production order PDF."

        if self.swap_width_height.get():
            raw_width_in, raw_height_in = raw_height_in, raw_width_in

        meta = {
            "po_number": parsed["po_number"] if parsed else None,
            "so_number": parsed["so_number"] if parsed else None,
            "sku": parsed["sku"] if parsed else sku_prefix,
            "sku_prefix": sku_prefix,
            "item_name": parsed["item_name"] if parsed else "",
            "raw_width_in": raw_width_in,
            "raw_height_in": raw_height_in,
        }
        return meta, engine.PROFILES.get(sku_prefix), None

    def preview(self):
        if not self.production_order_path.get() and not (
            self.raw_width.get().strip() and self.raw_height.get().strip() and self.product_type_override.get().strip()
        ):
            self.preview_text.set("Choose the production order PDF first (or fill in the manual overrides below).")
            return
        meta, profile, error = self._resolve_production_meta()
        if error:
            self.preview_text.set(f"⚠ {error}")
            return
        lines = []
        if meta["po_number"]:
            lines.append(f"PO {meta['po_number']}  /  SO {meta['so_number']}")
        if meta["item_name"]:
            lines.append(f"Item: {meta['item_name']} ({meta['sku']})")
        if not lines:
            lines.append("(manual entry — production order file couldn't be read)")
        lines.append(f"Raw size: {meta['raw_width_in']}\" x {meta['raw_height_in']}\"")
        if profile:
            lines[0] = f"{profile['name']}  —  " + lines[0]
            try:
                curb = float(self.curb_depth.get().strip() or "0")
            except ValueError:
                curb = engine.DEFAULT_CURB_DEPTH_IN
            double_curb = profile.get("curb_affects_height") and self.curb_affects_width.get()
            oversize_w = (meta["raw_width_in"] - curb + 1) if double_curb else meta["raw_width_in"] + 1
            if profile.get("curb_affects_height"):
                oversize_h = meta["raw_height_in"] - curb + 1
                curb_note = "width and height use" if double_curb else "height uses"
                lines.append(f"Oversize: {oversize_w}\" x {oversize_h}\"  ({curb_note} curb depth {curb}\")")
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

    def _validate_and_prepare(self):
        """Shared setup for Generate and Edit-before-generating. Returns a
        dict of everything needed, or None (after showing an error)."""
        order_form = self.order_form_path.get()
        production_order = self.production_order_path.get()
        material = self.material.get().strip()
        thickness = self.thickness.get().strip() or None
        out_dir = self.out_dir.get().strip()
        try:
            curb_depth = float(self.curb_depth.get().strip() or "0")
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

        meta, profile, error = self._resolve_production_meta()
        if error:
            messagebox.showerror("Couldn't read production order", error)
            return None
        if not profile:
            messagebox.showerror(
                "Unknown product",
                f"No annotation layout yet for SKU prefix '{meta['sku_prefix']}'. Send a sample form for this product line.",
            )
            return None

        oversize_w = (meta["raw_width_in"] - curb_depth + 1) \
            if (profile.get("curb_affects_height") and self.curb_affects_width.get()) \
            else meta["raw_width_in"] + 1
        if profile.get("curb_affects_height"):
            oversize_h = meta["raw_height_in"] - curb_depth + 1
        else:
            oversize_h = meta["raw_height_in"] + 1
        wide_origin = "bracket_wide" in profile and meta["raw_width_in"] > engine.WIDE_PANEL_THRESHOLD_IN

        typed_name = self.out_name.get().strip()
        if typed_name:
            out_name = typed_name if typed_name.lower().endswith(".pdf") else typed_name + ".pdf"
        elif meta["po_number"] and meta["so_number"]:
            out_name = f"{meta['po_number']}-{meta['so_number']}.pdf"
        else:
            out_name = Path(order_form).stem + "-markup.pdf"
        out_path = str(Path(out_dir) / out_name)

        return {
            "order_form": order_form, "production_order": production_order,
            "material": material, "thickness": thickness or "", "curb_depth": curb_depth,
            "meta": meta, "profile": profile, "oversize_w": oversize_w, "oversize_h": oversize_h,
            "wide_origin": wide_origin, "out_path": out_path,
        }

    def open_recent_order(self, entry):
        """Reopen a previously generated order (File > Recent Orders) with
        its full markup restored -- dragged item positions, brackets, notes,
        cut line, background rotate/resize -- so a single quick change (e.g.
        a corrected dimension) doesn't require re-marking the whole drawing
        up from scratch."""
        order_form = entry.get("order_form_path", "")
        production_order = entry.get("production_order_path", "")
        if not order_form or not os.path.isfile(order_form):
            messagebox.showerror(
                "File missing",
                f"Can't find the order form for this recent order:\n\n{order_form}\n\n"
                "It may have been moved, renamed, or deleted."
            )
            return
        if not production_order or not os.path.isfile(production_order):
            messagebox.showerror(
                "File missing",
                f"Can't find the production order for this recent order:\n\n{production_order}\n\n"
                "It may have been moved, renamed, or deleted."
            )
            return

        if self._preview_after_id is not None:
            self.after_cancel(self._preview_after_id)
            self._preview_after_id = None

        layout_state = entry.get("layout") or {}
        brackets = [
            {"offset": tuple(b.get("offset", (0.0, 0.0))), "rotation": b.get("rotation", 0)}
            for b in layout_state.get("brackets") or [{"offset": (0.0, 0.0), "rotation": 0}]
        ]
        self._pending_restore_state = {
            "items": layout_state.get("items", []),
            "brackets": brackets,
            "bar_offset": tuple(layout_state.get("bar_offset", (0.0, 0.0))),
            "has_cut_line": layout_state.get("has_cut_line", False),
            "bg_rotation": layout_state.get("bg_rotation", 0),
            "bg_scale": layout_state.get("bg_scale", 1.0),
        }
        # force a full reload through load_new_order() (rather than the
        # lighter sync() path) even if these happen to be the same two files
        # already showing, so restore_state is actually applied
        self._loaded_signature = None

        self.material.set(entry.get("material", ""))
        self.thickness.set(entry.get("thickness", ""))
        self.drain_a.set(entry.get("drain_a", ""))
        self.curb_depth.set(entry.get("curb_depth", ""))
        self.curb_affects_width.set(entry.get("curb_affects_width", False))
        self.keyhole_linear.set(entry.get("keyhole_linear", False))
        self.swap_width_height.set(entry.get("swap_width_height", False))
        self.raw_width.set(entry.get("raw_width", ""))
        self.raw_height.set(entry.get("raw_height", ""))
        self.product_type_override.set(entry.get("product_type_override", ""))
        self.out_name.set(entry.get("out_name", ""))
        if entry.get("out_dir"):
            self.out_dir.set(entry["out_dir"])
        self.order_form_path.set(order_form)
        self.production_order_path.set(production_order)
        self.status.config(
            text=f"Reopened {entry.get('label', '')} — markup restored. Make your change and click Generate to update it.",
            foreground="#0a7d2c",
        )

    def start_new_order(self):
        """Clear everything specific to the order just finished so the next
        one can be started fresh, without relaunching the app. The default
        output folder (out_dir) is intentionally left alone -- that's a
        persistent per-computer setting, not per-order data."""
        if self._preview_after_id is not None:
            self.after_cancel(self._preview_after_id)
            self._preview_after_id = None
        self.order_form_path.set("")
        self.production_order_path.set("")
        self.material.set("")
        self.thickness.set("")
        self.drain_a.set("")
        self.raw_width.set("")
        self.raw_height.set("")
        self.product_type_override.set("")
        self.curb_depth.set("")
        self.curb_affects_width.set(False)
        self.keyhole_linear.set(False)
        self.swap_width_height.set(False)
        self.out_name.set("")
        self._last_auto_thickness = None
        self._autoread_attempted_for = None
        self._last_auto_outname = None
        self._last_auto_raw_width = None
        self._last_auto_raw_height = None
        self._loaded_signature = None
        self.preview_text.set("Choose both files, then click Preview.")
        self.status.config(text="", foreground="#0a7d2c")
        self.layout.show_placeholder("Load an order form to see it here")

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

        # Ask where to save every time, pre-filled with the usual default
        # folder + suggested name, rather than silently writing there --
        # lets you redirect a specific order without having to change the
        # default folder first. Cancelling the dialog cancels Generate too,
        # same as any normal Save As.
        chosen_path = filedialog.asksaveasfilename(
            title="Save production markup as",
            initialdir=str(Path(ctx["out_path"]).parent),
            initialfile=Path(ctx["out_path"]).name,
            defaultextension=".pdf",
            filetypes=[("PDF", "*.pdf")],
        )
        if not chosen_path:
            return
        ctx["out_path"] = chosen_path
        self.out_dir.set(str(Path(chosen_path).parent))
        self.out_name.set(Path(chosen_path).name)
        # remembered as the next dialog's starting folder, both this
        # session (self.out_dir above) and future launches -- replaces the
        # old explicit "Set as default" button now that every save already
        # goes through this dialog
        engine.set_default_output_dir(str(Path(chosen_path).parent))

        self.status.config(text="Working…", foreground="#555")
        self.update_idletasks()

        # use whatever's currently in the live layout (including any drags,
        # edits, notes, or a cut-for-shipping line) if it matches this exact
        # order; otherwise fall back to fresh default positions
        matches = self.layout.matches(ctx["order_form"], ctx["production_order"])
        # Always normalized to a portrait PAGE_W x PAGE_H page (see
        # normalize_to_portrait_page()) even with no manual rotate/resize --
        # only overridden below if bg_rotation/bg_scale add something on top.
        order_form_for_merge = engine.get_transformed_order_form(ctx["order_form"])
        if matches:
            items = self.layout.get_items()
            oversize_w = self.layout.oversize_w  # includes the cut-for-shipping bump, if present
            wide_origin = self.layout.wide_origin
            brackets = self.layout.get_brackets()  # manual nudge(s)/rotation(s) from the live preview, if any
            bar_offset = self.layout.get_bar_offset()  # manual nudge for the Traveler bar, if any
            page_rotation = self.layout.bg_rotation
            if self.layout.bg_rotation or abs(self.layout.bg_scale - 1.0) > 0.001:
                order_form_for_merge = engine.get_transformed_order_form(
                    ctx["order_form"], self.layout.bg_rotation, self.layout.bg_scale)
            if self.layout.bg_rotation:
                # Rotating the background swaps its width/height -- without
                # also rotating the overlay's own coordinates to match,
                # merge_pdf()'s canonical->real scaling has to squash it
                # non-uniformly to fit, visibly stretching the dimension
                # text/lines (the background itself doesn't stretch since
                # it's rotated as a proper image, not just scaled).
                items, brackets = engine.rotate_overlay_for_page(
                    ctx["profile"], wide_origin, items, brackets, self.layout.bg_rotation)
        else:
            items = engine.compute_default_items(ctx["profile"], ctx["oversize_w"], ctx["oversize_h"],
                                                   thickness=ctx["thickness"])
            oversize_w = ctx["oversize_w"]
            wide_origin = ctx["wide_origin"]
            brackets = [{"offset": (0.0, 0.0), "rotation": 0}]
            bar_offset = (0.0, 0.0)
            page_rotation = 0
        try:
            overlay_bytes, overlay_min_x, overlay_min_y = engine.render_page(
                ctx["profile"], ctx["material"], items, wide_origin=wide_origin,
                brackets=brackets, bar_offset=bar_offset, page_rotation=page_rotation)
            engine.merge_pdf(order_form_for_merge, ctx["production_order"], overlay_bytes, ctx["out_path"],
                              min_x=overlay_min_x, min_y=overlay_min_y)
        except Exception as e:
            traceback.print_exc()
            messagebox.showerror("Failed", str(e))
            self.status.config(text="Failed — see message.", foreground="#b00020")
            return

        # remember this order (inputs + the exact markup just exported) so
        # it can be reopened later from File > Recent Orders for a quick
        # single-field change without re-marking the whole drawing up again
        try:
            recent_entry = {
                "label": Path(ctx["out_path"]).stem,
                "timestamp": datetime.now().isoformat(timespec="seconds"),
                "order_form_path": ctx["order_form"],
                "production_order_path": ctx["production_order"],
                "material": ctx["material"],
                "thickness": ctx["thickness"],
                "drain_a": self.drain_a.get().strip(),
                "curb_depth": self.curb_depth.get().strip(),
                "curb_affects_width": self.curb_affects_width.get(),
                "keyhole_linear": self.keyhole_linear.get(),
                "swap_width_height": self.swap_width_height.get(),
                "raw_width": self.raw_width.get().strip(),
                "raw_height": self.raw_height.get().strip(),
                "product_type_override": self.product_type_override.get().strip(),
                "out_name": Path(ctx["out_path"]).name,
                "out_dir": str(Path(ctx["out_path"]).parent),
                "layout": {
                    "items": items,
                    "brackets": brackets,
                    "bar_offset": list(bar_offset),
                    "has_cut_line": self.layout.has_cut_line if matches else False,
                    "bg_rotation": self.layout.bg_rotation if matches else 0,
                    "bg_scale": self.layout.bg_scale if matches else 1.0,
                },
            }
            engine.save_recent_order(recent_entry)
            if self.on_recent_orders_changed:
                self.on_recent_orders_changed()
        except Exception:
            traceback.print_exc()  # non-critical -- never block a successful export over this

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


def _install_entry_context_menu(root):
    """Right-click Cut/Copy/Paste/Select All for every text-entry widget in
    the app (ttk.Entry, ttk.Combobox's internal entry, and the plain
    tk.Entry inside simpledialog.askstring dialogs). macOS's native Aqua
    text fields get this for free; Windows Tk does not, so right-click did
    nothing there. Scoped to non-Mac only so it can't interfere with
    whatever Mac already provides."""
    if platform.system() == "Darwin":
        return

    menu = tk.Menu(root, tearoff=0)

    def _do(virtual_event):
        widget = root.focus_get()
        if widget is not None:
            widget.event_generate(virtual_event)

    def _select_all():
        widget = root.focus_get()
        if widget is not None:
            try:
                widget.selection_range(0, tk.END)
            except tk.TclError:
                pass

    menu.add_command(label="Cut", command=lambda: _do("<<Cut>>"))
    menu.add_command(label="Copy", command=lambda: _do("<<Copy>>"))
    menu.add_command(label="Paste", command=lambda: _do("<<Paste>>"))
    menu.add_separator()
    menu.add_command(label="Select All", command=_select_all)

    def show_menu(event):
        event.widget.focus_set()
        menu.tk_popup(event.x_root, event.y_root)
        return "break"

    for cls in ("TEntry", "TCombobox", "Entry"):
        root.bind_class(cls, "<Button-3>", show_menu)


def main():
    global DND_AVAILABLE
    root = None
    if DND_AVAILABLE:
        try:
            root = TkinterDnD.Tk()
        except Exception:
            # tkinterdnd2's bundled tkdnd binary can fail to load at runtime
            # (e.g. Tcl version mismatch when frozen by PyInstaller) even
            # though the import itself succeeded — fall back like a missing
            # install.
            DND_AVAILABLE = False
    if root is None:
        root = tk.Tk()
    root.title("KBRS Production Markup")
    root.geometry("1360x900")
    root.minsize(1000, 600)
    _install_entry_context_menu(root)

    ACCENT_PRESETS = [
        ("Orange", "#f2842f"),
        ("Blue", "#91afda"),
        ("Green", "#84bf78"),
        ("Pink", "#e282af"),
    ]

    def apply_accent_color(hex_code):
        # This install's accent color (default orange) for every measurement
        # overlay -- lets different computers running this app be set to a
        # different color, e.g. to tell whose copy generated a sheet.
        engine.set_accent_color(hex_code)
        ITEM_COLOR_HEX["orange"] = hex_code
        messagebox.showinfo(
            "Accent color saved",
            "Saved for this computer. It'll apply the next time you load or refresh a preview.",
        )

    def pick_accent_color():
        dlg = tk.Toplevel(root)
        dlg.title("Choose accent color")
        dlg.resizable(False, False)
        ttk.Label(dlg, text="This computer's accent color for measurement overlays:").pack(padx=14, pady=(14, 6))
        swatches = ttk.Frame(dlg)
        swatches.pack(padx=14)
        for name, hex_code in ACCENT_PRESETS:
            tk.Button(
                swatches, text=name, bg=hex_code, fg="black", width=8, relief="raised",
                command=lambda h=hex_code: (apply_accent_color(h), dlg.destroy()),
            ).pack(side="left", padx=4)

        def custom():
            _rgb, hex_code = colorchooser.askcolor(color=ITEM_COLOR_HEX["orange"], title="Choose a custom accent color", parent=dlg)
            if hex_code:
                apply_accent_color(hex_code)
                dlg.destroy()

        ttk.Button(dlg, text="Custom color…", command=custom).pack(pady=14)

    top_bar = ttk.Frame(root)
    top_bar.pack(fill="x", padx=8, pady=(6, 0))
    ttk.Button(top_bar, text="Accent color…", command=pick_accent_color).pack(side="right")

    # -- self-update (Windows packaged build only; a no-op everywhere else,
    # including this Mac dev build) -------------------------------------
    update_btn = ttk.Button(top_bar, text="")
    _pending_update_sha = {"sha": None}

    def _do_update():
        sha = _pending_update_sha["sha"]
        if not sha:
            return
        if not messagebox.askyesno(
            "Update available",
            f"A newer version is available (build {sha[:7]}).\n\n"
            "Download and install it now? The app will close and reopen "
            "automatically once it's done.",
        ):
            return
        update_btn.config(text="Downloading update…", state="disabled")
        root.update_idletasks()

        def worker():
            try:
                def progress(read, total):
                    if total > 0:
                        pct = int(read * 100 / total)
                        root.after(0, lambda: update_btn.config(text=f"Downloading update… {pct}%"))
                zip_path = engine.download_update(progress_cb=progress)
                root.after(0, lambda: update_btn.config(text="Installing update…"))
                staged_dir = engine.stage_update(zip_path)
            except Exception as e:
                traceback.print_exc()
                root.after(0, lambda: (
                    update_btn.config(text="🔄 Update available", state="normal"),
                    messagebox.showerror(
                        "Update failed",
                        f"Couldn't download/prepare the update ({type(e).__name__}: {e}).\n\n"
                        "The app hasn't been changed -- you can try again, or download it "
                        "manually from the usual GitHub Releases link.",
                    ),
                ))
                return
            # apply_update_and_relaunch() exits the process itself -- nothing
            # after this call runs (or needs to)
            engine.apply_update_and_relaunch(staged_dir)

        threading.Thread(target=worker, daemon=True).start()

    update_btn.config(command=_do_update)

    def _check_for_update_async(silent=True):
        if not engine.is_frozen_windows_build():
            return

        def worker():
            try:
                sha = engine.check_for_update()
            except engine.UpdateCheckError as e:
                # A failed check is NOT the same as "up to date" -- silently
                # treating it that way is exactly how a real network problem
                # once got reported as "you're current" when it wasn't.
                # Quiet on the automatic launch-time check (don't nag every
                # startup over a transient network blip); loud when someone
                # explicitly asked via File > Check for Updates, since they
                # need to know the check itself didn't work.
                if not silent:
                    root.after(0, lambda: messagebox.showerror(
                        "Couldn't check for updates",
                        "The update check itself failed, so this does NOT mean "
                        "you're up to date -- it just couldn't reach the update server:\n\n"
                        f"{e}\n\n"
                        "Check your internet connection and try again, or download "
                        "manually from the usual GitHub Releases link."
                    ))
                return
            if sha:
                def show():
                    _pending_update_sha["sha"] = sha
                    update_btn.config(text="🔄 Update available")
                    update_btn.pack(side="left")
                root.after(0, show)
            elif not silent:
                root.after(0, lambda: messagebox.showinfo("Up to date", "You're already on the latest version."))

        threading.Thread(target=worker, daemon=True).start()

    _check_for_update_async(silent=True)  # on launch, quiet if already current

    tab = SingleOrderTab(root)
    tab.pack(fill="both", expand=True)

    # File > Recent Orders -- reopen any of the last MAX_RECENT_ORDERS
    # generated orders with its full markup restored, for a quick edit.
    menubar = tk.Menu(root)
    root.config(menu=menubar)
    file_menu = tk.Menu(menubar, tearoff=0)
    menubar.add_cascade(label="File", menu=file_menu)
    recent_menu = tk.Menu(file_menu, tearoff=0)
    file_menu.add_cascade(label="Recent Orders", menu=recent_menu)
    if engine.is_frozen_windows_build():
        file_menu.add_separator()
        file_menu.add_command(label="Check for Updates…", command=lambda: _check_for_update_async(silent=False))

    def refresh_recent_menu():
        recent_menu.delete(0, "end")
        entries = engine.get_recent_orders()
        if not entries:
            recent_menu.add_command(label="(no recent orders yet)", state="disabled")
            return
        for entry in entries:
            label = entry.get("label") or "(untitled)"
            ts_display = ""
            try:
                # %-d/%-I (no leading zero) are Linux/macOS-only strftime
                # extensions and would raise on Windows -- %d/%I plus a
                # manual lstrip keeps this portable for the Windows build.
                dt = datetime.fromisoformat(entry["timestamp"])
                ts_display = "  —  " + dt.strftime("%b ") + dt.strftime("%d").lstrip("0") \
                    + dt.strftime(", %I:%M %p").replace(", 0", ", ")
            except (KeyError, ValueError):
                pass
            recent_menu.add_command(label=f"{label}{ts_display}", command=lambda e=entry: tab.open_recent_order(e))
        recent_menu.add_separator()

        def clear():
            if messagebox.askyesno("Clear recent orders", "Remove all entries from the recent-orders list?"):
                engine.clear_recent_orders()
                refresh_recent_menu()

        recent_menu.add_command(label="Clear recent orders", command=clear)

    tab.on_recent_orders_changed = refresh_recent_menu
    refresh_recent_menu()

    if not DND_AVAILABLE:
        ttk.Label(
            root,
            text="Drag & drop isn't available (tkinterdnd2 not installed) — use the Browse buttons instead.",
            foreground="#b00020",
        ).pack(pady=(0, 6))

    root.mainloop()


if __name__ == "__main__":
    main()
