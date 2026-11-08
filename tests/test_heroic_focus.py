import importlib.util
from pathlib import Path
import unittest

SCRIPT=Path(__file__).resolve().parents[1]/'scripts/heroic-window-focus.py'
class HeroicFocusTest(unittest.TestCase):
    def module(self):
        spec=importlib.util.spec_from_file_location('heroic_focus',SCRIPT)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

    def window(self,props=''):
        return {'properties':{'status':0,'output':'WM_CLASS(STRING) = "steam_app_0", "steam_app_0"\nWM_STATE(WM_STATE):\n window state: Normal\n'+props}}

    def test_only_normal_zero_app_wine_windows_are_candidates(self):
        m=self.module()
        self.assertTrue(m.is_candidate(self.window()))
        for extra in ('STEAM_OVERLAY(CARDINAL) = 1','STEAM_GAME(CARDINAL) = 12',
                      '_NET_WM_NAME(UTF8_STRING) = "Ubisoft Connect Notification"'):
            self.assertFalse(m.is_candidate(self.window(extra)))
        self.assertFalse(m.is_candidate({'properties':{'status':0,'output':'WM_CLASS(STRING) = "heroic"'}}))
        self.assertFalse(m.is_candidate(self.window().copy() | {'properties':{'status':0,'output':'WM_CLASS = "steam_app_0"'}}))

    def test_fullscreen_wine_without_wm_state_is_eligible(self):
        m=self.module()
        window={'properties':{'status':0,'output':'WM_CLASS(STRING) = "steam_app_0", "steam_app_0"\n_NET_WM_NAME(UTF8_STRING) = "Brawlhalla"\nWM_STATE:  not found.\n'}}
        self.assertTrue(m.is_candidate(window))
        window['properties']['output'] += 'window state: Iconic\n'
        self.assertFalse(m.is_candidate(window))

    def test_registered_windows_remain_candidates(self):
        m=self.module();self.assertTrue(m.is_candidate(self.window(f'STEAM_GAME(CARDINAL) = {m.APP_ID}')))

    def test_layer_changes_preserve_other_owners(self):
        m=self.module()
        self.assertEqual(m.desired_layers([1],True),[m.APP_ID,1])
        self.assertEqual(m.desired_layers([m.APP_ID,1],False),[1])
        self.assertIsNone(m.desired_layers([600123,1],True))
        self.assertIsNone(m.desired_layers([],True))
