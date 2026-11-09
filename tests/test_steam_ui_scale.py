"""Steam's persisted display preference, independent of zoom/accessibility settings."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('steam_ui_scale_test', ROOT/'scripts/steam-ui-scale.py')
scale = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scale)


def config(fields):
    return '"InstallConfigStore" { "UI" { "display" { "Current" { '+fields+' } } } }'


class SteamUIScaleTest(unittest.TestCase):
    def test_reads_saved_manual_display_scale_and_ignores_other_settings(self):
        text = config('"ScaleFactor" "1.68186640739440918" "AutoScaleFactor" "2.08"')
        text += '\n"other" { "steamos_magnifier_scale" "150" "accessibility_desktop_ui_scale" "0.8" }'
        self.assertAlmostEqual(scale.display_scale(text), 1.68186640739440918)
        self.assertIsNone(scale.display_scale('"elsewhere" { "display" { "Current" { "ScaleFactor" "3" } } }'))

    def test_auto_scale_and_malformed_or_missing_preferences(self):
        self.assertEqual(scale.display_scale(config('"AutoScaleFactor" "2"')), 2)
        self.assertEqual(scale.display_scale(config('"ScaleFactor" "0" "AutoScaleFactor" "1.5"')), 1.5)
        for value in ('nan', 'inf', '-1', '999', 'invalid'):
            self.assertIsNone(scale.display_scale(config('"ScaleFactor" "'+value+'"')))
        for text in ('', config('"ScaleFactor" "2"')[:-1], config('"ScaleFactor" "2" "ScaleFactor" "3"'), 'bad tokens'):
            self.assertIsNone(scale.display_scale(text))

    def test_comments_escaped_quotes_and_braces_inside_strings(self):
        text = '// settings\n"extra" { "value" "escaped \\" brace }" }\n' + config('"ScaleFactor" "1.75"')
        self.assertEqual(scale.display_scale(text), 1.75)

    def test_poll_follows_changes_and_preserves_last_valid_scale_without_writes(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            reader = scale.SteamUIScale(home, home/'data')
            self.assertEqual(reader.poll(), 1)
            path = home/'data/Steam/config/config.vdf'
            path.parent.mkdir(parents=True)
            path.write_text(config('"ScaleFactor" "1.68"'))
            original = path.read_bytes()
            self.assertEqual(reader.poll(), 1.68)
            self.assertEqual(reader.poll(), 1.68)
            self.assertEqual(path.read_bytes(), original)
            path.write_text('incomplete write')
            self.assertEqual(reader.poll(), 1.68)
            path.write_text(config('"ScaleFactor" "2"'))
            self.assertEqual(reader.poll(), 2)
            path.unlink()
            self.assertEqual(reader.poll(), 2)
