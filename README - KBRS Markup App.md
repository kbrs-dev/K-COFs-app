# KBRS Production Markup App

Turns your two per-order PDFs (customer order form + KBRS production order) into
the finished, annotated production sheet — no PowerPoint, no manual dragging.

## Cost

$0. Everything here is free and runs on your own computer (Mac or Windows):
- Python (free, from python.org — you likely already have it)
- tkinter, reportlab, pypdf, Pillow, tkinterdnd2, pypdfium2, pikepdf, numpy (free, open-source libraries)

No subscriptions, no accounts, no API keys.

## Using this on more than one computer (GitHub)

This app lives in a private GitHub repo (`kbrs-dev/K-COFs-app`) so it can stay in sync across
multiple computers — for example, doing updates on a Mac and running the app on one or more
Windows machines. **GitHub Desktop** (free, no command line) is the easiest way to handle this:

- **On the computer where updates happen:** open GitHub Desktop → File → Add Local Repository →
  select this folder. After any update, GitHub Desktop shows the changed files — write a short
  summary and click **Commit**, then **Push origin** to send it up to GitHub.
- **On every other computer that just needs to run the app:** open GitHub Desktop → File → Clone
  Repository → paste `https://github.com/kbrs-dev/K-COFs-app.git` → pick a folder → Clone. That's
  the one-time setup per computer.
- **Every time you open the app**, the launcher (`KBRS Markup.command` on Mac, `KBRS Markup.bat`
  on Windows) automatically runs `git pull` first, so you always get the latest version without
  touching GitHub Desktop yourself — it only asks you to do anything when you're the one making
  changes, not when you're just using the app.

## First-time setup (one time only, per computer)

**Mac:**
1. Check you have Python 3: open Terminal and type `python3 --version`.
   If it's missing, get it free at https://www.python.org/downloads/
2. Double-click **KBRS Markup.command**.
   - The first time, macOS will say "Apple could not verify this app." Right-click
     (or Control-click) the file → **Open** → **Open** again. You only do this once.
   - The launcher auto-installs the free libraries it needs the first run
     (PDF handling, drag-and-drop, and the layout editor's PDF preview).

**Windows:**
1. Install Python 3 from https://www.python.org/downloads/ — on the install screen, **check the
   box that says "Add python.exe to PATH"** before clicking Install (easy to miss, and the
   launcher won't find Python without it). Make sure "tcl/tk and IDLE" stays checked too (it's
   on by default) — that's what tkinter needs.
2. Double-click **KBRS Markup.bat**.
   - Windows may show a "Windows protected your PC" SmartScreen prompt the first time — click
     "More info" → "Run anyway." You only do this once.
   - The launcher auto-installs the same free libraries the Mac version does.

## Using it

**Single order tab:** drop the customer order form onto the big box (or click
it to browse) -- it can be a PDF **or a photo/scan (JPG, PNG, TIFF, BMP)**,
whichever you have on hand. Drop the KBRS production order PDF onto the
second box (that one's always a real PDF from KBRS's system). Pick a
**Traveler** (dropdown of GRAY/GREEN/BLUE/RED TRAVELER, or type a new one),
optionally set drain dimension A/thickness/curb depth.

**File name to save as:** auto-suggested from the PO/SO numbers as soon as
the production order is read (e.g. `PO247946-SO243810`) — paste or type
over it any time to save under a different name; ".pdf" is added
automatically if you leave it off.

The right-hand panel is the **live preview and editor in one** — as soon as
both files are read, it shows the real order form with the material bar,
origin bracket, and every dimension/thickness annotation on top, updating
automatically as you type. You can edit right there before generating (see
below). When it looks right, click **Generate**. The status line reports the
file it saved and confirms both pages are present with page 2 rotated
correctly (flags it clearly if something's off, instead of a silent "Done").

**Batch tab:** for a folder of many orders at once.
1. Name your files so each pair shares the PO number, e.g.
   `PO247946_orderform.pdf` and `PO247946_production.pdf`
2. Click **Create manifest template from folder…** — scans the folder and builds
   a `manifest.csv` listing every PO number found, with columns: `po_number`,
   `material`, `thickness`, `curb_depth`.
3. Open that CSV and fill in `material` for each order (required). Leave
   `thickness`/`curb_depth` blank to use the product's default, or fill in a
   value to override.
4. Pick an output folder, click **Run batch**. Progress and any skipped/failed
   orders show in the log at the bottom. Batch mode always uses default
   positions (no editor step — that's single-order only).

## The live preview / editor panel

This is the same panel — there's no separate popup window anymore. Once it
loads an order, every dimension/thickness label is draggable right there:

- **Drag** any dimension/thickness text to move it.
- **Right-click** an item → Edit text, or Delete (dimension labels can be
  moved but not deleted; notes and the cut line can be both).
- **Add cut-for-shipping line** — adds a draggable dashed vertical line +
  "Cut for shipping" label for oversized panels that need a field cut to
  ship. There's no fixed rule for where the cut goes, so you place it by
  hand each time. Adding it automatically bumps the width oversize by an
  extra 0.5" (confirmed: raw + 1.5" total instead of the usual raw + 1"
  whenever a shipping cut is present). Click again to remove it (reverts
  the width bump too).
- **Add note** — freeform text anywhere, for anything not covered above.
- **Add diagonal line** — a plain solid indicator line (not dashed, unlike
  the cut-for-shipping line above), for flagging a diagonal cut or angled
  feature on the drawing. Purely a visual marker — it never changes any
  oversize dimension, and isn't tied to any particular product type. Starts
  at 45°; drag it like any other item, and **right-click → "Rotate 45°"**
  to spin it in place. Click the toolbar button again to add another one if
  you need more than one. Right-click → Delete to remove.
- **Undo / Redo** — buttons in the toolbar, or ⌘Z / ⇧⌘Z (Ctrl+Z / Ctrl+Shift+Z
  on Windows) while the preview has focus. Covers moves, deletes, text
  edits, notes, diagonal lines, and the cut line — use it freely; nothing is
  final until you click Generate.
- **Drag the origin bracket** (the orange corner marker) to nudge it if the
  calibrated position doesn't match a real order — useful when a product's
  default rule doesn't fit a specific drain layout. **Right-click it** for
  "Rotate 90°" (spins the bracket's arms in place, for when the corner
  orientation itself is wrong, not just its position) or "Reset origin
  position" (clears both the drag and any rotation back to the calibrated
  default). The bracket turns pink while it's been manually adjusted, so
  it's obvious at a glance that it's off the calibrated default.
- **Right-click the drawing itself** (not an item) for "Rotate drawing 90°",
  "Make drawing bigger/smaller", and "Darken lines/text (+contrast)" — useful
  for a source that's awkward after the automatic normalization, or (the
  contrast option) a faint CAD/CAM export like Aspire's PDF output or a
  washed-out scan where the lines and printed measurements are hard to read.
  Contrast only ever darkens (never lightens past the original), each click
  applies another notch, and "Reset drawing rotation/size/contrast" clears
  all three back to normal. This is baked into the final PDF the same way a
  rotate/resize is — it changes how the customer's drawing itself prints,
  not just the live preview.
- **A large-format CAM/CAD export (e.g. Aspire, sized to the actual physical
  part rather than a normal Letter page) also gets its thin lines
  automatically thickened**, always, even without touching the contrast
  control — those exports typically use a "hairline" stroke width that
  stays a fixed 1 pixel wide no matter the color, so on a source shrunk way
  down to fit the small page, recoloring the lines darker in Aspire alone
  won't make them print any thicker. No action needed; it only kicks in for
  a source that actually needs it (a normal Letter-ish scan is unaffected).
- Editing here, then changing the material/thickness/curb-depth fields on
  the left, keeps your edits — only picking a *different* order form/production
  order resets the layout back to defaults.
- **Generate** (left panel) bakes whatever's currently shown in the preview
  into the final PDF.

**Auto-shrink-to-fit:** the material bar (and anything else) can be dragged
anywhere, including below or beside the drawing — but the drawing normally
fills the whole page, so dragging something below it would otherwise push
it past the actual edge of the physical page, where it simply can't print.
Generate checks for this automatically: if anything ends up outside the
real printable page, the whole page's content (the drawing itself and
every item on it, together, so they stay lined up with each other) is
shrunk down just enough to make room and fit it back in — the status line
after Generate says so and by how much when this happens. It's a rare
case in practice (only when something is deliberately dragged well outside
the drawing's normal area), and doesn't need any action from you — just
check the result looks right, same as any manual drag.

The origin bracket's default position is still rule-driven (see below) —
dragging it is a manual override for a specific order, not a change to the
underlying rule. Use it when an order's real drain layout doesn't match the
calibrated default.

## What's covered right now

Five product lines, each calibrated from one real finished example:

| SKU prefix | Product | Thickness shown? | Curb affects height? |
|---|---|---|---|
| CLSS | Custom Linear ShowerSlope | Yes (varies, no safe default) | No |
| CSS | Custom ShowerSlope (point drain) | No calibrated spot yet — will warn if entered | No |
| CLTB | Custom Linear Tile-Basin | Yes (varies, no safe default) | Yes |
| CTB | Custom Tile-Basin (point drain) | No calibrated spot yet — will warn if entered | Yes |
| CFSRC | Custom Flanged SRC | Yes, always 1.5" per KBRS (type it in — no auto-fill) | No |

## A brand new product line with no calibrated layout yet (e.g. Vanity Vessels)

Load an order form + production order for a product that isn't one of the
five above (or whose production order doesn't even follow the usual
"SKU-CODE: name (WxH)" text format, like a Custom Vanity Vessel) and the app
still loads the order form as the background — it just skips the automatic
material bar, origin bracket, and dimension callouts, since there's no
calibrated position for any of them yet. **Add note** and **Add cut-for-shipping
line** still work in this mode (neither needs a calibrated position), so you
can mark up the order entirely by hand — drag notes wherever they need to go,
type in the measurements/material/whatever else the order needs. Clicking
**Generate** bakes exactly what's in the preview onto the order form, and the
status line flags that it was manual-only so it's never mistaken for a fully
calibrated export. Send a sample blank order form + a finished markup for the
product and I'll add it as a real calibrated profile.

Thickness works on any product with a calibrated position; default is always
blank (nothing shown unless you type something in). To add a thickness spot
for CSS/CTB, or a whole new product line, send a sample order form + finished
markup PDF and I'll calibrate it.

## Auto-calculated thickness for Linear products (CLSS, CLTB)

Field 4, "Drain dimension A," drives an automatic thickness calculation for
Linear ShowerSlope and Linear Tile-Basin, per KBRS's reference formula:

    thickness = ceil( (1.25" + 2% x (raw width - A)) / 0.5" ) x 0.5"

(1.25" drain height, 2% slope grade, rounded up to the nearest half inch.)

Enter "A" from the order form's own "A" field and the Thickness field fills
in automatically — still fully editable if a real order needs an exception.
The app also tries to auto-read "A" straight off the order form first, but
that only works on the rare form that has a real text layer; most order
forms (PDF or photo) are flattened scans with no extractable text, so
typing "A" in by hand is the normal path.

## Dimension rules

- **Oversize width** = raw width + 1" for every product line, or **+1.5"**
  if a cut-for-shipping line is present (added via the editor).
- **Oversize height**:
  - ShowerSlope (CLSS, CSS) and SRC (CFSRC): raw height + 1"
  - Tile-Basin (CLTB, CTB): raw height − curb depth + 1" (curb depth defaults
    to 4" for HardCurb — override in the app if a different curb type/depth
    applies to that order)

## Material bar color

The colored bar behind the material name is derived from the color word in
the material name itself — confirmed working for GRAY, GREEN, and BLUE from
real examples; RED added on request. Other colors (black, white, beige, tan,
brown, taupe) are best-effort guesses not yet confirmed against a real
example — flag it if one looks wrong and I'll fix the color.

## Wide-panel origin rule (Linear ShowerSlope only, so far)

Drain is normally on the right, and the origin bracket marks the top-right
corner of the diagram. For raw widths over 85", the app automatically moves
the origin bracket to the bottom-left corner instead — **confirmed exact**
against a real 101.5"-wide example, not a guess. This rule is currently
applied only to Linear ShowerSlope (CLSS) — not yet extended to Linear
Tile-Basin or SRC; ask if those need the same treatment.

## Files in this folder

- `app.py` — the app window (run via the .command launcher, or `python3 app.py`)
- `kbrs_markup.py` — the underlying engine (also usable from Terminal directly,
  see the comment at the top of that file for command-line usage)
- `KBRS Markup.command` — double-click launcher
