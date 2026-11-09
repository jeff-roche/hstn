# HSTN

**HSTN**, pronounced “Houston,” is mission control for Linux gaming sessions.
Switch between Steam, Heroic, and KDE Desktop from a controller-friendly menu,
with a chance to review running apps before closing them and switching.

## What you need

- **Bazzite KDE** with Steam and Heroic Flatpak installed and opened at least once.
- **Python 3.10+**, Gamescope session-plus, and InputPlumber. The installer checks
  for required software and tells you what is missing.
- A **DualSense controller** for controller navigation. Connect over USB, or pair
  through KDE’s Bluetooth settings. The Desktop menu also supports keyboard and mouse.

USB DualSense has been tested on hardware. Bluetooth and multiple-controller
support have automated tests; live hardware validation is still in progress.

## Install

Open a terminal in **KDE Desktop Mode** with your games closed:

```sh
git clone https://github.com/jeff-roche/hstn.git
cd hstn
sh installer/install.sh --dry-run
sh installer/install.sh
```

If you already have the checkout, start with the installer commands. Close Steam
and Heroic before installing. The installer asks for administrator access when
needed and offers to add HSTN shortcuts to each launcher. Installation keeps you
in Desktop Mode.

To let the installer close running launchers and configure their shortcuts:

```sh
sh installer/install.sh -c -y
```

- `-c` authorizes closing running launchers without extra prompts. Games must be closed.
- `-y` accepts shortcut setup for every detected launcher.
- `--dry-run` previews changes without closing apps or changing files.

See the [installation guide](installer/INSTALL.md) for requirements, offline
installation, upgrades, and recovery.

## Use HSTN

Hold **PS**, then press **Create** to open the menu. Pressing PS alone keeps the
launcher’s normal behavior.

- Use the **D-pad** to choose Steam, Heroic, or Desktop.
- Press **Cross** to select. Review any running apps and confirm before closing them.
- Press **Circle** or **Escape** to dismiss the menu.

On KDE Desktop, use **Open HSTN**, **Switch to Steam**, or **Switch to Heroic** from
the desktop or application menu. **Save your desktop work before switching**:
switching away from Desktop logs out the KDE session.

You can connect supported controllers after login. HSTN watches for connections
and reconnections; Steam and Heroic can start with no controller attached.

## Need help?

Check your installation with:

```sh
hstn mechanic
```

Mechanic shows warnings and failures without changing anything. Add `--verbose`
to see every check. If `hstn` is unavailable in your terminal, use
`~/.local/bin/hstn` instead.

If the controller menu does not respond, try **Open HSTN** on Desktop. Close Steam,
reconnect the controller, and let HSTN initialize before reopening Steam. For more
help, see the [technical reference](docs/REFERENCE.md).

To add launcher shortcuts later, close the launchers and run:

```sh
hstn configure
```

## Update or uninstall

To update, run the installer from a newer checkout or extracted release.

To uninstall, return to KDE Desktop, close games and launchers, then run:

```sh
hstn uninstall
```

HSTN removes files it owns and restores saved originals where safe. Your games
and unrelated launcher entries are preserved.

## Contributing

See [Repository Guidelines](AGENTS.md) for development commands and conventions,
and the [design guide](docs/DESIGN.md) for artwork guidance.
