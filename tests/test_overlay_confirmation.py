import subprocess
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
class ConfirmationUiTest(unittest.TestCase):
    def test_review_cancel_confirm_and_late_plan_are_safe(self):
        code=r'''
import importlib.util,json,os,tempfile
from pathlib import Path
from unittest import mock
spec=importlib.util.spec_from_file_location('overlay',Path('prototypes/session-overlay.py').resolve());m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
os.environ['QT_QPA_PLATFORM']='offscreen';m.xproperty=lambda *args:None
app=m.QtWidgets.QApplication([])
with tempfile.TemporaryDirectory() as directory:
 os.environ['XDG_RUNTIME_DIR']=directory
 folder=Path(directory)/'session-switch-confirmations';folder.mkdir()
 def payload():
  path=folder/'close-example.json';path.write_text('{}');path.chmod(0o600)
  return {'path':str(path),'apps':[{'label':'Agentos','processes':[{'name':'Agentos.exe'}]}, {'label':'Ubisoft Connect','processes':[{'name':'upc.exe'}]}],'warnings':[]}
 menu=m.Overlay();menu.planner=mock.Mock();menu.planner.busy=False
 menu.closer=mock.Mock();menu.closer.busy=False;menu.request=mock.Mock();menu.request.busy=False
 menu.choose(2);assert menu.mode=='planning'
 plan=payload();menu.plan_finished(0,json.dumps(plan))
 assert menu.mode=='confirm' and menu.selection==1
 assert 'Agentos' in menu.status.text() and 'Ubisoft Connect' in menu.status.text()
 menu.choose(1);assert menu.mode=='menu' and not Path(plan['path']).exists()
 menu.closer.start.assert_not_called();menu.request.start.assert_not_called()
 menu.choose(2);plan=payload();menu.plan_finished(0,json.dumps(plan));menu.choose(0)
 assert menu.mode=='closing';menu.closer.start.assert_called_once()
 assert menu.closer.start.call_args.args[0]=='desktop'
 assert menu.closer.start.call_args.kwargs['arguments']==['execute',plan['path']]
 menu.choose(0);assert menu.closer.start.call_count==1
 menu.switch_finished(20,'Still running: Agentos');assert menu.mode=='menu'
 menu.choose(2);menu.hide_overlay();late=payload();menu.plan_finished(0,json.dumps(late))
 assert menu.mode=='menu' and not Path(late['path']).exists()
 menu.request.start.assert_not_called()
 demo=m.Overlay(enable_actions=False);demo.planner=mock.Mock();demo.choose(2);demo.planner.start.assert_not_called()
 menu.hide();demo.hide()
print('CONFIRMATION_UI_PASS')
'''
        result=subprocess.run(['/usr/bin/python3','-c',code],cwd=ROOT,capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('CONFIRMATION_UI_PASS',result.stdout)
