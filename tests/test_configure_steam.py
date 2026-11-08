import importlib.util
import struct
import json
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/configure-launchers.py'
ASSETS = SCRIPT.parents[1] / 'assets/artwork'


def fixture():
    # Two independent shortcut records, including unrelated tags and launch options.
    def string(key, value):
        return b'\x01' + key.encode() + b'\0' + value.encode() + b'\0'
    def record(key, appid, name, executable):
        return (b'\x00' + key.encode() + b'\0' + b'\x02appid\0' + struct.pack('<I', appid)
                + string('AppName', name) + string('Exe', executable) + string('icon', '')
                + string('LaunchOptions', '--keep-this') + b'\x00tags\0'
                + string('0', 'Favorites') + b'\x08\x08')
    return (b'\x00shortcuts\0'
            + record('0', 42, 'Other application', '/bin/other')
            + record('1', 2777996481, 'old name', '"/home/example/.local/bin/switch-to-heroic"')
            + b'\x08\x08')

class ConfigureTest(unittest.TestCase):
    def test_existing_shortcut_and_unrelated_data_survive_reapply(self):
        self.assertTrue(SCRIPT.exists(), 'Configuration script has not been implemented')
        spec = importlib.util.spec_from_file_location('configure', SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory)
            (config / 'shortcuts.vdf').write_bytes(fixture())
            (config / 'grid').mkdir()
            (config / 'grid/2777996481.json').write_text(json.dumps({'nVersion': 1, 'logoPosition': {'pinnedPosition': 'BottomLeft'}, 'keep': True}))
            before = module.read_vdf((config / 'shortcuts.vdf').read_bytes())
            module.configure_steam(config)
            after = module.read_vdf((config / 'shortcuts.vdf').read_bytes())
            for key, shortcut in before['shortcuts'].items():
                expected = dict(shortcut)
                if shortcut['appid'] == 2777996481:
                    expected['AppName'] = 'Switch to Heroic'
                    expected['icon'] = str(config / 'grid/2777996481_icon.png')
                self.assertEqual(after['shortcuts'][key], expected)
            self.assertEqual(json.loads((config / 'grid/2777996481.json').read_text()),
                             {'nVersion': 1, 'keep': True})
            for suffix, asset in {'p.png': 'switch-to-heroic-portrait.png', '.png': 'switch-to-heroic-wide.png', '_hero.png': 'switch-to-heroic-details-background.png', '_icon.png': 'heroic-official-icon.png', '_logo.png': 'heroic-official-icon.png'}.items():
                self.assertEqual((config / ('grid/2777996481' + suffix)).read_bytes(),
                                 (ASSETS / asset).read_bytes())
            first = (config / 'shortcuts.vdf').read_bytes()
            module.configure_steam(config)
            self.assertEqual(first, (config / 'shortcuts.vdf').read_bytes())
            self.assertTrue(list(config.glob('shortcuts.vdf.*.bak')))

if __name__ == '__main__':
    unittest.main()
