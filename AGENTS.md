# Repository Guidelines

## Project Structure & Module Organization

HSTN manages Steam, Heroic, and KDE Desktop sessions on Bazzite. `scripts/hstn` is the CLI entry point; `scripts/` contains Python helpers and Bash session wrappers. `tests/` holds automated tests. `templates/config/` contains Gamescope and KWin integration, and `templates/systemd/` contains service units. Artwork lives in `assets/artwork/`, with launcher mappings in `manifest.json`. `installer/install.py` and `installer/install.sh` provide installation entry points; `installer/` defines release assembly.

Read `README.md` for behavior, `installer/INSTALL.md` for deployment, and `docs/DESIGN.md` and `docs/BRANDING.md` for visual and naming guidance. Exclude `docs/superpowers/`, `diagnostics/`, and `prototypes/` from routine exploration and changes.

## Build, Test, and Development Commands

Run commands from the repository root:

- `./scripts/hstn --help`: inspect available CLI commands.
- `python3 -m unittest discover -s tests -v`: run the automated suite.
- `python3 -m unittest discover -s tests -p 'test_session_switch.py' -v`: run a focused test module.
- `sh installer/install.sh --dry-run`: preview installation changes.
- `python3 -B installer/package.py --output /tmp/hstn-release`: build release archives and checksums.
- `python3 -B installer/package.py --destdir /tmp/hstn-package-root`: stage native package files.

## Coding Style & Naming Conventions

Use four-space indentation in Python and follow surrounding code conventions. Use `snake_case` for functions and variables, `UPPER_CASE` for constants, and descriptive hyphenated executable names such as `session-transition-guard.py`. Preserve Bash quoting and existing `set -euo pipefail` safeguards. No repository-wide formatter or linter configuration is present.

## Testing Guidelines

Tests use standard-library `unittest`, temporary directories, and mocked commands. Name modules `test_*.py` and methods `test_<behavior>`. Cover refusal paths, rollback, ownership checks, and repeat-operation behavior when relevant. No numerical coverage threshold is configured. Live controller routing and session transitions require manual acceptance on supported Bazzite hardware; document what was actually verified.

## Commit & Pull Request Guidelines

The current branch has no commits, so no historical message convention is established. Use concise imperative subjects, such as `Fix session guard cleanup`. PRs should explain the behavior change, link relevant issues, report validation, and include screenshots for overlay or artwork changes.

## Security & Configuration

Keep credentials and private machine captures out of commits. Use fixtures for automated checks; real switching logs out sessions. Preserve explicit close-and-switch confirmation, installation ownership tracking, backups, and recovery behavior.
