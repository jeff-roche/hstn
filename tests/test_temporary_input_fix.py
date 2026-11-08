import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]

class TemporaryInputFixTest(unittest.TestCase):
    def load(self):
        spec = importlib.util.spec_from_file_location('fix', ROOT/'prototypes/temporary-input-rule-fix.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_only_corrects_affected_hid_parent_match(self):
        module = self.load()
        text = (ROOT/'diagnostics/steam-input/50-inputplumber-hide-hidraw1-early.rules.captured').read_text()
        fixed = module.correct_rule(text, 'hidraw1')
        self.assertIn('SUBSYSTEM=="hidraw", KERNEL=="hidraw1", KERNELS==', fixed)
        self.assertEqual(module.correct_rule(fixed, 'hidraw1'), fixed)
        self.assertEqual(module.correct_rule(text.replace('KERNELS==', 'ENV{OTHER}=='), 'hidraw1'), text.replace('KERNELS==', 'ENV{OTHER}=='))
        self.assertEqual(module.correct_rule(text, 'hidraw2'), text)

    def test_preserves_unrelated_subsystem_conditions(self):
        module = self.load()
        text = 'SUBSYSTEMS=="hidraw", KERNEL=="hidraw1"\n'
        self.assertEqual(module.correct_rule(text, 'hidraw1'), text)
