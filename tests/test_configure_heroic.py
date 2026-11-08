import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/configure-launchers.py'

class HeroicTest(unittest.TestCase):
    def test_preserves_launch_settings_other_games_and_repeat_runs(self):
        self.assertTrue(SCRIPT.is_file(), 'Heroic configuration script is missing')
        spec = importlib.util.spec_from_file_location('heroic_steam', SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'sideload_apps').mkdir()
            (root / 'GamesConfig').mkdir()
            library = root / 'sideload_apps/library.json'
            game = {'app_name': 'example-id', 'title': 'Switch to Steam',
                    'runner': 'sideload', 'install': {'executable': '/usr/bin/flatpak-spawn'},
                    'art_cover': 'old-cover', 'art_square': 'old-square', 'favorite': True}
            other = {'app_name': 'other', 'title': 'Other game'}
            desktop = dict(game, app_name='desktop-id', title='Switch to Desktop')
            original = {'games': [game, desktop, other], 'keep': 123}
            library.write_text(json.dumps(original))
            settings = root / 'GamesConfig/example-id.json'
            settings.write_text(json.dumps({'example-id': {'launcherArgs': '--host --directory=/home/test /home/test/.local/bin/switch-to-steam'}}))
            desktop_settings = root / 'GamesConfig/desktop-id.json'
            desktop_settings.write_text(json.dumps({'desktop-id': {'launcherArgs': '--host --directory=/home/test /home/test/.local/bin/switch-to-desktop'}}))
            desktop_bytes = desktop_settings.read_bytes()
            settings_bytes = settings.read_bytes()
            module.configure_heroic(root)
            actual = json.loads(library.read_text())
            expected = json.loads(json.dumps(original))
            art = root / 'sideload_apps/artwork'
            expected['games'][0]['art_cover'] = (art / 'switch-to-steam-wide.png').as_uri()
            expected['games'][0]['art_square'] = (art / 'switch-to-steam-portrait.png').as_uri()
            expected['games'][1]['art_cover'] = (art / 'switch-to-desktop-wide.png').as_uri()
            expected['games'][1]['art_square'] = (art / 'switch-to-desktop-portrait.png').as_uri()
            self.assertEqual(actual, expected)
            self.assertEqual(desktop_settings.read_bytes(), desktop_bytes)
            self.assertEqual((art / 'switch-to-desktop-wide.png').read_bytes(), (module.ASSETS / 'switch-to-desktop-wide.png').read_bytes())
            self.assertEqual((art / 'switch-to-desktop-portrait.png').read_bytes(), (module.ASSETS / 'switch-to-desktop-portrait.png').read_bytes())
            self.assertEqual(settings.read_bytes(), settings_bytes)
            self.assertEqual((art / 'switch-to-steam-portrait.png').read_bytes(),
                             (module.ASSETS / 'switch-to-steam-portrait.png').read_bytes())
            self.assertEqual((art / 'switch-to-steam-wide.png').read_bytes(),
                             (module.ASSETS / 'switch-to-steam-wide.png').read_bytes())
            backups = list(library.parent.glob('library.json.*.bak'))
            self.assertEqual(len(backups), 1)
            self.assertEqual(json.loads(backups[0].read_text()), original)
            first = library.read_bytes()
            module.configure_heroic(root)
            self.assertEqual(library.read_bytes(), first)
            self.assertEqual(list(library.parent.glob('library.json.*.bak')), backups)

    def test_invalid_existing_launch_settings_leave_library_untouched(self):
        spec = importlib.util.spec_from_file_location('heroic_config', SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'sideload_apps').mkdir()
            (root / 'GamesConfig').mkdir()
            library = root / 'sideload_apps/library.json'
            library.write_text(json.dumps({'games': [{
                'runner': 'sideload', 'title': 'Switch to Steam', 'app_name': 'steam-id',
                'install': {'executable': '/usr/bin/flatpak-spawn'}}]}))
            (root / 'GamesConfig/steam-id.json').write_text(json.dumps({
                'steam-id': {'launcherArgs': '--host /home/test/.local/bin/wrong-wrapper'}}))
            original = library.read_bytes()
            with self.assertRaisesRegex(ValueError, 'switch-to-steam'):
                module.configure_heroic(root)
            self.assertEqual(library.read_bytes(), original)
            self.assertFalse((root / 'sideload_apps/artwork').exists())
            self.assertFalse(list(library.parent.glob('*.bak')))

if __name__ == '__main__':
    unittest.main()
