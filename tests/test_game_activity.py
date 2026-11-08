import importlib.util
import contextlib
import io
from unittest.mock import patch
import os
from pathlib import Path
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/game-activity.py'


def load():
    spec = importlib.util.spec_from_file_location('activity', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ActivityTest(unittest.TestCase):
    def test_live_metadata_is_grouped_and_switchers_are_identified(self):
        self.assertTrue(SCRIPT.exists(), 'Read-only activity probe missing')
        module = load()
        with tempfile.TemporaryDirectory() as directory:
            proc = Path(directory)
            def process(pid, env, args):
                p = proc / str(pid); p.mkdir()
                (p / 'environ').write_bytes(b'\0'.join(f'{k}={v}'.encode() for k,v in env.items()) + b'\0')
                (p / 'cmdline').write_bytes(b'\0'.join(a.encode() for a in args) + b'\0')
            process(1, {'SteamAppId': '123'}, ['game'])
            process(2, {'SteamAppId': '123'}, ['sleep', '1'])
            process(3, {'SteamAppId': '456'}, ['bash', '/home/test/.local/bin/switch-to-heroic'])
            process(4, {'HEROIC_APP_NAME': 'abc', 'HEROIC_APP_SOURCE': 'sideload', 'SteamAppId': '0'}, ['game'])
            process(5, {}, ['steamwebhelper'])
            report = module.scan(proc, {'456'}, set())
            groups = {(g['launcher'],g['app_id']):g for g in report['candidates']}
            self.assertEqual(groups[('steam','123')]['pids'], [1,2])
            self.assertFalse(groups[('steam','123')]['switcher'])
            self.assertTrue(groups[('steam','456')]['switcher'])
            self.assertEqual(groups[('heroic','abc')]['pids'], [4])
            self.assertEqual(len(groups),3)
            self.assertEqual(report['errors'], [])

    def test_unreadable_metadata_is_reported_not_silently_safe(self):
        module = load()
        with tempfile.TemporaryDirectory() as directory:
            proc = Path(directory)
            (proc / '123').mkdir()
            (proc / '123/environ').mkdir()  # deterministic read failure, even for root
            report = module.scan(proc, set(), set())
            self.assertTrue(report['errors'])


    def test_check_blocks_game_but_allows_switcher_with_inspection_warnings(self):
        module = load()
        report = {'mode': 'diagnostic-only', 'candidates': [
            {'launcher': 'steam', 'app_id': '456', 'switcher': True, 'pids': [1]}],
            'errors': ['Cannot inspect protected desktop process']}
        with patch.object(module, 'switcher_ids', return_value=({'456'}, set(), [])), patch.object(module, 'scan', return_value=report), contextlib.redirect_stderr(io.StringIO()) as output:
            self.assertEqual(module.main(['--check']), 0)
            self.assertIn('Warning', output.getvalue())
            report['candidates'].append({'launcher': 'heroic', 'app_id': 'abc', 'switcher': False, 'pids': [2]})
            self.assertEqual(module.main(['--check']), 20)
            self.assertIn('abc', output.getvalue())

if __name__ == '__main__':
    unittest.main()
