import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def module():
    spec = importlib.util.spec_from_file_location('install_state', ROOT/'installer/install-state.py')
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class InstallStateTest(unittest.TestCase):
    def setUp(self):
        self.assertTrue((ROOT/'installer/install-state.py').exists(), 'ownership journal is missing')
        self.m = module()
        self.tmp = tempfile.TemporaryDirectory(prefix='hstn state space ')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.path = self.root/'bin/command'
        self.state = self.root/'state/install.json'

    def store(self):
        return self.m.Store(self.state, [self.path])

    def test_repeat_upgrade_remove_restores_original_symlink(self):
        original = self.root/'original'
        original.write_text('untouched')
        self.path.parent.mkdir()
        self.path.symlink_to(original)
        with self.store() as store:
            store.apply({self.path: self.m.file(b'v1', 0o755)})
        with self.store() as store:
            store.apply({self.path: self.m.file(b'v1', 0o755)})
            store.apply({self.path: self.m.file(b'v2', 0o755)})
        self.assertEqual(self.path.read_text(), 'v2')
        with self.store() as store:
            self.assertEqual(store.remove(), [])
        self.assertEqual(os.readlink(self.path), str(original))
        self.assertEqual(original.read_text(), 'untouched')

    def test_interrupted_write_retries_without_losing_original(self):
        self.path.parent.mkdir()
        self.path.write_text('before')
        with self.store() as store:
            real = self.m.restore
            def fail_after_write(path, value):
                real(path, value)
                raise OSError('interrupted')
            with patch.object(self.m, 'restore', side_effect=fail_after_write):
                with self.assertRaises(OSError):
                    store.apply({self.path: self.m.file(b'after', 0o644)})
        self.assertIn('pending', json.loads(self.state.read_text())['files'][str(self.path)])
        with self.store() as store:
            store.apply({self.path: self.m.file(b'after', 0o644)})
            self.assertEqual(store.remove(), [])
        self.assertEqual(self.path.read_text(), 'before')

    def test_user_edits_block_whole_plan_and_survive_removal(self):
        with self.store() as store:
            store.apply({self.path: self.m.file(b'installed', 0o755)})
        self.path.write_text('user edit')
        with self.store() as store:
            with self.assertRaisesRegex(RuntimeError, 'edited'):
                store.apply({self.path: self.m.file(b'upgrade', 0o755)})
            self.assertEqual(store.remove(), [str(self.path)])
        self.assertEqual(self.path.read_text(), 'user edit')
        self.assertTrue(self.state.exists())

    def test_untrusted_journal_path_and_symlink_parent_are_rejected(self):
        outside = self.root/'outside'
        outside.write_text('untouched')
        self.state.parent.mkdir()
        self.state.write_text(json.dumps({'version': 1, 'files': {str(outside): {
            'installed': self.m.file(b'untouched', 0o644), 'previous': None}}}))
        with self.assertRaisesRegex(RuntimeError, 'path'):
            with self.store():
                pass
        self.state.unlink()
        target = self.root/'target'
        target.mkdir()
        self.path.parent.symlink_to(target)
        with self.assertRaisesRegex(RuntimeError, 'symlink'):
            with self.store() as store:
                store.apply({self.path: self.m.file(b'bad', 0o644)})
        self.assertFalse((target/'command').exists())
        self.assertEqual(outside.read_text(), 'untouched')

    def test_lock_excludes_concurrent_install(self):
        with self.store():
            with self.assertRaisesRegex(RuntimeError, 'progress'):
                with self.store():
                    pass
