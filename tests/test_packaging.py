import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def package_module():
    spec = importlib.util.spec_from_file_location('hstn_package', ROOT/'installer/package.py')
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class PackagingTest(unittest.TestCase):
    def test_all_installed_command_targets_are_executable_in_release(self):
        spec = importlib.util.spec_from_file_location('installer_modes', ROOT/'installer/install-hstn.py')
        installer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(installer)
        with tempfile.TemporaryDirectory() as folder:
            path = package_module().build(ROOT, Path(folder))
            with tarfile.open(path) as archive:
                for command, relative in installer.LINKS.items():
                    member = archive.getmember('hstn-' + package_module().version(ROOT) + '/' + relative)
                    self.assertTrue(member.mode & 0o111, f'{command}: {relative} is not executable')

    def test_archive_is_deterministic_complete_and_runs_away_from_checkout(self):
        self.assertTrue((ROOT/'installer/package.py').exists(), 'release builder is missing')
        m = package_module()
        with tempfile.TemporaryDirectory() as folder:
            dest = Path(folder)
            first = m.build(ROOT, dest/'first')
            second = m.build(ROOT, dest/'second')
            self.assertEqual(first.read_bytes(), second.read_bytes())
            self.assertEqual((first.parent/'SHA256SUMS').read_text().split()[0],
                             hashlib.sha256(first.read_bytes()).hexdigest())
            with tarfile.open(first) as archive:
                names = archive.getnames()
                self.assertFalse(any('__pycache__' in n or '.superpowers' in n or 'diagnostics/' in n for n in names))
                archive.extractall(dest/'extracted', filter='data')
            release = next((dest/'extracted').iterdir())
            # Instantiate the consumer from the extracted tree: CLI --help alone
            # cannot catch omitted resources loaded only during Desktop startup.
            spec = importlib.util.spec_from_file_location('packaged_desktop_support', release/'scripts/desktop-overlay-support.py')
            support = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(support)
            from unittest.mock import patch
            runtime = dest/'runtime'
            runtime.mkdir()
            with patch.object(support.KWinFocus, 'call', return_value='1'):
                focus = support.KWinFocus(runtime, 'HSTN test')
                self.assertTrue(focus.path.is_file())
                self.assertNotIn('__HSTN_PID__', focus.path.read_text())
                focus.close()
            result = subprocess.run(['python3', '-B', str(release/'scripts/hstn'), '--help'], capture_output=True, text=True, cwd='/tmp')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('install', result.stdout)
            result = subprocess.run(['sh', str(release/'installer/install.sh'), '--help'],
                                    capture_output=True, text=True, cwd='/tmp')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('--dry-run', result.stdout)
            for name in ('heroic-gamescope', 'switch-to-steam', 'switch-to-heroic', 'switch-to-desktop'):
                self.assertTrue(os.access(release/'scripts'/name, os.X_OK), name)
            manifest = json.loads((release/'manifest.json').read_text())
            for destination in manifest['destinations'].values():
                for asset in destination['images'].values():
                    self.assertTrue((release/manifest['assets_dir']/asset).is_file(), asset)

    def test_destdir_stages_system_files_without_touching_home(self):
        self.assertTrue((ROOT/'installer/package.py').exists(), 'release builder is missing')
        with tempfile.TemporaryDirectory() as folder:
            dest = Path(folder)
            package_module().stage(ROOT, dest)
            self.assertTrue((dest/'usr/lib/hstn/manifest.json').is_file())
            self.assertEqual(os.readlink(dest/'usr/bin/hstn'), '../lib/hstn/scripts/hstn')
            self.assertTrue((dest/'usr/libexec/session-switch-input-guard.py').is_file())
            self.assertIn('/usr/libexec/session-switch-input-guard.py',
                          (dest/'usr/lib/systemd/system/session-switch-input-guard.service').read_text())
            self.assertFalse((dest/'home').exists())

    def test_inventory_rejects_missing_files_before_building(self):
        self.assertTrue((ROOT/'installer/package.py').exists(), 'release builder is missing')
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises((ValueError, FileNotFoundError)):
                package_module().inventory(Path(folder))
