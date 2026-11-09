# HSTN

**HSTN**, pronounced “Houston,” is mission control for Linux gaming sessions.
Switch between Steam, Heroic, and KDE Desktop from a controller-friendly menu,
with a chance to review running apps before closing them and switching.

## What you need

- **Bazzite KDE** with Steam and Heroic Flatpak installed and opened at least once.
- **Python 3.10+**, Gamescope session-plus, and InputPlumber. The installer checks
  for required software and tells you what is missing.
- A **Legion Go S, DualSense, Xbox One, or Xbox Series X|S controller** for controller navigation. Connect external controllers over USB, or pair
  through KDE’s Bluetooth settings. The Desktop menu also supports keyboard and mouse.

USB DualSense has been tested on hardware. Xbox support requires live hardware
validation; it uses the installed Bazzite controller drivers. Bluetooth and multiple-controller
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
launcher’s normal behavior. On Xbox, hold **Xbox**, then press **View**;
Xbox alone keeps the launcher’s normal behavior.

- Use the **D-pad** to choose Steam, Heroic, or Desktop.
- Press **A / Cross** to select. Review any running apps and confirm before closing them.
- Press **B / Circle** or **Escape** to dismiss the menu.

On KDE Desktop, use **Open HSTN**, **Switch to Steam**, or **Switch to Heroic** from
the desktop or application menu. **Save your desktop work before switching**:
switching away from Desktop logs out the KDE session.

You can connect supported controllers after login. HSTN watches for connections
and reconnections; Steam and Heroic can start with no controller attached.
A brief bottom-right HSTN notification shows physical controller connections
and disconnections, including USB or Bluetooth. Notifications do not take focus;
connection detection does not establish that controller routing is ready.

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

While HSTN is closed on **Desktop**, all controls retain their existing Steam
desktop mappings, including A/B and D-pad menu navigation. Only the completed
Guide + Quick Access chord is consumed to open HSTN.

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
reopen it once the other profile manager has settled.

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
