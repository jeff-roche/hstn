# Changelog

## Unreleased

Current development version: `0.1.0-dev`. No public release has been published.

### Added

- Controller-friendly Steam, Heroic, and KDE Desktop switching with explicit
  app review before closing, cancellation, and guarded session transitions.
- Standalone installation, upgrade, uninstall and recovery, launcher shortcut
  configuration, read-only `hstn mechanic`, reproducible archives, and native
  package staging.
- Native Launch Deck overlay, controller connection notifications, and
  PlayStation, Xbox, keyboard, and handheld prompts.
- DualSense and standard Xbox One/Series controller routing with USB/Bluetooth
  hotplug coverage, plus Lenovo Legion Go S input profiles and display scaling.
- Project licensing and asset notices, issue forms, automated tests and package
  checks, and documented release ownership and support expectations.
- Maintainer-confirmed GPT provenance for custom artwork, with HSTN's rights
  in those assets available under MIT; third-party asset licenses are preserved.

### Changed

- Input-rule regression tests use the shipped guard and synthetic data, so a
  clean checkout no longer depends on ignored prototypes or machine captures.
- Desktop startup tests supply their own KDE environment instead of relying on
  the developer's graphical session.

### Upgrade and recovery

- Install or upgrade from KDE Desktop with games closed; see
  [installer/INSTALL.md](installer/INSTALL.md). Preserve ownership records and
  backups if installation or removal reports a conflict.
- When upgrading from a version that allowed Steam to open a physical controller
  directly, close Steam and reconnect the controller once before testing routing.

### Known limitations

- Bazzite KDE is the target environment. Fixture tests and offscreen UI checks
  do not establish live controller isolation or session-switch acceptance.
- USB DualSense has prior hardware testing. The current installer guide records
  remaining Xbox, Bluetooth, multiple-controller, and handheld acceptance needs.
- Published shell-installer downloads, RPM/.deb recipes, and other distribution
  support are not available. A CI artifact is a development build.
