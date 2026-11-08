import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest

SCRIPT=Path(__file__).resolve().parents[1]/'scripts/input-guard-status.py'
def load():
    spec=importlib.util.spec_from_file_location('guard_status',SCRIPT)
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

class StatusTest(unittest.TestCase):
    def test_stale_reused_or_writable_status_never_counts_as_running(self):
        m=load()
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);status=root/'active';proc=root/'proc';process=proc/'42';process.mkdir(parents=True)
            fields=['S']+['0']*18+['123']
            (process/'stat').write_text('42 (guard) '+' '.join(fields))
            data={'version':1,'kind':'session-switch-input-guard','pid':42,'start_ticks':123}
            status.write_text(json.dumps(data));status.chmod(0o644)
            self.assertTrue(m.permanent_guard_active(status,proc,owner_uid=os.getuid()))
            data['start_ticks']=124;status.write_text(json.dumps(data))
            self.assertFalse(m.permanent_guard_active(status,proc,owner_uid=os.getuid()))
            data['start_ticks']=123;status.write_text(json.dumps(data));status.chmod(0o666)
            self.assertFalse(m.permanent_guard_active(status,proc,owner_uid=os.getuid()))
            status.unlink();self.assertFalse(m.permanent_guard_active(status,proc,owner_uid=os.getuid()))
