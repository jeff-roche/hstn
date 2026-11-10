# Licenses and third-party notices

HSTN code and documentation are licensed under [MIT](LICENSE), copyright
2026 Jeff Roche and HSTN contributors. This does not relicense third-party
images. The file-level scope and provenance evidence are recorded in
[assets/README.md](assets/README.md).

## Kenney Input Prompts 1.3

Creator/distributor: Kenney (<https://kenney.nl>).
License: **CC0-1.0**. The original package notice is preserved verbatim in
[assets/controller/LICENSE](assets/controller/LICENSE); the
[CC0 legal text](https://creativecommons.org/publicdomain/zero/1.0/legalcode)
defines the dedication and fallback license.

Source: [official Input Prompts pack](https://kenney.nl/assets/input-prompts),
obtained from [Maaack's mirror at dd37497091c176e91ce81a14e203729ea12d8e4b](https://github.com/Maaack/Kenney-Input-Prompts/tree/dd37497091c176e91ce81a14e203729ea12d8e4b).
The PlayStation, Xbox, keyboard, and handheld SVGs have ivory fills and adjusted
intrinsic dimensions/viewBox; their paths are preserved. See the exact
source-to-local mappings in [assets/controller/README.md](assets/controller/README.md).
Kenney credit is appreciated but not required by the package notice.

HSTN's authored `assets/controller/usb.svg` and `bluetooth.svg` are also dedicated
under CC0-1.0, as recorded in that directory's README.

## Heroic Games Launcher icon

`assets/artwork/heroic-official-icon.png` is an unmodified copy of
`public/icon.png` from **Heroic Games Launcher**, by the Heroic Games Launcher
contributors. It is distributed separately under upstream's **GPL-3.0-only**
terms, not HSTN's MIT license. The full upstream license is included at
[assets/artwork/HEROIC-COPYING](assets/artwork/HEROIC-COPYING).

Verified upstream revision: `75e383491b589dbda07fb32f28d716e631deec5b`.

- [Original PNG source](https://github.com/Heroic-Games-Launcher/HeroicGamesLauncher/blob/75e383491b589dbda07fb32f28d716e631deec5b/public/icon.png)
- [Repository source tree](https://github.com/Heroic-Games-Launcher/HeroicGamesLauncher/tree/75e383491b589dbda07fb32f28d716e631deec5b)
- [Upstream license declaration](https://github.com/Heroic-Games-Launcher/HeroicGamesLauncher/blob/75e383491b589dbda07fb32f28d716e631deec5b/package.json)
- [Original COPYING](https://github.com/Heroic-Games-Launcher/HeroicGamesLauncher/blob/75e383491b589dbda07fb32f28d716e631deec5b/COPYING)

The local Git blob ID is `519bae9e1a9886ad9328fd6bc321bb0d64bedbc4`, matching
upstream. SHA-256:
`35cf28043bcb6e1d4cf290051403566a71914e176a5ce4045aba586003eb0dce`.
No HSTN modifications were found. Keep this notice, the upstream license, and
the source information with redistributed copies of the image. Shipping the
image alongside HSTN does not change its separate license.

## Project artwork and marks

Jeff Roche confirmed on November 10, 2026 that the custom doorway artwork,
navy backgrounds, rocket design, and reference mockups were generated with GPT.
HSTN makes its rights, if any, in these assets and their project edits available
under [MIT](LICENSE). The exact model and generation dates were not recorded.
See [assets/README.md](assets/README.md) for the confirmation and file-level
inventory. HSTN's UI screenshots are application captures incorporating those
assets and separately licensed controller prompts.

Product names and symbols identify their respective destinations or controls.
HSTN does not claim ownership of third-party trademarks or endorsement by their
owners. Copyright licenses do not grant trademark rights.

## Runtime dependencies

HSTN relies on separately installed PySide6/Qt, PyYAML, InputPlumber, Gamescope,
Steam, Heroic, KDE, and system tools. Release archives contain HSTN files and
the assets above, not copies of those runtime packages. Their licenses and
notices remain with their distributions. If a future package bundles a
dependency, review and include its notices before publication.
