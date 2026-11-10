# Releases and maintenance ownership

Jeff Roche ([@jeff-roche](https://github.com/jeff-roche)) owns release decisions,
license/provenance review, version changes, release notes, tags, uploaded
artifacts, and support-scope updates. Contributors can prepare release PRs;
the maintainer reviews and publishes them. There is no automatic publication or
update daemon. See [SUPPORT.md](../SUPPORT.md) for response and support policy.

## Prepare a release

1. Work from a reviewed `main` commit with a clean checkout and passing Checks.
   Resolve release blockers and review provenance for new or changed assets in
   [assets/README.md](../assets/README.md). Confirm third-party licenses and
   notices still match the actual shipped bytes. Verify that the archive and
   native staging tree include them.
2. Complete live acceptance on supported Bazzite KDE hardware: clean install,
   upgrade, uninstall and recovery; Steam/Heroic/Desktop round trips; explicit
   app review and Cancel; controller activation and Guide passthrough; hotplug,
   reconnect and reboot. For each controller/transport advertised as validated,
   record model, firmware where known, OS image, and results. Mark untested
   combinations clearly rather than promoting fixture coverage to live support.
3. Set `VERSION` to the intended release (for example `0.1.0`), move Unreleased
   entries in [CHANGELOG.md](../CHANGELOG.md) to that version with its date, and
   include changes, upgrade/recovery guidance, known limitations, and the live
   acceptance evidence. Until this happens, `0.1.0-dev` remains an unreleased
   development version.
4. Build from that exact commit in fresh output directories:

   ```sh
   python3 -B installer/package.py --output /tmp/hstn-release
   python3 -B installer/package.py --destdir /tmp/hstn-package-root
   cd /tmp/hstn-release
   sha256sum --check SHA256SUMS
   ```

   Packaging tests compare two builds for identical archive bytes. Check an
   extracted archive independently of the checkout. Run installation previews
   and live acceptance only on the supported test machine; hosted CI cannot
   establish Bazzite session or controller support.
5. After review, the maintainer creates `vVERSION` at that commit and a GitHub
   Release at <https://github.com/jeff-roche/hstn/releases>. Upload the exact
   `hstn-VERSION.tar.gz` and `SHA256SUMS`, copy the version's changelog entries,
   and state the tested configuration and remaining limitations. Mark previews
   as prereleases. Keep the tag, source commit, archive version, and notes aligned.
6. Verify the published download URLs and checksums. The bootstrap currently
   has no default host: document the verified release base explicitly, using
   `https://github.com/jeff-roche/hstn/releases/download` with `--version VERSION`
   only once matching assets have been published. Do not advertise an untested
   installer URL or a release that does not exist.

## Fixes and dependencies

Fixes target `main` and the latest published release; backports are at the
maintainer's discretion. Record regressions and any upgrade/recovery implications
in release notes. Preserve compatibility identifiers and installation ownership
through upgrades. A failed validation is a release blocker until resolved or the
advertised scope is narrowed explicitly.

When updating pinned GitHub Actions or test dependencies, review their upstream
release notes, update the pin and version comment together, and run Checks.
GitHub Actions have read-only repository access and publication remains manual.
Actual RPM/.deb recipes and support for distributions beyond Bazzite are outside
the current release process.
