# Installing HSTN

HSTN currently targets **Bazzite KDE with Steam, Heroic Flatpak, Gamescope
session-plus and DualSense, Xbox One, or Xbox Series X|S over USB or Bluetooth**. USB has prior live testing;
Bluetooth routing and reconnection have automated coverage and need live
acceptance. An installer does not establish support for other distributions/controllers. Install, upgrade and remove from KDE
Desktop with games closed. Close Steam and Heroic first, or use `-c` to authorize
closing running launchers. Installation never logs out, restarts SDDM, reboots or
changes your persistent autologin destination.

## From an extracted release or source tree

Requires Python 3.10+. Preview first:

```sh
sh installer/install.sh --dry-run
sh installer/install.sh
```

Add `-c` (or `--close-launchers`) to authorize closing detected running launchers
without extra prompts. Steam receives `-shutdown`; Heroic main processes receive
SIGTERM. The installer waits for exit and reports any launchers that still need
manual closing. It refuses while games are active and never escalates to SIGKILL.
`--dry-run` and status checks never close launchers. `-y` only accepts shortcut
configuration; combine the flags to authorize both actions:

```sh
sh installer/install.sh -c -y
```

The normal invocation installs the runtime, commands, session definitions,
Desktop icons/autostart and user units; requests sudo for a separate system
phase; starts the Desktop menu hidden; and runs the installed mechanic. The system
phase stages regular root-owned copies in a root-private temporary directory
before executing installation code. It installs the input guard, Heroic login
entry and a dedicated SDDM directory snippet, then validates guard readiness.

After installation, answer `y` or `n` for each detected launcher to create/update
its HSTN shortcuts and artwork. Add `-y` (or `--yes`) to configure every detected
launcher without prompting:

```sh
sh installer/install.sh -y
```

Without an interactive terminal,
configuration is skipped unless `-y` is supplied. You can configure later with
`hstn configure --launcher steam` or `hstn configure --launcher heroic`. Ambiguous
account configuration requires `--steam-config-dir /absolute/path` and/or
`--heroic-config-dir /absolute/path`. These selections are retained for mechanic,
activity checks and later configuration. Both launchers must be installed even
when library setup is deferred. Multiple Heroic Flatpak deployments are rejected
rather than silently choosing which deployment to configure.

`--user-only` explicitly skips the system phase. It is useful when an administrator
has already provisioned the system components; it is not a complete installation
on a clean system. Mechanic still reports missing system prerequisites as failures.

The source directory can be removed after successful standalone installation.
Keep it during migration/testing if existing backups point to the old checkout.
Ensure `~/.local/bin` is in PATH, or use `~/.local/bin/hstn` directly.

## Downloadable shell installer

The bootstrap can download `hstn-VERSION.tar.gz` and `SHA256SUMS` from
`RELEASE_BASE_URL/vVERSION/`, check the exact archive checksum, validate its
contents and run the same Python installer. Until public hosting is chosen,
**no default download URL is embedded**. With a maintainer-provided HTTPS URL:

```sh
# Replace the variables with the published bootstrap URL, release base and version.
mkdir -p installer
curl --proto '=https' --tlsv1.2 -fSL "$HSTN_INSTALLER_URL" -o installer/install.sh
sh installer/install.sh --release-base-url "$HSTN_RELEASE_BASE_URL" --version "$HSTN_VERSION" --dry-run
sh installer/install.sh --release-base-url "$HSTN_RELEASE_BASE_URL" --version "$HSTN_VERSION"
```

Downloading the script first permits inspection. Piping the same trusted script
to `sh -s --` is also supported. Download options go before Python installer
options; `--` explicitly separates them. `HSTN_VERSION` and
`HSTN_RELEASE_BASE_URL` can supply the corresponding options.

For an already-downloaded archive:

```sh
sh installer/install.sh --archive /path/to/hstn-VERSION.tar.gz --sha256 EXPECTED_HEX_DIGEST --dry-run
```

Checksums detect damaged or mismatched downloads; a checksum served alongside an
archive does not independently authenticate its publisher. Obtain the script and
release information from the trusted project release source. Extraction accepts
only regular files under one matching versioned root, rejects duplicate/traversal
paths and special files, and limits the extracted payload size. Nothing is
executed after a failed download, checksum or archive validation.

## Layout, upgrades and recovery

Standalone runtime: `$XDG_DATA_HOME/hstn` (default `~/.local/share/hstn`).
Compatibility commands stay in `~/.local/bin`. User configuration and private
state honor `XDG_CONFIG_HOME` and `XDG_STATE_HOME`. Default paths work without
setting those variables; custom XDG paths must also be present in future login
environments so Gamescope can find its user session definitions.

The user record is `$XDG_STATE_HOME/hstn/install.json`. System state is separate
at `/var/lib/hstn/system-install.json`, readable/writable only by root. The records
contain backups and pending changes. Preserve them through partial failures.
Repeat the same install command to resume or upgrade from a newer extracted
release. Installation stops on edited owned files instead of overwriting them.
No autonomous update daemon is installed.

```sh
hstn install --status
hstn mechanic
hstn uninstall --dry-run
hstn uninstall
```

Removal restores unrelated prior files/modes/symlinks and service state only
where HSTN still owns the installed content. It removes HSTN launcher shortcuts,
their unshared artwork/settings, diagnostics, and empty installed runtime/state
directories. Library edits preserve unrelated current games and shared artwork;
they never restore an old whole-library snapshot. Later edits remain with a
conflict report and recovery records. Existing focused Desktop backups migrate
into the general record, including during removal, so unrelated original icons
can be restored. Use the general installer for installation/removal, while
`hstn desktop open/hide/status` still controls the menu. No shared launcher library
or configuration directory is deleted. If a conflict leaves the command unavailable, use
`python3 -B /path/to/extracted-release/installer/install.py uninstall` to finish recovery.

### Remove a legacy/manual deployment for clean installation tests

An older manual deployment can predate the ownership record. Explicitly remove
its recognized HSTN commands, wrapper backups, session overrides, user services,
root guard, Heroic login entries, HSTN SDDM snippets, inactive experimental
configuration backups and HSTN's manual Heroic host-talk override with:

```sh
sh installer/install.sh uninstall --clean-slate --dry-run
sh installer/install.sh uninstall --clean-slate
```

This works after an earlier uninstall has restored the manual deployment, and
when no general installation record exists. It requires KDE with Steam, Heroic
and games closed. It stops/disables the guard so matching runtime rules can be
restored, then removes only fixed, validated HSTN system paths through the
root-owned stage. Unrecognized/edited files cause a conflict, not deletion.
Unresolved input-guard rollback data is retained for recovery. A failed cleanup
can be retried with the same command; keep its recovery records until it finishes.

The source checkout, Bazzite/vendor Steam session definitions, autologin user,
installed Steam/Heroic, unrelated games/files, and shared whole-library backups
are preserved. Native packages must first be removed through their package
manager. Once this baseline is clean, a normal install/uninstall cycle removes
all newly installed HSTN assets without resurrecting the earlier deployment.

The system guard is stopped only from Desktop with games closed so it can restore
its owned runtime corrections. The installer retains its existing lock, journal,
readiness checks and compatibility names; it does not stop InputPlumber or adopt
another controller owner. A higher-priority SDDM main-file SessionDir that excludes
`/etc/wayland-sessions` must be corrected explicitly before installation.
Fedora's trusted vendor-wide `TimeoutStopFailureMode=abort` policy is preserved.
Other guard service drop-ins require explicit review; installation does not
silently accept overrides that could redirect the root guard's executable.

## Dependencies and acceptance

Preflight checks Bazzite, KDE Desktop, closed launchers/games, both launcher
installations/configuration, InputPlumber, SDDM, SteamOS Manager's session API,
Gamescope/session-plus, PySide6 including QtDBus, X11/XRes libraries, Flatpak and
host spawning, systemd including `systemd-inhibit`, and supporting commands.
Missing requirements stop setup before installation writes. It does not run
apt/dnf, layer packages, download launchers or change OS images.

After file/service installation, mechanic failures mean setup is incomplete, even
though recoverable installed files may remain. WARN/SKIP do not establish live
controller isolation. Desktop reports omit the Gamescope-only runtime checks.
Perform Steam and Heroic round trips, repeated restarts, PS/PS+Create, glyphs,
guarded close-and-switch and reboot acceptance manually. Diagnostic captures are
included but never armed by installation. The service watches for supported USB
and Bluetooth controllers and maintains separate virtual outputs for multiple controllers.
Multiple-controller hotplug has automated coverage; live hardware acceptance,
Bluetooth feedback/suspend/resume, and Steam's built-in power-menu lid-guard
coverage remain unvalidated. Pair Bluetooth devices through KDE before use;
the installer does not configure Bluetooth adapters or pairing.

The input guard reserves supported physical controller nodes before session access is granted,
so Steam cannot open a newly connected controller before HSTN routes it. Steam
uses the virtual output. This reservation lasts while the guard runs, including
between sessions; stopping the guard removes its owned runtime rule and restores
normal access. If HSTN routing is unavailable, use keyboard/mouse for recovery.
Close Steam and reconnect the controller once when upgrading from a version that
allowed Steam to open it directly. Startup, hotplug, session round trips and guard
stop/restart with this reservation still require live hardware acceptance.

## Building releases and native packages

```sh
python3 -B installer/package.py --output /tmp/hstn-release
python3 -B installer/package.py --destdir /tmp/hstn-package-root
```

`VERSION`, `installer/files.json` and manifest-referenced artwork define a release.
Identical inputs produce identical archive bytes and a `SHA256SUMS` file. The
allowlist excludes private captures, accounts, credentials, caches, diagnostics
output and `.superpowers` backups. The build does not inspect the builder's home
or depend on Git.

Native staging places the runtime under `/usr/lib/hstn`, `hstn` under `/usr/bin`,
the guard under `/usr/libexec` and its unit under `/usr/lib/systemd/system`.
RPM/Debian packaging can consume this DESTDIR tree, define distribution-specific
dependencies and appropriate service lifecycle integration. Staging itself does
not control services or modify any user's home. Native package users explicitly
run `hstn setup`; they upgrade/remove package-owned files through their package
manager. `hstn uninstall` restores that user's setup and HSTN-created system
configuration; it does not remove native package files. The standalone installer
refuses to shadow/overwrite a detected native installation. Remove the old setup
before switching installation methods. Actual RPM/.deb recipes and Debian runtime
support are not included yet.

Before publishing: choose the project license, review third-party artwork
redistribution/attribution (including Heroic's official icon), choose the public
repository/release URLs, set a release version, and complete live acceptance on a
clean supported installation. This development archive has not been published.

## Xbox controllers

Official standard Xbox One and Series X|S controllers use one virtual Xbox Series
output per physical controller. USB and Bluetooth are supported where the model
supports that transport. Pair through KDE before use. HSTN uses the installed
Bazzite driver stack and InputPlumber profiles; it does not install kernel drivers
or update firmware. Xbox 360, Elite-specific features, third-party controllers,
and proprietary wireless adapters are outside this support scope.

Hold Xbox and press View to open HSTN; A selects and B dismisses. Xbox alone
retains launcher behavior. Mixed Xbox and DualSense controllers retain their
respective output families. Xbox routing has fixture-based automated coverage;
live USB/Bluetooth input, rumble, reconnection, suspend/resume, game prompts,
and session transitions still require Bazzite hardware acceptance.

## Legion Go S (experimental)

Lenovo Legion Go S uses the existing InputPlumber composite and preserves its
Steam/Desktop controller output. Hold **Guide**, then press **Quick Access** to open HSTN;
Guide alone retains launcher behavior. Navigate with the D-pad, select with A,
return with B, and scroll app details with L1/R1. HSTN uses Kenney Steam Deck
prompts for handheld input, independently of the emulated controller output.

In Heroic, the known Deck HID/keyboard/mouse combination temporarily becomes
Xbox Elite/keyboard/mouse so Heroic's browser interface can read a gamepad.
Leaving Heroic restores the original output. Existing Xbox outputs and custom
target combinations are preserved. A private runtime journal protects recovery
if setup or cleanup fails; unresolved recovery blocks updates and removal.

Only Go S models 83L3, 83N6, 83Q2, and 83Q3 with controller IDs 1a86:e310/e311
are included. Original Legion Go and Go 2 are not included. HSTN only adopts an
idle Go S composite (interception mode 0); it leaves intercepted composites alone.
InputPlumber has no activation-binding getter, so cleanup restores its default
Guide binding. Custom activation bindings on an idle composite cannot be saved.

Automated fixtures cover detection, routing preservation, and overlay cleanup.
On model 83N6, Steam/Heroic/Desktop round trips, menu A/B, Desktop navigation and
mouse splitting, and native Steam prompts have been verified. Rumble,
suspend/resume, external-controller coexistence, and other Go S models still
need hardware acceptance.

In the Go S **Desktop** menu, the left stick and D-pad navigate HSTN. A selects,
B returns on release, and the shoulder buttons scroll the app review. The right
stick, touchpad, and triggers retain their normal Steam desktop mouse mappings;
Steam must be running for those mappings. Closing HSTN restores the original
InputPlumber profile. Gaming-session interception is unchanged.

This split uses a fixed mapping lease served by the root-owned input guard, and
requires PyYAML in the system Python. Updates to this feature require the full
installer so the system guard is updated as well. The mapping socket accepts
only verified Go S composites from the active local user; it accepts no custom
YAML or commands. Crash/disconnect recovery restores the recorded profile.
Profiles with explicit target overrides or a file-backed profile path are
refused to preserve their configuration.

DeckyPlumber may reload its base profile as Steam's active app changes. While
the Desktop menu is open, HSTN can reapply navigation over that exact saved base
profile. Distinct profile edits remain preserved. If a keyboard/mouse selection
arrives during a reset, HSTN dismisses the menu instead of switching sessions;
reopen it once the other profile manager has settled. This needs the current
system guard and user runtime together; use the full installer for an update.

On KDE Wayland, Steam may ask permission to control input devices when its
controller mouse mapping starts. Allow Steam's request to use those desktop
mouse controls. Until permission is granted, HSTN navigation can work while the
Steam-driven pointer and clicks do not. Steam may request permission again after
a restart or reconnect; see [Steam's portal permission report](https://github.com/ValveSoftware/steam-for-linux/issues/10442).

### Steam Gaming Mode and Bazzite's OpenGamepadUI toggle

The HSTN-managed `ogui-steam` session override uses packaged standard Steam,
with HSTN providing the controller menu. This matches Bazzite's **Toggle
OpenGamepadUI overlay** status: the override file means OpenGamepadUI is disabled.
The packaged Steam arguments and hooks are retained. Enabling OpenGamepadUI
through Bazzite removes that override; HSTN's controller chord is then unavailable
in that session because HSTN preserves the other overlay's input ownership.
HSTN installation/updates restore its managed override. Uninstall restores the
original override, if there was one. An OpenGamepadUI plugin integration is not
included.

For native Go S prompts in Steam, Bazzite's companion
`bazzite-native-steam-input.service` must be enabled. Bazzite's Disable
OpenGamepadUI action normally does this; HSTN preserves the vendor preference
and orders its overlays after that optional setup. If the companion setting is
missing, run from KDE with Steam/Heroic closed:

```sh
systemctl --user stop hstn-desktop-overlay.service
systemctl --user enable --now bazzite-native-steam-input.service
systemctl --user start hstn-desktop-overlay.service
```

In Gaming Mode, HSTN reads Steam's saved display/text scale from
`config/config.vdf` (`InstallConfigStore/UI/display/Current/ScaleFactor`) and
updates its layout when Steam writes a changed preference. It keeps the 25%
compact layout reduction and renders text/artwork at native resolution. KDE
Desktop scaling remains independent. The accessibility magnifier zoom is a
separate setting and is not used. HSTN never edits Steam's scale settings.
