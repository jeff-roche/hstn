import importlib.util
import json
import shlex
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), ROOT/('installer' if name in ('install-hstn', 'install-system', 'install-state', 'clean-installation', 'remove-launcher-assets') else 'scripts')/f'{name}.py')
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m


class RemoveLauncherAssetsTest(unittest.TestCase):
    def setUp(self):
        self.assertTrue((ROOT/'installer/remove-launcher-assets.py').is_file(), 'launcher removal is missing')
        self.m = load('remove-launcher-assets')
        self.config = load('configure-launchers')
        self.tmp = tempfile.TemporaryDirectory(prefix='hstn remove space ')
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)

    def test_steam_removes_only_host_shortcuts_and_their_artwork(self):
        config = self.home/'Steam config'; config.mkdir()
        managed = {'appid': 123, 'AppName': 'Switch to Heroic', 'Exe': f'"{self.home}/.local/bin/switch-to-heroic"'}
        unrelated = {'appid': 456, 'AppName': 'My Game', 'Exe': '/games/my-game'}
        same_name = {'appid': 789, 'AppName': 'Switch to Heroic', 'Exe': '/games/other-game'}
        path = config/'shortcuts.vdf'
        path.write_bytes(self.config.encode_vdf({'shortcuts': {'0': managed, '1': unrelated, '2': same_name}}))
        grid = config/'grid'; grid.mkdir()
        (grid/'123p.png').write_bytes(b'owned art')
        (grid/'456p.png').write_bytes(b'other art')
        files = self.m.steam_files(config, self.home)
        self.m.apply(files)
        data = self.config.read_vdf(path.read_bytes())['shortcuts']
        self.assertEqual(list(data.values()), [unrelated, same_name])
        self.assertFalse((grid/'123p.png').exists())
        self.assertEqual((grid/'456p.png').read_bytes(), b'other art')
        self.assertEqual(self.m.steam_files(config, self.home), {})

    def test_heroic_removes_matching_settings_and_art_preserving_other_games(self):
        config = self.home/'Heroic config'
        (config/'sideload_apps/artwork').mkdir(parents=True)
        (config/'GamesConfig').mkdir()
        art = config/'sideload_apps/artwork/switch-to-steam-wide.png'; art.write_bytes(b'art')
        managed = {'app_name': 'hstn-id', 'title': 'Switch to Steam', 'runner': 'sideload',
                   'install': {'executable': '/usr/bin/flatpak-spawn'}, 'art_cover': art.as_uri()}
        other = {'app_name': 'game-id', 'title': 'My Game', 'runner': 'sideload',
                 'install': {'executable': '/games/real'}}
        library = config/'sideload_apps/library.json'
        library.write_text(json.dumps({'games': [managed, other], 'metadata': {'keep': True}}))
        settings = config/'GamesConfig/hstn-id.json'
        settings.write_text(json.dumps({'hstn-id': {'launcherArgs': shlex.join(['--host', '--directory=' + str(self.home), str(self.home/'.local/bin/switch-to-steam')])}}))
        other_settings = config/'GamesConfig/game-id.json'; other_settings.write_text('keep')
        self.m.apply(self.m.heroic_files(config, self.home))
        self.assertEqual(json.loads(library.read_text()), {'games': [other], 'metadata': {'keep': True}})
        self.assertFalse(settings.exists()); self.assertFalse(art.exists())
        self.assertEqual(other_settings.read_text(), 'keep')
        self.assertEqual(self.m.heroic_files(config, self.home), {})

    def test_shared_art_and_outside_asset_paths_are_preserved(self):
        config = self.home/'Heroic config'
        (config/'sideload_apps/artwork').mkdir(parents=True)
        (config/'GamesConfig').mkdir()
        art = config/'sideload_apps/artwork/switch-to-steam-wide.png'; art.write_bytes(b'shared')
        outside = self.home/'precious.png'; outside.write_bytes(b'keep')
        managed = {'app_name': 'hstn-id', 'title': 'Switch to Steam', 'runner': 'sideload',
                   'install': {'executable': '/usr/bin/flatpak-spawn'},
                   'art_cover': art.as_uri(), 'art_square': outside.as_uri()}
        other = {'app_name': 'other', 'art_cover': art.as_uri()}
        (config/'sideload_apps/library.json').write_text(json.dumps({'games': [managed, other]}))
        (config/'GamesConfig/hstn-id.json').write_text(json.dumps({'hstn-id': {'launcherArgs':
            shlex.join(['--host', str(self.home/'.local/bin/switch-to-steam')])}}))
        self.m.apply(self.m.heroic_files(config, self.home))
        self.assertTrue(art.exists()); self.assertEqual(outside.read_bytes(), b'keep')

    def test_duplicate_steam_id_is_a_conflict_before_art_removal(self):
        config = self.home/'Steam'; config.mkdir()
        (config/'shortcuts.vdf').write_bytes(self.config.encode_vdf({'shortcuts': {
            '0': {'appid': 123, 'Exe': str(self.home/'.local/bin/switch-to-heroic')},
            '1': {'appid': 123, 'Exe': '/games/other'}}}))
        with self.assertRaisesRegex(ValueError, 'ID|collision'):
            self.m.steam_files(config, self.home)

    def test_direct_heroic_wrapper_is_removed_even_without_a_settings_file(self):
        config = self.home/'Heroic'
        (config/'sideload_apps').mkdir(parents=True)
        library = config/'sideload_apps/library.json'
        library.write_text(json.dumps({'games': [{'runner': 'sideload', 'app_name': 'direct-id',
            'install': {'executable': str(self.home/'.local/bin/switch-to-steam')}}]}))
        self.m.apply(self.m.heroic_files(config, self.home))
        self.assertEqual(json.loads(library.read_text()), {'games': []})
