import importlib.util
import os
from pathlib import Path
import unittest
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('guard_overlay',ROOT/'prototypes/session-overlay.py')
overlay=importlib.util.module_from_spec(spec);spec.loader.exec_module(overlay)

class GuardLifecycleTest(unittest.TestCase):
    def router(self):
        app=overlay.QtCore.QCoreApplication.instance() or overlay.QtCore.QCoreApplication([])
        self.app=app
        with mock.patch.dict(os.environ,{'SESSION_SWITCH_REQUIRE_INPUT_GUARD':'1'}):
            router=overlay.InputRouter(manage=True)
        router.guard_status=mock.Mock()
        router.guard_status.permanent_guard_active.return_value=False
        router.guard_status.legacy_guard_active.return_value=False
        return router
    def test_missing_guard_never_takes_controller_ownership(self):
        router=self.router()
        with mock.patch.object(overlay,'composites') as discover, mock.patch.object(overlay,'set_property') as mutate:
            with self.assertRaises(RuntimeError):router.start()
            discover.assert_not_called();mutate.assert_not_called()
    def test_lost_guard_emits_disable_once_and_prevents_capture(self):
        router=self.router();messages=[];router.fatal.connect(messages.append)
        with mock.patch.object(overlay,'set_property') as mutate:
            router.refresh();router.refresh()
            with self.assertRaises(RuntimeError):router.capture(True)
            mutate.assert_not_called()
        self.assertEqual(len(messages),1);self.assertFalse(router.visible)
