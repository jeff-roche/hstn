# HSTN naming and compatibility

Display name: **HSTN**. Pronunciation: **Houston**. Command/repository slug:
`hstn`. Tagline: **Mission control for Linux gaming sessions.** No expanded
acronym is required. The user selected this name on November 7, 2026.

## Public tools

`scripts/hstn` is the public entry point: `switch`, `configure`, `activity`,
`overlay`, and `doctor` forward arguments to their implementations. It resolves its
checkout through symlinks and preserves tool exit codes and safety checks.
The existing `configure-launchers.py` and other direct commands remain usable.
The read-only `doctor` command checks installation health. `install`, `setup`
and `uninstall` expose the shared standalone/native-package user lifecycle.
No force option is provided. See [installation guidance](../installer/INSTALL.md) for ownership boundaries.

## Installed compatibility

Keep these identifiers until an explicit migration is implemented and tested:

- `session-switch`, `session-close`, `session-game-activity`,
  `hstn-overlay`, and `switch-to-*` installed entry points.
- `session-switch-overlay.service`, `session-switch-input-guard.service`,
  their environment files, runtime paths, status kind, rollback journal and lock.
- `SESSION_SWITCH_*` environment variables and existing diagnostic marker paths.
- Existing launcher shortcut IDs, launch settings, titles and destination artwork.

These are compatibility identifiers, not the public product name. The service
source descriptions and overlay window title use HSTN. The root-owned installed
service/helper copies require a separate privileged update; a source edit does
not update them. Do not rename the active guard runtime directory or journal:
they retain ownership information needed for recovery and safe rollback.

A future installer should expose `hstn` and automate root-owned copies and user
service configuration. Any later internal migration must handle existing units,
symlinks, runtime state and shortcuts without creating two competing guards.

## Preliminary conflict check

No prominent standalone Linux/gaming `hstn` application surfaced. Hydrascale
uses an `hstn` shell function (https://github.com/Crank-Git/Hydrascale).
Oakley Meta HSTN smart glasses are the main exact-name commercial/search overlap.
Several unrelated Houston software tools exist; do not add a `houston` alias.
This research did not establish trademark or package-registry clearance.
