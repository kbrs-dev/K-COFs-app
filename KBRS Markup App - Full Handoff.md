# KBRS Markup App — Full Handoff

**Purpose of this file:** Upload to Project Knowledge in the new Claude account/project. Read this
first — it covers the app's architecture, every real bug fixed and why, and the current open
items, so a new session doesn't have to re-derive any of it.

**Compiled:** 2026-07-24.

---

## 1. What this is

A free, local desktop app (Python/Tkinter, runs on the user's own Mac, no subscriptions/accounts)
that takes two per-order PDFs — the customer's shower-pan order form and KBRS's own auto-generated
production order — and merges them into one finished, annotated 2-page production sheet:

- **Page 1:** the customer's order form, with an orange "oversize dimensions" overlay (width,
  length, thickness where applicable), a colored material/"Traveler" bar, and the CNC/CAD origin
  reference bracket.
- **Page 2:** KBRS's production order, rotated 90° (confirmed correct via raw PDF byte inspection
  and `qpdf --show-pages`, not just pypdf's object model — this was double-checked because it was
  reported as missing/wrong twice and both times turned out to be a stale-running-process issue,
  not a real bug).

This is a completely separate tool from the Shopify configurator project — no shared code, but
same underlying domain (KBRS custom shower pans) and the same production-floor stakes (wrong
numbers here mean a wrong CNC cut, not just a wrong price).

## 2. Where it lives / how it runs

- **Location:** `/Users/imacpro/Documents/KBRS Markup App/` on the user's Mac — a real local
  folder, not a Chrome/cloud workflow (unlike the configurator project).
- **Files:** `app.py` (GUI), `kbrs_markup.py` (engine, also usable standalone from Terminal),
  `KBRS Markup.command` (double-click launcher), `README - KBRS Markup App.md` (user-facing usage
  doc — keep this in sync with any UI change).
- **Launch:** double-click `KBRS Markup.command`. First run auto-installs `reportlab`, `pypdf`,
  `Pillow`, `tkinterdnd2`, `pypdfium2` via pip if missing.
- **Critical constraint for any Claude session working on this:** the typical sandboxed dev
  environment (including this one) **has no `tkinter` module at all**, so `app.py` can never be
  imported or run directly there. Validate with `python3 -m py_compile app.py kbrs_markup.py`,
  test `kbrs_markup.py`'s logic headlessly (it has no tkinter dependency), reimplement
  app.py-specific algorithms standalone for testing when needed, and do visual spot-checks by
  rendering generated PDFs to PNG. Never claim something works in the live GUI without the user
  actually running it on their Mac.

## 3. Architecture

### Engine (`kbrs_markup.py`)

- **`PROFILES` dict** — one entry per product SKU prefix, each calibrated from a real finished
  example: exact PDF-point coordinates (reportlab space, origin bottom-left) for the width/length/
  thickness cover boxes and text positions, the material bar rectangle, the origin bracket's 3-point
  polyline, and per-product font sizes. Currently covers `CLSS`, `CSS`, `CLTB`, `CTB`, `CFSRC`.
  Thickness has no calibrated spot yet for `CSS`/`CTB` (warns and skips rather than guessing).
- **`ensure_pdf(path)`** — converts JPG/PNG/TIFF/BMP/GIF order-form scans into a Letter-size PDF by
  stretching the image to fill the page exactly (matches how real KBRS order form PDFs are
  themselves just one embedded full-page scan). Cached by `(mtime, converted_path)`.
- **Item-based rendering** — annotations (dimension text, thickness, notes, cut-line) are plain
  dicts with `kind` (`text`/`line`), position, font, color, and cover-box/deletable/editable flags,
  rendered by `render_page(profile, material, items, wide_origin, bracket_offset, bracket_rotation)`.
  This is what lets the live editor and the final PDF stay in sync — both just render the same item
  list.
- **`compute_default_items()`** — builds the default item list for an order from its parsed
  metadata; factored into small `make_height_item`/`make_width_item`/`make_thickness_item` helpers
  so the app's live editor can reuse the same thickness-item logic when a field changes.
- **Linear thickness auto-calc (CLSS and CLTB only):**
  `thickness = ceil((1.25 + 0.02 × (raw_width − drain_A)) / 0.5) × 0.5`, derived from KBRS's own
  reference chart and verified two ways: against the chart's own worked example (A=10, width=45 →
  2.0") and against its visual step-boundary tick marks. `try_extract_drain_a()` does a best-effort
  read of "A" from the order form's text layer (only works on the rare form that has one — most
  scans are flattened images with no text), otherwise the app's "Drain dimension A" field is manual.
- **Material bar sizing** — bar width = `max(calibrated_width, text_width + padding)`, computed via
  `stringWidth()` (reportlab). This exists because the calibrated bar was too narrow for a real
  label ("GRAY TRAVELER" at 205.3pt vs a 194.5pt calibrated bar) and text was rendering invisibly
  past the bar's edge.
- **Origin bracket** — a 3-point polyline (elbow + two arms) marking the CNC/CAD reference corner.
  Rule-driven by default (`profile["bracket"]`, or `profile["bracket_wide"]` for CLSS panels over
  85" wide — `WIDE_PANEL_THRESHOLD_IN`). As of this session, also supports a manual
  `bracket_offset` (dx, dy in PDF points) and `bracket_rotation` (0/90/180/270°, rotated around the
  elbow via the new `rotate_point()` helper) for cases where the calibrated default is wrong for a
  specific order. Both default to zero/no-op — automatic behavior is unchanged unless the user
  drags/rotates in the live editor.
- **Batch mode** (`main() --batch`): scans a folder for `{PO}_orderform.*` / `{PO}_production.pdf`
  pairs (any image extension for the order form, PDF-only for production), driven by a
  `manifest.csv` (po_number, material, thickness, curb_depth) the app can also auto-generate from a
  folder scan. Always uses default item positions — no live-editor step in batch mode.

### GUI (`app.py`)

- **`DropZone`** — large click-or-drag file target (replaced tiny drop targets after user feedback
  that they were hard to hit), validates the file on drop (`validate_order_form_path`/
  `validate_production_order_path`) and shows a friendly error instead of a cryptic pypdf
  exception.
- **`InteractiveLayout(ttk.Frame)`** — the live preview **and** editor, merged into one widget (an
  earlier separate `EditorWindow(tk.Toplevel)` popup was fully replaced after the user pointed out
  they wanted to edit in the same preview panel, not a separate popup). Key state: `items`,
  `bracket_offset`, `bracket_rotation`, `has_cut_line`, `undo_stack`/`redo_stack`. Key methods:
  `load_new_order(...)` (full reset — genuinely different order), `sync(...)` (same order, field
  tweak only — preserves manual edits/undo history), `matches(...)` (used by `generate()` to decide
  whether to use live-edited state or fresh defaults), `get_items()`, `get_bracket_offset()`,
  `get_bracket_rotation()`.
  - Every draggable item and the origin bracket support right-click context menus (edit text/
    delete for items; rotate/reset for the bracket).
  - Undo/redo is snapshot-based (`_snapshot()`/`_restore()`), one snapshot per drag gesture or
    before any mutating action, scoped to `⌘Z`/`⇧⌘Z` bound only on the canvas (not `bind_all`, to
    avoid hijacking normal text-field undo elsewhere in the window — this was a deliberate fix
    after almost shipping the global-bind version).
  - Canvas supports both scrollbar-drag and mousewheel/trackpad scrolling (`<MouseWheel>`,
    `<Shift-MouseWheel>`, `<Button-4>`/`<Button-5>` for cross-platform coverage) — mousewheel
    support was missing entirely until this session.
- **`SingleOrderTab`** fields, in order: order-form DropZone, production-order DropZone, Preview
  button, **Traveler** (material) combobox — deliberately renamed from "Material" per user
  request, drain dimension **A** entry (drives the linear thickness auto-calc), Thickness entry,
  Curb depth entry, **file name to save as** entry (auto-suggested from the parsed PO/SO numbers,
  e.g. `PO247946-SO243810`, fully overridable), output folder picker, Generate button, status line.
  The left panel is wrapped in a scrollable `Canvas`+`Scrollbar` (added after the growing field
  count pushed Generate off-screen with no way to reach it).
- **Override-respecting auto-fill pattern**, used for thickness, drain-A, and output filename: each
  tracks a `_last_auto_<field>` value and only auto-writes into the field if it's currently blank or
  still equal to what was last auto-written — never clobbers something the user typed/pasted
  themselves, and resumes auto-filling once the field is cleared.
- **`generate()`** re-runs the preview synchronously first (in case Generate is clicked faster than
  the 400ms debounce), decides live-edited vs. default items via `matches()`, calls
  `engine.render_page(...)` with the live `bracket_offset`/`bracket_rotation` if applicable, then
  **re-opens the saved file** via `PdfReader` to verify page count == 2 and page 2's `/Rotate == 90`,
  appending a warning to the status line instead of a blind "Done" if anything's off.

## 4. Product coverage matrix

| SKU prefix | Product | Thickness shown? | Curb affects height? | Wide-panel origin flip? |
|---|---|---|---|---|
| CLSS | Custom Linear ShowerSlope | Yes, auto-calc from drain A | No | Yes, >85" wide (confirmed real example) |
| CSS | Custom ShowerSlope (point drain) | No calibrated spot — warns | No | No |
| CLTB | Custom Linear Tile-Basin | Yes, auto-calc from drain A | Yes | No `bracket_wide` yet — see §5 |
| CTB | Custom Tile-Basin (point drain) | No calibrated spot — warns | Yes | No |
| CFSRC | Custom Flanged SRC | Yes, always 1.5" (typed in, no auto-fill) | No | No |

Dimension rules: oversize width = raw + 1" (or +1.5" if a cut-for-shipping line is added in the
editor — bumps automatically). Oversize height: ShowerSlope/SRC = raw + 1"; Tile-Basin = raw − curb
depth + 1" (curb depth defaults to 4" for HardCurb, overridable).

Material bar color is derived from the color word in the material name — confirmed against real
examples for GRAY, GREEN, BLUE; RED added on request. Other colors (black, white, beige, tan,
brown, taupe) are best-effort guesses, not yet confirmed against a real example.

## 5. Current open item — CLTB origin bracket calibration

The real-world trigger: a real CLTB order (PO247884-SO243737, drain visibly on the right,
raw width 54.125" — well under any width threshold) showed the origin bracket in the top-left area
of the diagram; the user says it should be bottom-left. The existing top-left calibration is
correct for *some* CLTB layout but not this one.

**Confirmed with the user (2026-07-24):** the rule should be — CLTB origin bracket = **always
bottom-left when the drain is on the right**, regardless of panel width (unlike CLSS, where the
flip only happens above the 85" width threshold). The user also explicitly wants to keep manual
drag *and* rotate available regardless, as a permanent escape hatch, not just a stopgap.

**What shipped this session (both engine and GUI sides, compiled and math-verified):**
- Origin bracket is now **draggable** (click-drag, turns pink while manually offset) and
  **rotatable** (right-click → "Rotate 90°," rotates the bracket's arms in place around its own
  elbow via exact-90°-multiple rotation, no float drift). Right-click → "Reset origin position"
  clears both. Both are undo/redo-safe and get baked into the final PDF via `bracket_offset`/
  `bracket_rotation` params threaded through `render_page()`.
- Verified numerically (not just visually): rotating the current CLTB `bracket` coordinate 90°
  converts it from its current top-left orientation (arms pointing right + down) into exactly the
  orientation confirmed correct for CLSS's real bottom-left example (arms pointing up + right) —
  same shape, just needs repositioning after the rotation.

**What's deliberately NOT done yet, and why:** the calibrated `PROFILES["CLTB"]["bracket"]`
coordinate itself was **not** changed to a guessed bottom-left position. This is a safety-critical
CNC reference coordinate and there's no confirmed real bottom-left CLTB example to calibrate
against (unlike CLSS's wide-panel flip, which was confirmed against a real 101.5"-wide example
before being hardcoded). **Next step:** on the real order, right-click the bracket → Rotate 90°
once, then drag it to the true bottom-left corner. Once it's sitting right, capture the final
`bracket_offset`/rotated position (or send the finished PDF) so the exact coordinates can be
locked in as CLTB's new default for drain-right orders — closing this out the same way the CLSS
wide-panel rule was closed out.

## 6. Full bug/fix history (chronological, condensed)

1. **Same file loaded into both PDF fields** → added `same_file()` check + clear errors in both
   validation and live preview.
2. **Cryptic "Stream has ended unexpectedly" dialog**, initially worried this was an OS-level
   crash — it was actually pypdf's own error, surfaced correctly once real exceptions replaced
   silent failures. Root cause: a `.jpg` was in a PDF-only field.
3. **Order forms are usually JPG, rarely PDF** → built `ensure_pdf()` to support image scans.
4. **Material bar had rounded corners and text below/off the bar** → was using `roundRect` with a
   full-pill radius and a vertical offset formula calibrated for a different kind of label. Fixed
   with a square `rect()` and a box-centered baseline formula.
5. **Editor window went blank with no error** → only the background-image step was wrapped in
   try/except, not the rest of widget construction. Broadened the try/except (later moot — this
   whole popup was replaced by the merged live editor).
6. **Page 2 "not sideways"** → investigated thoroughly, found no actual bug (`/Rotate 90` was
   always present, confirmed via raw byte regex and `qpdf`). Added a runtime self-check in
   `generate()` so this is visibly verifiable going forward instead of just trusted.
7. **Material bar STILL cut off** (second report) → root cause was genuinely different from #4:
   a fixed calibrated bar width narrower than real text needed, confirmed via `stringWidth()`.
   Fixed with dynamic bar-width sizing in both the reportlab renderer and the Tkinter canvas
   (two separate font-metric implementations, since the two renderers measure text differently).
8. **No visible Generate button / "doesn't save anywhere"** → the left panel's total field height
   had grown past the window height over the session, pushing Generate off-screen with no scroll
   mechanism. Fixed with a scrollable left panel. (Also flagged that "still cut off" reports can be
   a stale-running-process issue — Python doesn't hot-reload; always fully quit and relaunch via
   the `.command` file after an update.)
9. **Bracket not draggable, wrong position for a real order; canvas didn't scroll** (this session)
   → added mousewheel/trackpad canvas scrolling, made the bracket draggable and rotatable (see §5).

## 7. Conventions worth preserving

- Reportlab is bottom-left-origin/y-up; Tkinter canvas is top-left-origin/y-down. Conversion is
  centralized in `_pdf_to_canvas`/`_canvas_to_pdf_delta` (`CANVAS_SCALE = 0.75`) — don't do ad hoc
  conversions elsewhere.
- Dimension/thickness text always gets a white cover box behind it (both the calibrated
  `fixed_cover` and a dynamic text-sized box, layered) so labels stay legible regardless of scan
  alignment drift — this was an explicit, deliberate requirement from the user, not incidental.
- Any UI field rename or new field needs a matching README update — the README has drifted stale
  before (e.g. still said the bracket was "deliberately not draggable" after this session's changes
  — since corrected) and is the only reference the user actually reads day to day.

## 8. Distribution plan — real app icon on 3 computers, self-updating (IN PROGRESS, decisions pending)

**Goal (user's words):** "anyone with the icon can click it and get to work," updates made on the
Mac "push to anyone who has that (mine or theirs)." Three target machines: the user's Mac (where
updates will be made — primarily via a Claude for Work account, tested on Mac/Windows before
rolling out further), the user's own Windows machine, and a 3rd Windows PC the user can install on
but **cannot log into Claude on**. Confirmed fine: once the app is a real packaged executable, the
3rd machine never touches Claude, GitHub, or any account at all — it only ever needs the finished
app file. The "needs to log into Claude/GitHub" requirement only applies to the machines doing the
actual building/updating (the Mac, mainly).

### Where this stands right now

- **GitHub repo already created by the user:** `kbrs-dev/K-COFs-app` (currently private).
- **Files are fully prepped and current** at `Documents/KBRS Markup App/`: `app.py`,
  `kbrs_markup.py` (both confirmed to include the origin-bracket drag/rotate work, compiled clean),
  `.gitignore`, `KBRS Markup.command` (Mac) and `KBRS Markup.bat` (Windows) — **both launchers
  already do a non-blocking `git pull --ff-only` before launching**, README (now covers Windows
  setup + the multi-computer GitHub Desktop workflow), and this handoff doc.
- **Known environment limitation:** Claude's sandbox cannot run git operations (`git init`,
  `git commit`, etc.) inside the user's connected/mounted folders — file deletion/temp-file cleanup
  is blocked at the mount level, which breaks git's internals. **The actual repo creation/first
  push has to happen via GitHub Desktop on the user's real Mac**, not via Claude's shell — the
  prepared files above are ready to be dragged into a freshly-cloned copy of `K-COFs-app` and
  committed/pushed from there. This was not yet done as of this session — still a manual step for
  the user (or the next Claude session) to walk through.

### Open decision 1 — public vs. private repo

Directly relevant to the 3rd-device requirement: a **private** repo means every machine that pulls
from it needs an authenticated, invited GitHub account — which conflicts with both "don't want
other people to have repo access" and "3rd device with no login at all." A **public** repo (this
one specifically — not the separate, still-private configurator repo) removes that requirement
entirely: anyone/anything can pull or download a release with zero login, while only the user's own
Mac needs authenticated push access via GitHub Desktop to publish updates. This app's code has no
pricing or other business-sensitive data in it (just PDF markup/layout logic), so the exposure from
going public is low. **Recommended, not yet confirmed by the user.**

### Open decision 2 — how far to package it (three tiers, explained to the user, not yet chosen)

1. **Current state (done):** folder of files + a launcher script. Requires Python installed on
   every machine; not a real "app icon" experience.
2. **Real packaged app, manual updates:** bundle everything (Python interpreter included) into a
   single `.exe` (Windows) / `.app` (Mac) via PyInstaller (free), with a custom icon — genuinely
   just double-click and go, no installs needed on any machine. Limitation: the Windows build has
   to happen on an actual Windows machine or a CI service — **cannot be cross-built from this
   Mac-oriented sandbox**. Updates would still need manual re-download/reinstall per release at
   this tier.
3. **Full self-updating app (matches what the user described):** same packaged `.exe`/`.app`, plus
   a small update-check baked into the app itself — on launch, it checks whether the user has
   published something newer and silently updates itself first. To build both platform executables
   automatically on every push (without needing a Windows machine by hand each time), this uses
   **GitHub Actions** (free CI for public repos). Depends on open decision 1 being resolved to
   "public," since the auto-update check needs to reach the repo/releases without per-machine
   logins.

**Not yet decided:** whether to build tier 2 first and add tier 3 auto-update later once packaging
is proven, or go straight for the full tier 3 build. Recommendation offered to the user (not yet
confirmed): make the repo public, then build tier 2 first, then layer tier 3 on top.

### Immediate next steps for a new session

1. Confirm the public/private decision and the tier-2-first-vs-tier-3-straightaway decision with
   the user (both were explained but not yet answered as of this handoff).
2. Walk the user through the GitHub Desktop clone → drag files in → commit → push flow described
   above, since Claude's sandbox can't do this step itself.
3. If proceeding to packaging: set up PyInstaller (Mac build can happen in a session sandbox or on
   the user's Mac; Windows build needs GitHub Actions or an actual Windows machine), design/obtain
   an app icon (ask the user if they have a KBRS logo/icon asset, or offer to generate a simple
   one), and add the self-update check to `app.py` if going for tier 3.

---

## Session log

**2026-07-24:** Added mousewheel/trackpad scrolling to the live preview canvas. Made the origin
bracket draggable (click-drag, pink while offset) and rotatable (right-click → Rotate 90° /
Reset), with engine-side `bracket_offset`/`bracket_rotation` support in `render_page()`, full
undo/redo integration, and wiring through `generate()`. Confirmed with the user that CLTB's origin
rule should be "always bottom-left when drain is right, regardless of width" and mathematically
verified that a single 90° rotation converts the current top-left calibration into the correct
bottom-left arm orientation — did not guess new absolute coordinates without a confirmed real
example; left that as the explicit next step (drag+rotate live, then report back the final position
to lock in). Updated the README's editor section (previously said the bracket was not draggable).

**2026-07-27:** User wants the app usable on 3 computers (their Mac, their Windows machine, and a
3rd Windows PC they can't log into Claude on) with a real double-click app icon and updates made on
the Mac reaching all of them automatically. Discovered a Claude sandbox limitation: git operations
can't run inside the user's connected/mounted folders (unlink is blocked at the mount level),
so the actual GitHub repo push has to happen through GitHub Desktop on the user's real Mac, not
through Claude directly. Prepped and confirmed-current files for that at `Documents/KBRS Markup
App/`, added `git pull --ff-only` to the existing Mac launcher, and wrote a new Windows launcher
(`KBRS Markup.bat`) with equivalent Python-check/pip-install/git-pull logic. Updated the README
with Windows setup steps and the multi-computer GitHub Desktop workflow. Explained the three
packaging tiers (script+launcher → real packaged .exe/.app → full self-updating app) and the
public-vs-private repo tradeoff (private conflicts with the "3rd device, no login" requirement)
to the user; neither decision was confirmed before the user paused to export this session into a
new Claude for Work account. See §8 above for full detail — that's the next session's starting
point.
