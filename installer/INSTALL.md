# Installing HSTN

HSTN currently targets **Bazzite KDE with Steam, Heroic Flatpak, Gamescope
session-plus and the tested USB DualSense**. An installer does not establish
support for other distributions/controllers. Install, upgrade and remove from KDE
Desktop with Steam, Heroic and games closed. Installation never logs out, closes
apps, restarts SDDM, reboots or changes your persistent autologin destination.

## From an extracted release or source tree

Requires Python 3.10+. Preview first:

```sh
sh installer/install.sh --dry-run
sh installer/install.sh
```

The normal invocation installs the runtime, commands, session definitions,
Desktop icons/autostart and user units; requests sudo for a separate system
phase; starts the Desktop menu hidden; and runs the installed doctor. The system
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
`--heroic-config-dir /absolute/path`. These selections are retained for doctor,
activity checks and later configuration. Both launchers must be installed even
when library setup is deferred. Multiple Heroic Flatpak deployments are rejected
rather than silently choosing which deployment to configure.

`--user-only` explicitly skips the system phase. It is useful when an administrator
has already provisioned the system components; it is not a complete installation
on a clean system. Doctor still reports missing system prerequisites as failures.

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
hstn doctor
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

After file/service installation, doctor failures mean setup is incomplete, even
though recoverable installed files may remain. WARN/SKIP do not establish live
controller isolation. In particular, Desktop skips live Gamescope routing checks.
Perform Steam and Heroic round trips, repeated restarts, PS/PS+Create, glyphs,
guarded close-and-switch and reboot acceptance manually. Diagnostic captures are
included but never armed by installation. Bluetooth/multiple controllers/general
hotplug and Steam's built-in power-menu lid-guard coverage remain unvalidated.

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
