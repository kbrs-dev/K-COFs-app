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

## 8. Distribution plan — real app icon on 3 computers, self-updating (SHIPPED — see below)

**Goal (user's words):** "anyone with the icon can click it and get to work," updates made on the
Mac "push to anyone who has that (mine or theirs)." Three target machines: the user's Mac (where
updates will be made — primarily via a Claude for Work account, tested on Mac/Windows before
rolling out further), the user's own Windows machine, and a 3rd Windows PC the user can install on
but **cannot log into Claude on**. Confirmed fine: once the app is a real packaged executable, the
3rd machine never touches Claude, GitHub, or any account at all — it only ever needs the finished
app file. The "needs to log into Claude/GitHub" requirement only applies to the machines doing the
actual building/updating (the Mac, mainly).

### Where this stands right now (updated 2026-08-27)

Both open decisions below were resolved and fully built out in the sessions after this was
originally written — the repo is public, the Windows build is automated via GitHub Actions, and
the app self-updates. This section is kept for history; see the Session log for what actually
shipped and when.

- **`kbrs-dev/K-COFs-app` is public** (confirmed via the GitHub API: `"private": false`,
  `"visibility": "public"`). Resolves open decision 1 below in the recommended direction — anyone/
  anything can pull or download a release with zero login; only push access is restricted.
- **Tier 3 (full self-updating packaged app) shipped**, resolving open decision 2 below straight to
  the top tier rather than stopping at tier 2:
  - `.github/workflows/build-windows.yml` builds a Windows `.exe` via PyInstaller
    (`kbrs_markup_windows.spec`) on every push to `main` that touches `app.py`/`kbrs_markup.py`/the
    spec/the workflow itself, stamps the build with the commit SHA (`version.txt`), zips it, and
    publishes it to a single rolling GitHub Release (`windows-latest-build`) — one stable download
    link for both Windows machines instead of a new URL per release.
  - `app.py` has its own update-check/self-update logic (`get_local_version()`/
    `get_remote_version()`, a "Check for Updates" File-menu item and an in-app banner) that compares
    the local `version.txt` against the release's, matching the "click the icon, always get the
    latest" goal from the original ask.
  - Real Windows bugs found in actual use were subsequently fixed (see Session log,
    2026-08-11-ish commit "Fix Windows bugs found in real testing, add self-updater" and the later
    "Fix update checker silently claiming 'up to date' on a failed check").
- Mac side: `KBRS Markup.command` still does the `git pull --ff-only` + auto-install flow described
  originally; no separate Mac `.app`/PyInstaller packaging was pursued since git-pull-and-run
  already satisfies the Mac use case (that's where updates are authored).

### Open decision 1 — public vs. private repo — RESOLVED: public

See above — confirmed public on GitHub, matching the recommendation in this section's original
text (low exposure, no pricing/business-sensitive data in this repo).

### Open decision 2 — how far to package it — RESOLVED: tier 3 (full self-update), Windows only

Windows got the full tier-3 treatment (packaged `.exe` + GitHub Actions build + in-app
update-check/self-update). Tier 2/3 packaging was **not** built for Mac — the Mac stays on the
git-pull-and-run launcher, which was judged sufficient since that's the machine where updates are
authored anyway, not just consumed.

### Remaining open item from this section

No packaging/distribution work is outstanding. The one thing never done: a **custom KBRS app
icon** for the Windows `.exe` was mentioned as a nice-to-have in the original ask ("real app icon")
but never followed up on — `kbrs_markup_windows.spec` should be checked if that's still wanted.

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

**Between 2026-07-27 and 2026-08-25 (this repo's actual commit history — not previously logged
here):** the repo was created on GitHub as **public**, resolving open decision 1. Distribution went
straight to tier 3 for Windows: PyInstaller packaging (`kbrs_markup_windows.spec`), a GitHub
Actions workflow that builds and publishes a rolling Windows release on every push to `main`, and
in-app update-check/self-update logic in `app.py`. Real Windows bugs surfaced in actual use were
fixed, including a case where the update checker silently reported "up to date" on a failed check
instead of surfacing the failure. Also shipped since: Blue Traveler material auto-fills 1.5"
thickness + a "FLANGE ON ALL SIDES" note; a 45° bracket rotation step for neo-angle showers;
PDF flattening of fillable/annotated order forms on import; a File > Recent Orders list (last 15);
a "Swap width/height" checkbox; a "Keyhole Linear" checkbox adding a "DRAIN PLATE NEEDED" note;
portrait-normalization fixes for scanned order forms (page-1 export is now always exact portrait
Letter, without force-rotating landscape scans); a fix for notes/items mispositioning when the
overlay auto-grows; a fix for the bracket/measurements breaking after a manual "Rotate drawing";
and a fix for the live preview appearing to (but not actually) clip items dragged near the page
edge. See `.github/workflows/build-windows.yml` and `git log` for full detail.

**2026-08-27:** Picked this back up after a gap — working tree was clean, nothing pending. Found
this handoff doc badly stale: it still described the distribution plan (§8) as "in progress" with
two unresolved decisions, but the actual commit history showed both had been resolved and fully
built (public repo, confirmed via the GitHub API; tier-3 self-updating Windows app, confirmed via
`build-windows.yml` and the release pipeline). Rewrote §8 to match reality instead of leaving a
misleading "still open" section for the next session to re-litigate. The one item from this whole
doc that's still genuinely unresolved is §5 (CLTB origin bracket calibration for drain-right
orders) — checked `PROFILES["CLTB"]["bracket"]` in `kbrs_markup.py` and it's still the original
top-left coordinate, unchanged since 2026-07-24. That one can't be closed out without a real
confirmed bottom-left CLTB example from the user (a finished drag+rotate result or PDF), same
constraint as before — flagged back to the user rather than guessing at a safety-critical CNC
coordinate.

**2026-08-28:** User reported "Add note" silently doing nothing on a real Custom Vanity Vessel
order (production order PO248604 / SO244467, order form for KBRS's new "Point Drain Vanity Vessel
(PDV-301)" line — a genuinely new product with zero PROFILES entry and no git history anywhere in
this repo; confirmed there's no "CVV" support that was ever added or pushed here, contrary to the
user's expectation that it already existed). Root-caused to two compounding issues:
1. `parse_production_order()` raised a hard `ValueError` for this production order's item line
   ("CUSTOM VANITY VESSEL: Custom Vanity Vessel- 15\" x 23\" x 6-1/2\"") since it doesn't follow the
   "SKU-CODE: name (WxH)" format every other product's production order uses (no SKU code, and
   three dimensions instead of two) — losing even the po_number/so_number the function had already
   read, and blocking the order from loading at all in the app.
2. Even with that fixed, `InteractiveLayout.load_background_only()` (the fallback path that shows
   the order form when no profile can be resolved) explicitly sets `self.loaded = False`, and
   `add_note()`/`toggle_cut_line()` were gated on that same flag — so the background loaded fine,
   but the toolbar buttons for the app's only manual-annotation tools silently no-op'd, with nothing
   telling the user why.

Fixed both, plus made Generate itself support this "manual-only" mode end-to-end rather than
hard-blocking with "Unknown product": `parse_production_order()` now returns partial data (still
reading po_number/so_number/order_date normally) instead of raising when the item/dimension line
doesn't match the expected format; a new `has_background` flag (separate from `loaded`, which still
means "profile-based, matches()/get_items() are meaningful") gates the manual tools; and
`render_page()`/`_content_bbox()` in the engine skip the material-bar and origin-bracket drawing
entirely when `profile is None` (both are safety-critical calibrated-CNC-coordinate features with
nothing to guess from for an uncalibrated product) while still drawing whatever manual notes/cut-
line items exist. `_validate_and_prepare()`/`generate()` now produce a real merged PDF in this case
instead of refusing, with the status line explicitly flagging "no calibrated layout... manual-only"
so it's never mistaken for a fully-calibrated export. Verified end-to-end headlessly against the
user's actual PO248604 + vanity order form files (parse → render_page(profile=None) → merge_pdf →
confirmed 2 pages, page 2 rotated 90°, note text rendered, no material bar/bracket drawn) since the
sandbox has no tkinter to run the live GUI itself — same testing constraint as always for this repo,
see §2. README updated with a new section explaining this manual-only mode.

**"Diagonal line" clarified and implemented:** the user's third request turned out to describe a
brand new manual tool, not an existing feature that needed a bug fix — searching the repo/history
for any existing "diagonal line" concept found none, so this was confirmed with the user before
building anything (see the questions/answer above): a plain **solid** indicator line (as opposed to
the dashed cut-for-shipping line) in the app's accent color, purely a visual marker that never
changes any oversize dimension, added manually (not tied to or auto-populated for any particular
product type, linear or otherwise), starting at 45° with a right-click "Rotate 45°" step to spin it
in place.

Added `engine.make_diagonal_line_item()` (counter-keyed like notes, so more than one can exist) —
render_page()/_content_bbox() already handled generic line-kind items, so no engine rendering
changes were needed beyond the factory function itself. On the app.py side: a new "Add diagonal
line" toolbar button (`add_diagonal_line()`, gated on `has_background` like Add note — works with or
without a calibrated profile), a `_rotate_diagonal_line()` handler (reuses `engine.rotate_point()`
around the line's own midpoint, same mechanism as the bracket's 45° neo-angle step), and a
right-click menu entry for any `diagonal_*` key. Whole-line dragging worked for free (the existing
`_press`/`_motion` handlers are already generic across all line-kind items); endpoint-drag
(extend/shorten one end independently) was deliberately *not* generalized from the cut-line's
hardcoded version — the user only asked for drag-to-reposition + 45° rotate, not free-length
adjustment, so that's a reasonable next step if it's ever actually wanted, not a gap in this one.
Verified headlessly: rotation math round-trips exactly after 8×45° (back to the original endpoints,
sub-microinch), and it renders correctly both with a calibrated profile and in profile=None
(manual-only) mode. README updated with a description of the new toolbar button.

**(Undocumented here until now, shipped between 2026-08-28 and 2026-09-04):** SRC-D1/SRC-D3 product
types (reusing CFSRC's calibrated geometry; D1 auto-adds a pilot-hole note, D3 the flange note), a
fix for the Windows self-updater's `ren` failing because the relaunch `cmd.exe` inherited the
running app's own directory as its cwd, and a "Darken lines/text" contrast control for faint
CAD/CAM exports (e.g. Aspire's PDF output) and washed-out scans, followed by a fix for that same
feature causing severe quality loss/dropped linework on a source page sized to the real physical
part rather than Letter — root cause was an unnecessary lossy second rasterization pass, not the
contrast math; fixed by applying contrast during the original full-resolution render instead.

**2026-09-04:** A real Aspire CIS order (manual-only mode, no calibrated profile) had its drawing
exported to fill the entire page with zero margin at the bottom, so dragging the Traveler
material bar below it pushed the bar past the real page's own physical boundary — PDF pages have a
fixed MediaBox, and the existing overlay "auto-grow" only resizes the overlay's OWN page, which
doesn't help: `merge_pdf()` always composites onto the real target page using the fixed canonical
`PAGE_W x PAGE_H` -> real-page ratio, so anything outside that canonical box lands outside the real
page too, no matter how the overlay's own page was sized. Confirmed this diagnosis against the
user's actual files (`pypdf`/`pypdfium2` inspection) before proposing a fix, per this repo's normal
practice of not guessing at physically-meaningful behavior.

User explicitly asked for auto-shrink-to-fit rather than just a warning: "id rather they just print
and the drawing shrunk to make it fit below it." Implemented as `engine.compute_page_fit()` +
`engine.apply_page_fit()`: a uniform scale factor `k <= 1.0` anchored at whichever edge of the real
page ISN'T overflowing (e.g. content hanging below anchors at the top and shrinks upward, freeing
blank space at the bottom), computed from the same content bounding box `_content_bbox()` already
used for auto-grow. Applying the identical `(k, anchor)` to BOTH the background drawing (a new `fit`
parameter threaded through `normalize_to_portrait_page()`/`get_transformed_order_form()`) and every
overlay coordinate (`render_page()`) keeps the drawing and every item — including a calibrated
origin bracket or dimension callout, in the rare case one of those is what overflowed — exactly
aligned with each other throughout, just at a slightly smaller overall size; this is a pure
similarity transform, not an independent reshuffling of drawing vs. overlay, so it can't misalign a
CNC-critical reference point relative to the drawing it's calibrated against.

Learned from the earlier contrast quality-loss bug and applied the same fix up front this time: fit
is baked into `normalize_to_portrait_page()`'s own first, full-resolution render whenever the
background isn't ALSO being manually rotated (the common case), never into a second lossy
re-rasterization pass. Only a background rotation combined with an active fit needs a second pass
(an existing, already-accepted trade-off rotation/scale already had) — verified this combination
still produces the correct page size and placement, just at the pre-existing rotation/scale quality
cost, not a new one.

A no-op (`k == 1.0`) for the overwhelming majority of orders, where nothing was ever positioned
outside the real page — verified via a headless unit test (an off-page material bar's canonical
y-coordinate lands at exactly 0 after the fit transform, i.e. right at the real page's edge) and a
full render→merge→rasterize end-to-end test (the bar is visibly present in the final merged PDF's
rendered pixels, at the very bottom of the physical page, where it previously rendered nowhere at
all). Wired into `generate()`'s both branches (profile-based and manual-only) in `app.py`; the
status line after Generate now says when a shrink was applied and by roughly how much. Deliberately
scoped to `generate()`'s final output only, NOT the live interactive preview/canvas — the preview's
whole coordinate system (`_pdf_to_canvas`/`_canvas_to_pdf_delta`, dragging, hit-testing) stays
untouched, since rewiring all of that to also show the shrink live would be a much larger, riskier
change for a feature that (by design) only ever activates in a rare, already-abnormal case; the
tradeoff is that the live editor won't visually preview the shrink before Generate is clicked, only
report it afterward. README updated with a short "Auto-shrink-to-fit" explanation.
