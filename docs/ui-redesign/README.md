# Launch Deck redesign

Implements [issue #2](https://github.com/jeff-roche/hstn/issues/2) from the
[approved handoff](brief.md). The overlay remains native Qt and keeps its
existing asynchronous planning, confirmation, switching and input lifecycle.

See [design QA](../../design-qa.md) for screenshots, validation and remaining
hardware acceptance. The supplied rocket is in `assets/logo/`; destination art
and launcher slot mappings are unchanged. All PlayStation footer symbols use Kenney's Input
Prompts under CC0; attribution and license are in `assets/controller/`.

The session wrapper passes its known Steam or Heroic destination to the overlay
for the Current badge. Desktop identifies itself through the existing Desktop
entry point. Unknown clients leave the badge absent.

For a keyboard-only deck preview with switching disabled, run from this checkout:

```sh
python3 src/session-overlay.py --demo
```

Press F8 to open the deck. Use arrows or Tab to navigate, Enter to select, and
Escape to return. Demo mode never starts a planner or closes apps. Screenshots
in this directory use fixture review data rather than real running processes.
