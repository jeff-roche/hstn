# Getting help

HSTN is an experimental, volunteer-maintained project. Jeff Roche
([@jeff-roche](https://github.com/jeff-roche)) owns triage, review, and releases.
There is no guaranteed response time, release schedule, or long-term support
branch. The latest `main` commit is the development reference; after releases
begin, fixes target the latest release and `main`. Older versions may require
an upgrade before investigation.

## Supported environment

The target is Bazzite KDE with Steam, Heroic Flatpak, Gamescope session-plus,
and InputPlumber. The [README](README.md) and [installation guide](installer/INSTALL.md)
describe exact prerequisites and the current controller scope: DualSense,
standard Xbox One/Series, and Lenovo Legion Go S. Support for a device does not
mean every transport, firmware, or session path has passed live acceptance.
Those documents distinguish fixture coverage from hardware verification.

Other distributions, desktop environments, third-party controllers, Xbox
wireless adapters, and additional handhelds have no support commitment. Reports
and focused contributions are welcome; working on one machine does not establish
general support. HSTN uses the installed OS drivers and does not install drivers
or update controller firmware.

## Reporting problems

Run `hstn mechanic --verbose` and review the [technical reference](docs/REFERENCE.md).
Use `~/.local/bin/hstn` if the command is missing from PATH. Search
[existing issues](https://github.com/jeff-roche/hstn/issues) before opening a bug
report. Include the HSTN version/commit, Bazzite image, controller model and
transport, session, steps to reproduce, and sanitized diagnostic output.
Share only the output needed to explain the problem; remove account details,
tokens, private paths, and window titles. Diagnostic captures are opt-in.

Save desktop work and close games before attempting session-switch acceptance.
Switching away from Desktop logs out KDE. Installation, routing, or rollback
failures should include the original error and recovery state description;
preserve ownership/backup records for recovery as described in the installation
guide. Keyboard/mouse and the Desktop launcher are the recovery paths when
controller routing is unavailable.

Report HSTN bugs here. Driver, launcher, and OS failures may need upstream
investigation; include evidence that separates the HSTN behavior from the
upstream failure. Maintainers may request more information or close reports
that cannot be reproduced within the supported scope.
