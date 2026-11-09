# Launch Deck native Qt design QA

final result: passed

Scope: offscreen native Qt visual and fixture interaction checks. Live Bazzite
Gamescope/KDE compositor integration and physical controllers are not covered by
this result and still need hardware acceptance.

## References and captures

Approved [brief](docs/ui-redesign/brief.md) and its two screen references were
compared side by side with captures at the same 1672 × 941 viewport and state:
Heroic current, Steam focused on the deck; Steam destination, Cancel focused in
review. The four-porthole rocket supersedes the older mark in the screen mocks.

- [Launch Deck, TV](docs/ui-redesign/launch-deck-tv.png)
- [Review, TV](docs/ui-redesign/review-tv.png)
- [Launch Deck, handheld](docs/ui-redesign/launch-deck-handheld.png)
- [Review, handheld](docs/ui-redesign/review-handheld.png)

Captures use synthetic Hades/Heroic app data, Qt's offscreen platform, and mocked
switch helpers. Black outside the panel represents the offscreen underlay; no
private desktop or gameplay capture is included.

## Findings resolved

- Removed Qt's implicit minimum window constraint that expanded handheld views.
- Kept artwork proportional and fully visible, with live destination names.
- Separated Current from the ivory focus outline; unknown sessions omit Current.
- Moved review heading and scrollable app details to the left of destination art.
- Kept confirmation actions outside the scroller, initially focused on Cancel.
- Restored deck geometry after repeated review/cancel cycles.
- Routed Tab through QWidget's event handler, alongside arrows and controller input.
- Escaped app and process names before rich-text display.
- Bundled the supplied logo and licensed controller symbols in runtime inventory.

## Validation

`python3 -m unittest discover -s tests -v`: all 247 tests passed.
The first clean-worktree run exposed two pre-existing tests depending on local
files excluded from Git. For validation only, the existing prototype helper and
generic captured-rule fixture were copied from the original checkout into the
worktree. They remain locally ignored and are not part of the redesign changes.
No tests were skipped or removed.

All 12 overlay tests pass, including a 40-app review at 854 × 480, 1280 × 800,
and 1920 × 1080. Checks cover traversal order, cancellation, repeat review,
explicit confirmation, duplicate requests, zero apps, changed apps, failed
switches, escaped names, warnings, and packaged visual assets. Existing tests
cover late-plan cleanup, guard loss, Desktop fallback, and mouse selection.

Release archive and native package staging succeed. Fixture captures were also
rendered directly from the staged runtime with its own assets.

## Remaining polish and manual acceptance

The native rendering uses the existing square artwork, installed sans-serif,
and restrained panel borders. It does not reproduce generated atmospheric
textures or focus glow. Process details sit below each app to preserve grouping.
Keyboard and scroll hints supplement the controller footer.

Still verify on Bazzite: physical DualSense input and capture/release, couch
legibility, native Desktop focus restoration, actual Gamescope compositing,
Steam/Heroic/Desktop round trips, and guarded closing of real apps. No real apps
were closed or sessions switched during this work.

## Size and spacing refinement

Following user feedback, reduced the panel from 88% × 86% to 78% × 76% of
the viewport, with proportionally smaller internal spacing and type. Added an
explicit gap (at least 10 px) between destination artwork and live labels on
both screens. Shortened the review scroll hint so all footer controls remain
visible at handheld size. Refreshed all four screenshots and inspected both
screens at 854 × 480 and 1672 × 941; all 12 overlay tests passed.

## Kenney PlayStation glyphs

Replaced the Material symbols with Kenney Input Prompts for Cross and Circle.
The review footer now also uses Kenney L1 and R1 prompts rather than text
abbreviations. Geometry is unchanged from the source SVGs; only fill and sizing
metadata are adapted. Source version, pinned mirror, and original CC0 license
are included under `assets/controller/`. All four glyphs are in the package
inventory and covered by the asset-loading check. Refreshed screenshots and
checked the footer at handheld and TV sizes. All 12 overlay tests pass; release
packaging and native staging succeed.

## Compact desktop panel and prompt alignment

The panel is now capped at 960 × 620 logical pixels, with proportional scaling
on smaller screens. At the supplied screenshot's 1920 × 1200 viewport this is
half the screen width, instead of the previous 78%; type and spacing are based
on the panel size rather than monitor size. See the updated
[desktop capture](docs/ui-redesign/launch-deck-desktop.png).

Cards now reserve font-metric-based name and badge rows plus explicit bottom
padding. The image-to-label gap remains. The footer uses native layout cells
with vertically centered Kenney images and labels, replacing rich-text image
baselines. Verified both screens at desktop and handheld sizes, including long
reviews. Regression checks cover the size cap and matching icon/text centers.
All 247 tests pass.

## Application and taskbar icon

Set the application and overlay window icon to the packaged rocket, with 24,
48 and 256 px sources. The Qt desktop identity is `hstn-open`; the generated
Open HSTN launcher uses the rocket and `StartupWMClass=hstn-overlay`. Absolute
icon paths resolve against the installed runtime.

All 247 tests pass. An isolated Xvfb run of the actual `--demo` entry point
verified the X11 WM_CLASS, published `_NET_WM_ICON` images, and KDE desktop-file
identity. No live session services were restarted or installer changes applied.
