import importlib.util
from pathlib import Path
from unittest import TestCase, mock

SCRIPT=Path(__file__).resolve().parents[1]/'src/session-overlay.py'
spec=importlib.util.spec_from_file_location('overlay_binding',SCRIPT)
overlay=importlib.util.module_from_spec(spec)
spec.loader.exec_module(overlay)

class BindingTest(TestCase):
    def test_activation_uses_guide_then_create_and_distinct_marker(self):
        with mock.patch.object(overlay,'bus') as bus:
            overlay.configure_menu_activation('/composite')
        bus.assert_called_once_with('call',overlay.SERVICE,'/composite',overlay.COMPOSITE,
            'SetInterceptActivation','ass','2','Gamepad:Button:Guide',
            'Gamepad:Button:Select','Gamepad:Button:QuickAccess')

    def test_native_guide_does_not_toggle_custom_menu(self):
        menu=mock.Mock()
        menu.isVisible.return_value=False
        overlay.Overlay.controller(menu,'ui_guide')
        menu.toggle.assert_not_called()
        overlay.Overlay.controller(menu,'ui_quick')
        menu.toggle.assert_called_once()

    def test_heroic_compatibility_target_is_limited_to_owned_dualsense_hid(self):
        self.assertEqual(overlay.compatibility_targets('Sony DualSense Wireless Controller',['/dev/hidraw1'],True),['xb360','mouse','keyboard'])
        self.assertIsNone(overlay.compatibility_targets('Sony DualSense',['/dev/input/event17'],True))
        self.assertIsNone(overlay.compatibility_targets('Xbox controller',['/dev/hidraw1'],True))
        self.assertIsNone(overlay.compatibility_targets('Sony DualSense',['/dev/hidraw1'],False))


    def test_go_s_activation_uses_guide_then_quick_access(self):
        with mock.patch.object(overlay, 'bus') as bus:
            overlay.configure_menu_activation('/composite', profile='legion-go-s')
        bus.assert_called_once_with('call', overlay.SERVICE, '/composite', overlay.COMPOSITE,
            'SetInterceptActivation', 'ass', '2', 'Gamepad:Button:Guide',
            'Gamepad:Button:QuickAccess', 'Gamepad:Button:QuickAccess')

    def test_xbox_keeps_guide_then_view(self):
        with mock.patch.object(overlay, 'bus') as bus:
            overlay.configure_menu_activation('/composite', profile='xbox')
        bus.assert_called_once_with('call', overlay.SERVICE, '/composite', overlay.COMPOSITE,
            'SetInterceptActivation', 'ass', '2', 'Gamepad:Button:Guide',
            'Gamepad:Button:Select', 'Gamepad:Button:QuickAccess')

    def test_go_s_cleanup_restores_default_guide_binding(self):
        with mock.patch.object(overlay, 'bus') as bus:
            overlay.configure_menu_activation('/composite', restore_default=True, profile='legion-go-s')
        bus.assert_called_once_with('call', overlay.SERVICE, '/composite', overlay.COMPOSITE,
            'SetInterceptActivation', 'ass', '1', 'Gamepad:Button:Guide', 'Gamepad:Button:Guide')
