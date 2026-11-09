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

    def test_service_input_target_loads_family_output_manager(self):
        with mock.patch.dict(os.environ, {'SESSION_SWITCH_INPUT_TARGET': 'ds5-single'}, clear=True):
            router = overlay.InputRouter(manage=True)
        self.addCleanup(router.close)
        self.assertEqual(type(router.playstation).__name__, 'ControllerOutputs')
        self.assertIsNotNone(router.playstation.sony)
        self.assertIsNotNone(router.playstation.xbox)

    def test_glyph_family_follows_active_controller_without_release_or_duplicate_changes(self):
        families = []
        self.router.input_family.connect(families.append)
        self.router.target_families.update(xbox='xbox', sony='playstation')
        self.router.controller_event('xbox', 'ui_down', 1)
        self.router.controller_event('sony', 'ui_up', 0)
        self.router.controller_event('xbox', 'ui_down', 1)
        self.router.controller_event('sony', 'ui_guide', 1)
        self.assertEqual(families, ['xbox'])
        self.router.controller_event('sony', 'ui_up', 1)
        self.assertEqual(families, ['xbox', 'playstation'])
        self.router.detach_target('sony')
        self.assertNotIn('sony', self.router.target_families)

    def test_disconnect_stops_owned_empty_composite_and_preserves_other_owners(self):
        self.router.state['modes'] = {'/owned': 0, '/foreign': 1, '/active': 0}
        self.router.state['baseline'] = ['/foreign']
        sources = {'/owned': (), '/foreign': (), '/unknown': (), '/active': ('/dev/hidraw1',)}
        with mock.patch.object(overlay, 'bus') as bus:
            result = self.router.retire_disconnected(sources)
        bus.assert_called_once_with('call', overlay.SERVICE, '/owned', overlay.COMPOSITE, 'Stop')
        self.assertEqual(set(result), {'/foreign', '/unknown', '/active'})
        with mock.patch.object(overlay, 'bus') as bus:
            self.router.retire_disconnected(result)
        bus.assert_not_called()


    def test_idle_baseline_handheld_is_adopted_without_replacing_targets(self):
        self.router.watchdog = mock.Mock()
        self.router.state['baseline'] = ['/org/CompositeDevice0']
        self.router.dbus = mock.Mock()
        properties = {'SourceDevicePaths': ['/dev/hidraw0'], 'InterceptMode': 0,
                      'Name': 'Lenovo Legion Go S', 'DbusDevices': ['/target']}
        with mock.patch.object(overlay.controllers, 'connected', return_value=True), \
             mock.patch.object(overlay.controllers, 'supported_sources', return_value=True), \
             mock.patch.object(overlay.controllers, 'preserved_composite', return_value=True), \
             mock.patch.object(overlay.controllers, 'composite_profile', return_value='legion-go-s'), \
             mock.patch.object(overlay.subprocess, 'run', return_value=mock.Mock(stdout='/org/CompositeDevice0')), \
             mock.patch.object(overlay, 'get_property', side_effect=lambda path, interface, name: properties[name]), \
             mock.patch.object(overlay, 'set_property') as mutate, \
             mock.patch.object(overlay, 'configure_menu_activation') as activation:
            self.router.refresh()
            self.assertEqual(self.router.target_families['/target'], 'handheld')
            self.assertEqual(self.router.state['modes'], {'/org/CompositeDevice0': 0})
            activation.assert_called_once_with('/org/CompositeDevice0', profile='legion-go-s')
            mutate.assert_called_once_with('/org/CompositeDevice0', overlay.COMPOSITE, 'InterceptMode', 'u', 1)
            self.router.refresh()
            activation.assert_called_once()

    def test_handheld_cleanup_restores_mode_and_default_activation_without_stopping_baseline(self):
        state = {'baseline': ['/org/CompositeDevice0'], 'modes': {'/org/CompositeDevice0': 0}, 'activation_paths': ['/org/CompositeDevice0']}
        with mock.patch.object(overlay, 'configure_menu_activation') as activation, \
             mock.patch.object(overlay, 'set_property') as mutate, \
             mock.patch.object(overlay, 'bus') as bus:
            overlay.restore(state)
        activation.assert_called_once_with('/org/CompositeDevice0', restore_default=True)
        mutate.assert_called_once_with('/org/CompositeDevice0', overlay.COMPOSITE, 'InterceptMode', 'u', 0)
        bus.assert_not_called()

    def test_heroic_go_s_output_recovery_is_owned_before_controller_claim(self):
        self.router.watchdog = mock.Mock()
        self.router.state['baseline'] = ['/org/CompositeDevice0']
        self.router.dbus = mock.Mock()
        output = self.router.handheld_output = mock.Mock()
        trace = []
        def acquire(path, sources):
            saved = self.router.watchdog.stdin.write.call_args.args[0]
            self.assertTrue(overlay.json.loads(saved)['handheld_output'])
            trace.append('acquire output')
        output.acquire.side_effect = acquire
        properties = {'SourceDevicePaths': ['/dev/hidraw0'], 'InterceptMode': 0,
                      'Name': 'Lenovo Legion Go S', 'DbusDevices': ['/target']}
        with mock.patch.dict(os.environ, {'SESSION_SWITCH_CURRENT_SESSION':'heroic'}), \
             mock.patch.object(overlay.controllers, 'connected', return_value=True), \
             mock.patch.object(overlay.controllers, 'supported_sources', return_value=True), \
             mock.patch.object(overlay.controllers, 'preserved_composite', return_value=True), \
             mock.patch.object(overlay.controllers, 'composite_profile', return_value='legion-go-s'), \
             mock.patch.object(overlay.subprocess, 'run', return_value=mock.Mock(stdout='/org/CompositeDevice0')), \
             mock.patch.object(overlay, 'get_property', side_effect=lambda path, interface, name: properties[name]), \
             mock.patch.object(overlay, 'set_property'), \
             mock.patch.object(overlay, 'configure_menu_activation', side_effect=lambda *a, **kw: trace.append('claim controller')):
            self.router.refresh()
        self.assertEqual(trace, ['acquire output', 'claim controller'])
        self.assertEqual(self.router.target_families['/target'], 'handheld')
        output.recover.side_effect = lambda **kw: trace.append('restore output')
        with mock.patch.object(overlay, 'handheld_output_lease', return_value=output), \
             mock.patch.object(overlay, 'configure_menu_activation'), \
             mock.patch.object(overlay, 'set_property', side_effect=lambda *a: trace.append('restore mode')):
            overlay.restore(self.router.state)
        output.recover.assert_called_once_with(owned=True)
        self.assertEqual(trace[-2:], ['restore output', 'restore mode'])


    def test_go_s_back_waits_for_release_and_ignores_duplicates(self):
        self.router.target_families['gos'] = 'handheld'
        self.router.visible = True
        events = []
        self.router.action.connect(events.append)
        for value in (1, 1):
            self.router.controller_event('gos', 'ui_back', value)
        self.assertEqual(events, [])
        for value in (0, 0):
            self.router.controller_event('gos', 'ui_back', value)
        self.assertEqual(events, ['ui_back'])
        self.router.controller_event('gos', 'ui_back', 1)
        self.router.controller_event('gos', 'ui_back', 0)
        self.assertEqual(events, ['ui_back', 'ui_back'])

    def test_go_s_unmatched_back_release_recovers_stale_inputplumber_state(self):
        self.router.target_families['gos'] = 'handheld'
        events = []
        self.router.action.connect(events.append)
        with mock.patch.object(overlay, 'set_property'):
            for _ in range(3):
                self.router.capture(True)
                self.router.controller_event('gos', 'ui_back', 0)
                self.router.controller_event('gos', 'ui_back', 0)
                self.router.capture(False)
                self.router.controller_event('gos', 'ui_back', 0)
        self.assertEqual(events, ['ui_back'] * 3)

    def test_xbox_back_still_activates_on_press(self):
        self.router.target_families['xbox'] = 'xbox'
        events = []
        self.router.action.connect(events.append)
        self.router.controller_event('xbox', 'ui_back', 1)
        self.assertEqual(events, ['ui_back'])
        self.router.controller_event('xbox', 'ui_back', 0)
        self.assertEqual(events, ['ui_back'])

    def test_go_s_accept_releases_before_closing_and_works_on_next_open(self):
        self.router.target_families['gos'] = 'handheld'
        events = []
        def select(action):
            self.assertNotIn('ui_accept', self.router.controller_pressed['gos'])
            events.append(action)
            self.router.capture(False)
        self.router.action.connect(select)
        with mock.patch.object(overlay, 'set_property'):
            for cycle in range(3):
                self.router.capture(True)
                self.router.controller_event('gos', 'ui_accept', 1)
                self.router.controller_event('gos', 'ui_accept', 1)
                self.assertEqual(len(events), cycle)
                self.router.controller_event('gos', 'ui_accept', 0)
                self.router.controller_event('gos', 'ui_accept', 0)
                self.assertEqual(len(events), cycle + 1)
        self.assertEqual(events, ['ui_accept'] * 3)

    def test_go_s_first_accept_release_recovers_old_stale_press_once(self):
        self.router.target_families['gos'] = 'handheld'
        self.router.controller_pressed['gos'] = {'ui_accept'}
        events = []
        self.router.action.connect(events.append)
        with mock.patch.object(overlay, 'set_property'):
            self.router.capture(True)
            # InputPlumber suppresses the new press because its old target is held.
            self.router.controller_event('gos', 'ui_accept', 0)
            self.router.controller_event('gos', 'ui_accept', 0)
            self.router.capture(False)
            self.router.controller_event('gos', 'ui_accept', 0)
        self.assertEqual(events, ['ui_accept'])
        self.assertNotIn('ui_accept', self.router.controller_pressed['gos'])

    def test_go_s_desktop_splits_controls_and_restores_before_forwarding(self):
        self.router.desktop = True
        self.router.state['modes'] = {'/gos': 0}
        self.router.path_sources['/gos'] = ('/dev/hidraw1',)
        trace = []
        lease = mock.Mock()
        lease.close.side_effect = lambda: trace.append('restore profile')
        def acquire(path):
            trace.append('map ' + path)
            return lease
        with mock.patch.object(overlay.controllers, 'composite_profile', return_value='legion-go-s'), \
             mock.patch.object(overlay, 'desktop_isolation_issues', return_value=[]), \
             mock.patch.object(overlay, 'DesktopMapLease', side_effect=acquire), \
             mock.patch.object(overlay, 'set_property', side_effect=lambda *args: trace.append(args[-1])):
            self.router.capture(True)
            self.assertIs(self.router.desktop_maps['/gos'], lease)
            self.router.capture(False)
        self.assertEqual(trace, [2, 'map /gos', 1, 2, 'restore profile', 1])
        self.assertEqual(self.router.desktop_maps, {})

    def test_go_s_split_mapping_failure_does_not_enable_forwarding(self):
        self.router.desktop = True
        self.router.state['modes'] = {'/gos': 0}
        with mock.patch.object(overlay.controllers, 'composite_profile', return_value='legion-go-s'), \
             mock.patch.object(overlay, 'desktop_isolation_issues', return_value=[]), \
             mock.patch.object(overlay, 'DesktopMapLease', side_effect=RuntimeError('mapping failed')), \
             mock.patch.object(overlay, 'set_property') as mode:
            with self.assertRaisesRegex(RuntimeError, 'mapping failed'):
                self.router.capture(True)
        mode.assert_called_once_with('/gos', overlay.COMPOSITE, 'InterceptMode', 'u', 2)

    def test_stick_reversal_releases_opposite_navigation_state(self):
        self.router.target_families['gos'] = 'handheld'
        events = []
        self.router.action.connect(events.append)
        for event in ('ui_left', 'ui_right', 'ui_left'):
            self.router.controller_event('gos', event, .9)
        self.assertEqual(events, ['ui_left', 'ui_right', 'ui_left'])
