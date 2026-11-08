import json
from pathlib import Path
import shlex
import tempfile
import unittest
from unittest.mock import patch
from test_configure_launchers import load
from test_configure_steam import fixture


def make_home(root):
    home = root / 'home with spaces'
    for target in ('heroic', 'steam', 'desktop'):
        path = home / '.local/bin' / f'switch-to-{target}'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('#!/bin/sh\nexit 0\n')
        path.chmod(0o755)
    return home


class CreateShortcutsTest(unittest.TestCase):
    def test_steam_first_shortcut_has_launch_fields_artwork_and_stable_id(self):
        module = load()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); home = make_home(root)
            config = root / 'steam'; config.mkdir()
            with patch.object(module.Path, 'home', return_value=home):
                module.configure_steam(config)
                first = (config / 'shortcuts.vdf').read_bytes()
                games = module.read_vdf(first)['shortcuts']
                self.assertEqual(len(games), 1)
                game = next(iter(games.values()))
                self.assertEqual(game['AppName'], 'Switch to Heroic')
                self.assertEqual(game['Exe'], f'"{home}/.local/bin/switch-to-heroic"')
                self.assertEqual(game['StartDir'], f'"{home}/.local/bin"')
                self.assertEqual(game['LaunchOptions'], '')
                self.assertTrue(game['appid'] & 0x80000000)
                self.assertTrue((config / f'grid/{game["appid"]}p.png').is_file())
                module.configure_steam(config)
                self.assertEqual(first, (config / 'shortcuts.vdf').read_bytes())

    def test_steam_appends_without_changing_unrelated_shortcut(self):
        module = load()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); home = make_home(root)
            source = fixture(); position = source.index(b'\x001\0')
            unrelated = source[:position] + b'\x08\x08'
            (root / 'shortcuts.vdf').write_bytes(unrelated)
            with patch.object(module.Path, 'home', return_value=home):
                module.configure_steam(root)
            actual = module.read_vdf((root / 'shortcuts.vdf').read_bytes())['shortcuts']
            self.assertEqual(actual['0'], module.read_vdf(unrelated)['shortcuts']['0'])
            self.assertEqual(len(actual), 2)

    def test_heroic_creates_both_games_and_native_host_launch_arguments(self):
        module = load()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); home = make_home(root)
            config = root / 'heroic'; config.mkdir()
            with patch.object(module.Path, 'home', return_value=home):
                module.configure_heroic(config)
                library = config / 'sideload_apps/library.json'
                first = library.read_bytes()
                games = json.loads(first)['games']
                self.assertEqual(len(games), 2)
                self.assertEqual(len({g['app_name'] for g in games}), 2)
                for game, target in zip(games, ('steam', 'desktop')):
                    self.assertEqual(game['title'], 'Switch to ' + target.capitalize())
                    self.assertEqual(game['install']['platform'], 'linux')
                    self.assertEqual(game['install']['executable'], '/usr/bin/flatpak-spawn')
                    settings = json.loads((config / f'GamesConfig/{game["app_name"]}.json').read_text())
                    self.assertEqual(shlex.split(settings[game['app_name']]['launcherArgs']),
                                     ['--host', f'--directory={home}', str(home / f'.local/bin/switch-to-{target}')])
                    self.assertTrue(game['art_square'].endswith('-portrait.png'))
                module.configure_heroic(config)
                self.assertEqual(library.read_bytes(), first)

    def test_subset_creates_only_requested_game(self):
        module = load()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); home = make_home(root)
            with patch.object(module.Path, 'home', return_value=home):
                module.configure_heroic(root, targets=['desktop'])
            games = json.loads((root / 'sideload_apps/library.json').read_text())['games']
            self.assertEqual([g['title'] for g in games], ['Switch to Desktop'])

    def test_missing_wrapper_leaves_everything_untouched(self):
        module = load()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); home = make_home(root)
            (home / '.local/bin/switch-to-desktop').unlink()
            config = root / 'heroic'; config.mkdir()
            with patch.object(module.Path, 'home', return_value=home):
                with self.assertRaisesRegex(ValueError, 'switch-to-desktop'):
                    module.configure_heroic(config)
            self.assertEqual(list(config.iterdir()), [])


    def test_duplicate_heroic_entries_are_rejected_without_writes(self):
        module = load()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'sideload_apps').mkdir()
            library = root / 'sideload_apps/library.json'
            game = {'runner': 'sideload', 'title': 'Switch to Steam', 'app_name': 'one'}
            library.write_text(json.dumps({'games': [game, dict(game, app_name='two')]}))
            before = library.read_bytes()
            with self.assertRaisesRegex(ValueError, 'duplicate'):
                module.configure_heroic(root, targets=['steam'])
            self.assertEqual(library.read_bytes(), before)
            self.assertFalse((root / 'GamesConfig').exists())

    def test_partial_heroic_library_preserves_existing_entry_and_settings(self):
        module = load()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); home = make_home(root)
            config = root / 'heroic'; config.mkdir()
            with patch.object(module.Path, 'home', return_value=home):
                module.configure_heroic(config, targets=['steam'])
                library = config / 'sideload_apps/library.json'
                steam = json.loads(library.read_text())['games'][0]
                settings = config / f'GamesConfig/{steam["app_name"]}.json'
                previous_settings = settings.read_bytes()
                module.configure_heroic(config)
                games = json.loads(library.read_text())['games']
                self.assertEqual(games[0], steam)
                self.assertEqual(settings.read_bytes(), previous_settings)
                self.assertEqual(len(games), 2)

if __name__ == '__main__':
    unittest.main()
