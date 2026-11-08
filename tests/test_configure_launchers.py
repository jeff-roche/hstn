import importlib.util
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from test_configure_steam import fixture

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/configure-launchers.py'


def load():
    spec = importlib.util.spec_from_file_location('launchers', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class InstalledSelectionTest(unittest.TestCase):
    def test_installer_account_selection_is_reused_without_scanning_other_accounts(self):
        m = load()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            selected = root/'selected config'
            selected.mkdir()
            record = root/'hstn/install.json'
            record.parent.mkdir()
            record.write_text(json.dumps({'version': 1, 'metadata': {'selected_configs': {'steam': str(selected)}}}))
            with patch.dict(m.os.environ, {'XDG_STATE_HOME': str(root)}):
                self.assertEqual(m.detect_config('steam'), selected)


def heroic_fixture(root):
    (root / 'sideload_apps').mkdir(parents=True)
    (root / 'GamesConfig').mkdir()
    games = []
    for target in ('steam', 'desktop'):
        games.append({'runner': 'sideload', 'title': 'Switch to ' + target.capitalize(),
                      'app_name': target, 'install': {'executable': '/usr/bin/flatpak-spawn'},
                      'art_cover': 'old-wide', 'art_square': 'old-portrait'})
        (root / f'GamesConfig/{target}.json').write_text(json.dumps({target: {
            'launcherArgs': f'--host --directory=/home/test /home/test/.local/bin/switch-to-{target}'}}))
    path = root / 'sideload_apps/library.json'
    path.write_text(json.dumps({'games': games}))
    return path


class LaunchersTest(unittest.TestCase):
    def test_subset_changes_only_selected_entry_and_reads_manifest_slots(self):
        module = load()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            library = heroic_fixture(root / 'heroic')
            before = json.loads(library.read_text())
            manifest, assets = module.load_manifest()
            manifest['assets_dir'] = str(assets)
            manifest['launchers']['heroic']['entries']['steam']['slots']['art_square'] = 'icon'
            custom = root / 'manifest.json'
            custom.write_text(json.dumps(manifest))
            module.configure_heroic(library.parents[1], custom, targets=['steam'])
            after = json.loads(library.read_text())
            self.assertEqual(after['games'][1], before['games'][1])
            icon = Path(after['games'][0]['art_square'].removeprefix('file://'))
            self.assertEqual(icon.read_bytes(), (assets / 'switch-to-steam-icon.png').read_bytes())

    def test_all_preflights_before_writing_any_library(self):
        module = load()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            steam = root / 'steam'
            steam.mkdir()
            shortcuts = steam / 'shortcuts.vdf'
            shortcuts.write_bytes(fixture())
            with contextlib.redirect_stderr(io.StringIO()), patch.object(module, 'steam_running', return_value=False), patch.object(module, 'heroic_running', return_value=False):
                result = module.main(['--steam-config-dir', str(steam), '--heroic-config-dir', str(root / 'missing')])
            self.assertEqual(result, 1)
            self.assertEqual(shortcuts.read_bytes(), fixture())
            self.assertFalse((steam / 'grid').exists())
            self.assertFalse(list(steam.glob('*.bak')))

    def test_desktop_subset_does_not_require_or_check_steam(self):
        module = load()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            library = heroic_fixture(root)
            steam_before = json.loads(library.read_text())['games'][0]
            with patch.object(module, 'steam_running', side_effect=AssertionError('Steam must not be checked')), patch.object(module, 'heroic_running', return_value=False):
                result = module.main(['--target', 'desktop', '--heroic-config-dir', str(root)])
            self.assertEqual(result, 0)
            self.assertEqual(json.loads(library.read_text())['games'][0], steam_before)

    def test_default_configures_all_libraries(self):
        module = load()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            steam = root / 'steam'
            steam.mkdir()
            (steam / 'shortcuts.vdf').write_bytes(fixture())
            library = heroic_fixture(root / 'heroic')
            with patch.object(module, 'steam_running', return_value=False), patch.object(module, 'heroic_running', return_value=False):
                result = module.main(['--steam-config-dir', str(steam), '--heroic-config-dir', str(library.parents[1])])
            self.assertEqual(result, 0)
            self.assertTrue((steam / 'grid/2777996481_hero.png').is_file())
            for game in json.loads(library.read_text())['games']:
                self.assertTrue(game['art_cover'].startswith('file://'))
                self.assertTrue(game['art_square'].endswith('-portrait.png'))

    def test_invalid_filter_is_rejected(self):
        module = load()
        manifest, _ = module.load_manifest()
        with self.assertRaisesRegex(ValueError, 'No manifest entries'):
            module.select_entries(manifest, ['steam'], ['desktop'])

    def test_running_launcher_blocks_writes(self):
        module = load()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            library = heroic_fixture(root)
            before = library.read_bytes()
            with contextlib.redirect_stderr(io.StringIO()), patch.object(module, 'heroic_running', return_value=True):
                result = module.main(['--launcher', 'heroic', '--heroic-config-dir', str(root)])
            self.assertEqual(result, 1)
            self.assertEqual(library.read_bytes(), before)
            self.assertFalse((root / 'sideload_apps/artwork').exists())


if __name__ == '__main__':
    unittest.main()
