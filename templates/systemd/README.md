# HSTN services

The permanent system input guard is manually installed, enabled and boot-tested;
the Gamescope overlay user service is also deployed and live-tested. Unit names
retain `session-switch-*` for compatibility; see [BRANDING.md](../../docs/BRANDING.md).
Source unit descriptions now use HSTN. Updating the root-owned installed unit
requires repeating the privileged copy below; its older description does not
affect operation. The commands below document manual installation and maintenance.

## KDE Desktop overlay

`hstn desktop install` installs `hstn-desktop-overlay.service`, a KDE autostart
entry, and three Desktop/application-menu icons. The autostart helper captures
the current KDE environment in `%t/hstn-desktop-overlay.env`; it does not reuse
the Gamescope environment file. `Type=dbus` waits for `org.hstn.DesktopOverlay`.
Startup resolves graphical variables from the current KDE Plasma bus owner's
process, verifying its UID/name, so a terminal retained across session changes
cannot replace the current display authorization with an old session's values.
The service is part of `graphical-session.target`, runs hidden, and exits with
the Desktop session. Do not enable it globally or import stale display variables.

The Desktop and Gamescope units conflict, with Gamescope ordered after Desktop
cleanup. A shared runtime flock, inherited by the restoration watchdog, prevents
overlapping controller ownership even if the UI crashes. The existing root input
guard remains required. Desktop startup preserves pre-existing InputPlumber
owners; keyboard/mouse menu access remains available when controller setup fails.
The focus bridge loads only HSTN's own scoped KWin script and unloads it on exit.
Steam and Desktop now use Heroic's existing single-PlayStation coordinator for
the tested USB DualSense too; only the physical HID source exposes a virtual pad,
while owned button/motion/touchpad siblings remain suppressed. Steam's preflight
requires this output to be ready before starting the client.

Inspect with `hstn desktop status` and
`journalctl --user -u hstn-desktop-overlay.service`. Restart after resolving input
ownership/guard issues with `systemctl --user restart hstn-desktop-overlay.service`.
Use `hstn desktop remove` to stop/remove this integration and restore still-owned
backups. Removal preserves edited files and reports conflicts. The general HSTN
installer and fresh-login/session-transition validation remain separate work.

## Temporary transition lid guard

`session-switch` invokes `~/.local/bin/session-transition-guard.py` after game
checks and before selecting or ending a session. It starts a collected transient
user service named `hstn-transition-lid-<uuid>.service`. `systemd-inhibit` acquires
only `handle-lid-switch`; the holder reports readiness before logout can proceed,
then exits after30 seconds. Startup is bounded to5 seconds and total runtime to40.
No persistent unit is enabled and global logind/PowerDevil policy is unchanged.

The guard survives graphical-session target teardown, but not termination of the
entire user manager. This host has Linger=no and default UserStopDelaySec=10.
Observed SDDM transitions open the next PAM session immediately and retain the
manager. A login gap longer than10 seconds can shorten protection; do not claim
full coverage for failed/delayed logins or enable lingering as a silent workaround.
The future installer/recovery design must account for that boundary.

Inspect `systemd-inhibit --list` and
`journalctl --user -u 'hstn-transition-lid-*'`. A new session switch acquires its
own bounded inhibitor. If acquisition fails, the switcher refuses before logout.

# Permanent input isolation service

`session-switch-input-guard.service` is the system component that maintains the
known InputPlumber runtime HID-rule correction. It runs continuously across
sessions and reboots when enabled, without a diagnostic marker or time limit.
It does not enable controller management, launch games or switch sessions.

The service runs a root-owned copy of `scripts/session-switch-input-guard.py`
at `/usr/local/libexec/session-switch-input-guard.py`. Runtime state is under
`/run/session-switch-input-guard/`; only the active PID/start-time status is
publicly readable. Rule backups remain private to root. Root does not execute
code from the user's repository or home directory.

Only affected root-owned, non-writable-by-others generated physical HID rules
under `/run/udev/rules.d` are edited. Already corrected rules and virtual sources
are untouched. The service journals original content and file identity before
writing; on normal stop it restores surviving matching owned changes. On an
unexpected failure it retains corrections and the journal for restart. Recovery
retries udev reload/trigger/settle before publishing readiness, even if rule text
was corrected before a crash. InputPlumber can remove/regenerate rules normally.

The system unit starts with InputPlumber and at boot, restarts after failures,
and coordinates stop/restart with InputPlumber. Its exclusive lock also prevents
the old temporary diagnostic helper from running concurrently.

## Manual install

Run from Desktop after any temporary diagnostic test has ended. If the old
transient unit is still active, stop it first:

```bash
sudo systemctl stop session-switch-input-diagnostic.service
```

Install the two root-owned files and enable the service:

```bash
cd /var/home/jroche/repos/hstn
sudo install -D -o root -g root -m 0755 scripts/session-switch-input-guard.py /usr/local/libexec/session-switch-input-guard.py
sudo install -D -o root -g root -m 0644 templates/systemd/session-switch-input-guard.service /etc/systemd/system/session-switch-input-guard.service
sudo systemctl daemon-reload
sudo systemctl enable --now session-switch-input-guard.service
systemctl status session-switch-input-guard.service --no-pager
```

No installer is provided yet. The future installer must perform these same
privileged file copies, reload/enable steps and status checks. Installing a
root-executed symlink into the user checkout is not equivalent. Source changes
to the root helper require repeating its install command and restarting the
service from Desktop.

User-side launcher wrappers/status helper have been updated in this workspace's
existing ~/.local/bin deployment. Normal Steam and Heroic use the permanent
service automatically; Steam's explicit opt-out and OpenGamepadUI ownership
bypass remain. Both verify actual controller isolation before enabling the
custom menu. The overlay disables itself if guard availability is lost.
If isolation is unavailable, the launcher continues without our overlay.

After successful installation, switch normally and use PS+Create. No `sudo
systemd-run` diagnostic or `.once` marker is required. Optional capture remains
available through the existing markers or `SESSION_SWITCH_DIAGNOSTICS=1` for
Heroic. Logging is separate from the root correction.

## Verify / maintain

```bash
journalctl -u session-switch-input-guard.service --no-pager -n 40
systemctl is-enabled session-switch-input-guard.service
```

At idle, "Input guard ready; watching across sessions" is expected. Corrections
are logged only when managed HID rules appear. An empty runtime rules directory
on Desktop is normal; the service remains active for the next session.

Stop/restart/uninstall from Desktop with games closed, because stopping the
service withdraws the correction and disables the overlay. To uninstall:

```bash
sudo systemctl disable --now session-switch-input-guard.service
sudo rm /etc/systemd/system/session-switch-input-guard.service /usr/local/libexec/session-switch-input-guard.py
sudo systemctl daemon-reload
```

Verification before manual installation: 90 unit tests pass, including
multi-session regeneration, restart journal recovery with a failed udev refresh,
rollback ownership, symlink/writable-file rejection, status PID reuse, systemd
notification, Steam normal/opt-out routing and overlay guard-loss handling.
`systemd-analyze verify` accepts the unit. Independent code review found a
missing refresh-retry path; it was reproduced, fixed, regression-tested and
re-reviewed without remaining blockers. Privileged installation and live service behavior were subsequently verified,
including a reboot and Steam/Valheim close-and-switch; see the handoff checkpoint.
