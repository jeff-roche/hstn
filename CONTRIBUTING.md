# Contributing to HSTN

Read [AGENTS.md](AGENTS.md) for repository layout, coding conventions, commands,
and safety requirements. Use the bug and feature templates for new issues and
link the issue in a focused pull request. See [SUPPORT.md](SUPPORT.md) for scope
and [docs/RELEASING.md](docs/RELEASING.md) for release ownership.

## Local checks

Tests require Python 3.10+, PySide6 including QtDBus, PyYAML, and Linux system
tools. CI pins the Python dependencies in `requirements-test.txt` and uses Ubuntu
24.04 system Python because several tests invoke `/usr/bin/python3` directly.
Keep that interpreter able to import PySide6 and PyYAML; a virtual environment
alone does not change those subprocesses. On Bazzite, use the installed runtime
dependencies. CI uses Qt's offscreen platform and synthetic process/device data.

From the repository root:

```sh
python3 -m unittest discover -s tests -v
./scripts/hstn --help
python3 -B installer/package.py --output /tmp/hstn-release
python3 -B installer/package.py --destdir /tmp/hstn-package-root
```

Choose a fresh staging directory for each native build. Packaging tests check
reproducibility, checksums, executable modes, resources, and installed notices.
CI runs the complete suite, shell syntax checks, and both packaging modes.
An uploaded CI archive is a development artifact, not a supported release.
CI never installs HSTN, closes real apps, or switches the runner's session.

Changes involving session transitions or controller routing also need the
appropriate live Bazzite acceptance before release. Report automated and manual
results separately. Preserve explicit close-and-switch confirmation, ownership
checks, backups, and recovery records. Do not commit private machine captures.

## Documentation and assets

Update [CHANGELOG.md](CHANGELOG.md) under Unreleased when behavior or support
changes. Overlay/artwork PRs need screenshots. Follow [docs/DESIGN.md](docs/DESIGN.md)
and [docs/BRANDING.md](docs/BRANDING.md). For new or changed artwork, record the
creator or generation source, upstream URL and revision, modifications, license,
and required notices in [assets/README.md](assets/README.md) and
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). Include all required notices in
`installer/files.json`; assets and notices must survive both package formats.
Do not infer an asset license from its appearance or from the code license.

Contribute code and documentation under the project's [MIT license](LICENSE).
Existing third-party asset licenses remain in force. Identify any different
asset terms explicitly so they can be reviewed before inclusion.
