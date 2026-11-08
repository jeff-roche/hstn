import hashlib
import io
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class BootstrapTest(unittest.TestCase):
    def setUp(self):
        self.assertTrue((ROOT/'installer/install.sh').is_file(), 'shell bootstrap is missing')
        self.tmp = tempfile.TemporaryDirectory(prefix='hstn bootstrap ')
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        (self.folder/'installer').mkdir()
        self.script = self.folder/'installer/install.sh'
        self.script.write_bytes((ROOT/'installer/install.sh').read_bytes())
        self.marker = self.folder/'executed'

    def archive(self, unsafe=False):
        path = self.folder/'hstn-1.2.3.tar.gz'
        with tarfile.open(path, 'w:gz') as archive:
            source = ("import pathlib, sys\npathlib.Path(" + repr(str(self.marker)) + ").write_text(' '.join(sys.argv[1:]))\n").encode()
            for name, data in [('hstn-1.2.3/installer/install.py', source), ('hstn-1.2.3/VERSION', b'1.2.3\n')]:
                member = tarfile.TarInfo(name)
                member.size = len(data)
                archive.addfile(member, io.BytesIO(data))
            if unsafe:
                member = tarfile.TarInfo('../escaped')
                member.size = 3
                archive.addfile(member, io.BytesIO(b'bad'))
        return path, hashlib.sha256(path.read_bytes()).hexdigest()

    def execute(self, *args, env=None):
        return subprocess.run(['sh', str(self.script), *args], capture_output=True, text=True, env=env)

    def test_verified_offline_archive_forwards_arguments_with_spaces(self):
        archive, digest = self.archive()
        result = self.execute('--archive', str(archive), '--sha256', digest,
                              '-y', '--dry-run', '--steam-config-dir', '/a space/config')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.marker.read_text(), '-y --dry-run --steam-config-dir /a space/config')

    def test_checksum_failure_never_executes_payload(self):
        archive, digest = self.archive()
        result = self.execute('--archive', str(archive), '--sha256', '0'*64)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('checksum', result.stderr.lower())
        self.assertFalse(self.marker.exists())

    def test_archive_traversal_is_rejected_before_execution(self):
        archive, digest = self.archive(unsafe=True)
        result = self.execute('--archive', str(archive), '--sha256', digest)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.marker.exists())
        self.assertFalse((self.folder/'escaped').exists())

    def test_download_requires_version_and_release_url(self):
        result = self.execute()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('--release-base-url', result.stderr)
        self.assertFalse(self.marker.exists())

    def test_https_download_and_failed_download(self):
        archive, digest = self.archive()
        (self.folder/'SHA256SUMS').write_text(digest + '  ' + archive.name + '\n')
        bin_dir = self.folder/'bin'
        bin_dir.mkdir()
        curl = bin_dir/'curl'
        curl.write_text('#!/usr/bin/env python3\nimport os, pathlib, shutil, sys\n'
                        'if os.environ.get("FAIL_DOWNLOAD"): sys.exit(22)\n'
                        'args=sys.argv[1:]\nout=args[args.index("-o")+1]\n'
                        'shutil.copyfile(pathlib.Path(os.environ["FIXTURES"])/args[-1].rsplit("/",1)[-1],out)\n')
        curl.chmod(0o755)
        env = dict(os.environ, PATH=str(bin_dir)+os.pathsep+os.environ['PATH'], FIXTURES=str(self.folder))
        result = self.execute('--version', '1.2.3', '--release-base-url', 'https://example.invalid/releases', '--dry-run', env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.marker.read_text(), '--dry-run')
        self.marker.unlink()
        result = self.execute('--version', '1.2.3', '--release-base-url', 'https://example.invalid/releases', env=dict(env, FAIL_DOWNLOAD='1'))
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.marker.exists())

    def test_extracted_distribution_uses_local_installer(self):
        (self.folder/'installer/install.py').write_text('import sys\nprint("local installer", *sys.argv[1:])\n')
        (self.folder/'VERSION').write_text('1.2.3\n')
        result = self.execute('--dry-run')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('local installer --dry-run', result.stdout)
