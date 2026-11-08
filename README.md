# HSTN

Working Bazzite session switching and matching launcher artwork. See the session
switching guidance below and [DESIGN.md](docs/DESIGN.md) for the artwork style.

**HSTN**, pronounced “Houston”: *Mission control for Linux gaming sessions.*
A controller-first manager for Steam, Heroic, and KDE Desktop sessions on Bazzite.
PS opens the launcher's normal menu; hold PS then press Create for HSTN.
The overlay reviews running apps before an explicitly confirmed close-and-switch.

## Install

The self-contained installer supports clean installation, repeat installs,
upgrades and safe removal on the supported Bazzite setup. See [installer/INSTALL.md](installer/INSTALL.md)
for the downloadable shell bootstrap, offline archives, prerequisites, recovery
and native-package staging.

```sh
sh installer/install.sh --dry-run
sh installer/install.sh
```

After installation, choose whether to configure each detected launcher’s shortcuts
and artwork. Use `sh installer/install.sh -y` to configure all detected launchers
automatically.

Run from KDE Desktop with Steam, Heroic and games closed. Preview changes first;
the actual install requests sudo only for the separate system phase. No logout
or session switch is performed. Public download hosting and native RPM/.deb
recipes remain release work; the installer is not yet live-validated on a clean host.

`sh installer/install.sh uninstall` removes HSTN shortcuts, unshared artwork, diagnostics
and owned runtime files while preserving unrelated games and later edits.
For a pre-installer manual deployment, use
`sh installer/install.sh uninstall --clean-slate` from the source checkout after closing
Steam, Heroic and games; preview with `--dry-run`. See [cleanup details](installer/INSTALL.md#remove-a-legacymanual-deployment-for-clean-installation-tests).

## Commands

Run from this checkout, or use `hstn` when its entry point is linked into PATH:

```bash
./scripts/hstn --help
./scripts/hstn doctor
./scripts/hstn switch heroic
./scripts/hstn switch steam
./scripts/hstn switch desktop
./scripts/hstn activity --check
./scripts/hstn configure --launcher heroic
```

`switch` performs a real session transition and refuses while games are detected.
`activity` is read-only. `configure` requires the selected launchers to be closed.
Use the overlay for explicit close-and-switch confirmation. There is no force
option. `hstn overlay --demo` runs the inert demo; normal overlay startup is
managed by the Gamescope service or the separate KDE Desktop service.

## KDE Desktop icons and overlay

```bash
hstn desktop install
hstn desktop status
hstn desktop open
hstn desktop hide
hstn desktop remove
```

Run `install` from KDE Desktop Mode. It installs **Switch to Steam**, **Switch to
Heroic**, and **Open HSTN** into the XDG Desktop directory and application menu,
and starts HSTN hidden. KDE autostart starts the Desktop service at subsequent
logins; it is scoped to the graphical session. Hold PS then press Create to open
the menu; Circle or Escape dismisses it and releases input. The Desktop menu's
Desktop destination also dismisses without asking to close apps. Icon switching
uses the guarded switch command; use Open HSTN for explicit close-and-switch
review. Switching sessions logs out KDE, so save desktop work first.

HSTN-driven session switching briefly inhibits logind's closed-lid handling while the old
session's power manager exits and the next session starts. Protection is acquired
before logout and expires after 30 seconds; manual sleep and normal power settings
are retained. A failed guard prevents the transition. The transient unit depends
on the user manager surviving the handoff, as it does for the supported immediate
SDDM relogin; it does not guarantee protection through a delayed login that stops
the entire user manager.
Steam's built-in power-menu switch bypasses HSTN's transition guard.

The menu uses a temporary, process-specific KWin script to focus the overlay and
restore the surviving previously active window, including native Wayland apps.
It does not change KWin shortcuts or persistent scripting settings. The existing
Gamescope menu and Desktop menu cannot own controller routing simultaneously.

The current controller scope is the tested USB DualSense. Close Steam before
first enabling Desktop controller management: an already-open physical device
handle bypasses later permission changes. Once HSTN is ready, Steam can be started
again using the virtual route. Activation checks known isolation failures; a
snapshot does not prove live event isolation. Other existing InputPlumber owners
are preserved. If the guard, controller or route check is unavailable, the menu
remains accessible through the icon and keyboard/mouse, with an explanation.
After resolving the cause, restart with
`systemctl --user restart hstn-desktop-overlay.service`. Additional controllers,
Bluetooth and general hotplug support remain future work.

Setup backs up collisions in the private installation record at
`$XDG_STATE_HOME/hstn/desktop-install.json` (default `~/.local/state/hstn/`). Repeat
installs preserve original backups. Removal stops the Desktop service, restores
still-owned files, and preserves later edits with a conflict report. It does not
remove the existing root input guard or stop an active Gamescope session. This is
a focused setup tool that depends on its runtime tree and existing helpers.
The general installer packages that tree and takes over the Desktop ownership
record; use `hstn install`/`hstn uninstall` afterward for file lifecycle changes.

The permanent input guard is manually installed and boot-tested; see
[templates/systemd/README.md](templates/systemd/README.md). No temporary diagnostic helper is needed
for normal use. See [BRANDING.md](docs/BRANDING.md) for naming and compatibility paths.
The project directory is named `hstn`.

## Check the setup

```bash
hstn doctor
hstn doctor --json
```

Doctor inspects dependencies, installed wrappers and helpers, Steam/Heroic
configuration locations, manifest artwork, SDDM session lookup and desktop
entries, SteamOS Manager's session method, Heroic's effective host-talk permission, and the
input guard/user overlay services. It checks root helper ownership and the
active guard's PID/start identity. It never repairs files, starts/stops services,
closes apps or changes sessions. It does not require sudo.

Reports use PASS, WARN, FAIL and SKIP. Exit status is 1 if any check fails,
otherwise 0; warnings and skipped checks still need attention. JSON contains
`version`, `tool`, `context`, `ok`, `summary`, and a `checks` list whose entries
have `name`, `status`, and `detail`. Reports include local paths and installation
details; review them before sharing.

Doctor's overlay checks currently refer to the Gamescope service. On Desktop
that service is expected to be inactive and live controller isolation is skipped;
use `hstn desktop status` for the separate Desktop menu.
Inside Gamescope, doctor checks overlay activity and controller route
prerequisites using the existing read-only inspector (20-second scan timeout).
Steam, Heroic and Desktop use a single virtual PlayStation output for the tested
USB DualSense, suppressing duplicate outputs from button/motion/touchpad siblings.
This routing is recognized even when a terminal
does not inherit the overlay service environment. Inspection gaps warn; known
isolation failures fail. A passing snapshot is not a live controller-input test.
Doctor currently targets this project's Steam/Heroic/Bazzite setup; it does not
validate every shortcut setting, running game, or possible distribution.

### One-time Gamescope capture

For a live Steam/Heroic doctor test when the chat is on Desktop, the installed
Gamescope wrapper can consume a separate request for each launcher:

```bash
mkdir -p ~/.local/state/hstn
touch ~/.local/state/hstn/doctor-steam.once
touch ~/.local/state/hstn/doctor-heroic.once
```

The wrapper requires `~/.local/bin/capture-doctor.py` linked to this checkout's
`scripts/capture-doctor.py`. Each request is consumed once. After controller
preflight and launcher startup, a background helper waits five seconds and runs
doctor with a 60-second timeout. Reports are private JSON files under
`~/.local/state/hstn/doctor/`, containing the session, timestamp, doctor exit code,
report, and any capture error. An exited session invalidates live-test evidence.
This helper writes the requested report; doctor itself remains read-only.

Visit Steam and Heroic, stay in each for at least 15 seconds (longer if startup
is slow), and test PS+Create and PS normally. Then return to Desktop to inspect
the reports. If no report appears, check whether the matching request remains:
launches that bypass the overlay wrapper cannot capture it. Cancel an unused
request by deleting its corresponding `.once` file. No permanent capture or
extra controller-route logging is enabled.

## Configure library artwork

Requires Python 3.9+, installed launcher configuration directories, and the
host switcher wrappers in `~/.local/bin/`. Close each launcher you select before
running. The script preserves launch settings and unrelated
entries, backs up changed files, and verifies installed bytes.

```bash
# All configured entries in Steam and Heroic
./scripts/hstn configure

# Heroic library only: Switch to Steam and Switch to Desktop
./scripts/hstn configure --launcher heroic

# Steam library only: Switch to Heroic
./scripts/hstn configure --launcher steam

# One destination in one library
./scripts/hstn configure --launcher heroic --target desktop

# Multiple destinations (repeat either filter)
./scripts/hstn configure --launcher heroic --target steam --target desktop
```

`--launcher` means the library being edited; `--target` means the destination
shortcut. Omitted filters select all matching entries. A filter combination
with no matching entry fails. Unselected launchers need not be installed or
closed.

Configuration directories are detected automatically. Override with
`--steam-config-dir /path/to/Steam/userdata/ACCOUNT/config` and/or
`--heroic-config-dir /path/to/heroic` (the directory containing `sideload_apps`
and `GamesConfig`). Multiple installations/accounts require explicit selection.
The artwork is located relative to this checkout, independent of your working
directory.

## Manifest

[manifest.json](manifest.json) defines each destination's display name and
available images, plus which image goes into each launcher slot. Edit its
mappings to change artwork assignments without editing Python. Pass
`--manifest /path/to/manifest.json` to use a separate mapping; its `assets_dir`
is resolved relative to that manifest.

For example, Heroic's `art_square` maps to the destination's `portrait` image,
not its text-free `icon`. Steam's Heroic shortcut deliberately maps `icon` and
`logo` to `official_icon`, and uses Steam's default logo placement. Custom
square doorway icons are listed as available images without replacing these
choices.

The command validates all selected libraries, entries, launch settings, and
source files before writing. Validation failure leaves libraries unchanged.
Each changed existing file receives a timestamped `.bak` copy beside it; writes
use atomic file replacement. An I/O failure during application can leave some
files updated; backups permit recovery. Repeating the same configuration does
not create unnecessary backups.

The command creates missing selected shortcuts and applies their artwork. New
Steam shortcuts launch `~/.local/bin/switch-to-heroic` directly, using a stable
Steam shortcut ID derived from the executable and title. New Heroic entries are
native Linux sideloads using `/usr/bin/flatpak-spawn` with
`--host --directory=<home> <home>/.local/bin/switch-to-<target>`. Arguments are
quoted for paths containing spaces. Heroic game IDs and per-game settings are
created once and reused on later runs.

Missing shortcut/library files can be initialized inside an existing selected
configuration directory. With no existing Heroic library, automatic detection
requires its `config.json`; use an explicit configuration directory otherwise.
Existing entries retain their launch settings and IDs. Ambiguous duplicates,
Steam ID collisions, and missing/non-executable wrappers stop configuration
before writing selected libraries. New wrappers must already exist and be
executable. The script does not install host scripts, modify Flatpak permissions,
or trigger session transitions. Heroic's previously configured
`org.freedesktop.Flatpak` talk-name permission remains necessary for host launch.
 The old separate `configure-steam.py` and
`configure-heroic.py` commands have been replaced by `configure-launchers.py`.

## Tests

```bash
python3 -m unittest discover -s tests -v
```

Tests use temporary library fixtures and do not edit live launcher settings.

## Game activity and guarded switching

```bash
# JSON diagnostic report (read-only)
./scripts/hstn activity

# Guard decision without switching: 0 = allow, 20 = game detected, 21 = check failed
./scripts/hstn activity --check
```

The installed `~/.local/bin/session-switch` now runs the activity check before
selecting a session, stopping services, or logging out. Known switcher shortcuts
are excluded using their actual library IDs. Detected games block the switch,
with terminal output and a best-effort desktop notification. Already being in
KDE when requesting `desktop` remains a no-op.

User-selected policy: incomplete inspection produces warnings but does not
block switching by itself. A missing helper or a crashed check blocks the
switch. This is best-effort protection, not a guarantee: games may clear launch
metadata, helpers may linger, and launches can race with scanning. No bypass or
force option has been added to session switching.

`~/.local/bin/session-game-activity` is a symlink to this checkout's
`scripts/game-activity.py`. It resolves the companion configuration module and
manifest here. Keep this checkout available; moving/removing it breaks the
helper and causes switches to be refused until the symlink is updated.
`SESSION_SWITCH_ACTIVITY_HELPER` can override the helper path for testing.

Steam and Heroic have both been tested with the dummy game. Heroic's host loop
does not inherit launcher metadata through `flatpak-spawn`, but its waiting
`gamemoderun`/`flatpak-spawn` processes retain the game ID. Live tests verified
refusal with both test games active, allowance after their exit, and exclusion
of switcher metadata. Transition commands were stubbed during these tests: no
actual logout or session transition was performed. The two test loops were
stopped after testing.

Only selected launch metadata is reported; complete process environments are
never printed. The diagnostic JSON command returns 1 for inspection gaps,
whereas `--check` applies the warning-and-allow policy described above.
