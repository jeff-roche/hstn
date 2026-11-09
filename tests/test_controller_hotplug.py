import importlib.util
import os
from pathlib import Path
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('hotplug_overlay', ROOT/'src/session-overlay.py')
overlay = importlib.util.module_from_spec(spec)
spec.loader.exec_module(overlay)


class ControllerHotplugTest(unittest.TestCase):
    def setUp(self):
        self.app = overlay.QtCore.QCoreApplication.instance() or overlay.QtCore.QCoreApplication([])
        with mock.patch.dict(os.environ, {}, clear=True):
            self.router = overlay.InputRouter(manage=True)
        self.addCleanup(self.router.close)

    def test_no_supported_controller_keeps_service_watching_without_management(self):
        with mock.patch.object(overlay.controllers, 'connected', return_value=False), \
             mock.patch.object(self.router, 'start_controller') as start, \
             mock.patch.object(overlay, 'set_property') as mutate:
            self.router.start()
            self.assertTrue(self.router.timer.isActive())
            start.assert_not_called()
            mutate.assert_not_called()

    def test_connect_disconnect_reconnect_starts_fresh_controller_lifecycle(self):
        def activate():
            self.router.watchdog = mock.Mock()
        with mock.patch.object(overlay.controllers, 'connected', side_effect=[False, True, False, True]), \
             mock.patch.object(self.router, 'start_controller', side_effect=activate) as start, \
             mock.patch.object(overlay.subprocess, 'run', return_value=mock.Mock(stdout='')):
            self.router.start()
            self.router.refresh()
            first = self.router.watchdog
            self.router.refresh()
            first.stdin.close.assert_called_once()
            self.assertIsNone(self.router.watchdog)
            self.router.refresh()
            self.assertEqual(start.call_count, 2)
            self.assertTrue(self.router.timer.isActive())

    def test_activation_failure_keeps_watching_and_does_not_enable_interception(self):
        with mock.patch.object(overlay.controllers, 'connected', return_value=True), \
             mock.patch.object(self.router, 'start_controller', side_effect=RuntimeError('Steam already holds controller')), \
             mock.patch.object(overlay, 'set_property') as mutate:
            self.router.start()
            self.router.refresh()
            self.assertTrue(self.router.timer.isActive())
            mutate.assert_not_called()

    def test_button_state_is_independent_for_each_controller(self):
        events = []
        self.router.action.connect(events.append)
        self.router.controller_event('one', 'ui_down', 1)
        self.router.controller_event('two', 'ui_down', 1)
        self.router.controller_event('two', 'ui_down', 0)
        self.router.controller_event('one', 'ui_down', 1)
        self.assertEqual(events, ['ui_down', 'ui_down'])

    def test_detaching_one_controller_keeps_other_subscription(self):
        self.router.dbus = mock.Mock()
        self.router.targets.update(('one', 'two'))
        self.router.target_paths.update(one='/first', two='/second')
        self.router.controller_pressed.update(one={'ui_down'}, two={'ui_up'})
        self.router.detach_target('one')
        self.assertEqual(self.router.targets, {'two'})
        self.assertEqual(self.router.controller_pressed, {'two': {'ui_up'}})

    def test_steam_physical_handle_prevents_management_before_any_mutation(self):
        with mock.patch.object(overlay.controllers, 'activation_issues', return_value=['Steam already holds source']), \
             mock.patch.object(overlay, 'set_property') as mutate, \
             mock.patch.object(overlay.subprocess, 'Popen') as watchdog:
            with self.assertRaisesRegex(RuntimeError, 'Steam already holds'):
                self.router.start_controller()
            mutate.assert_not_called()
            watchdog.assert_not_called()
