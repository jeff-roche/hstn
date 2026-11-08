import importlib.util
from pathlib import Path
import unittest
import tempfile

SCRIPT=Path(__file__).resolve().parents[1]/'scripts/playstation-output.py'

class PlayStationOutputTest(unittest.TestCase):
    def load(self):
        spec=importlib.util.spec_from_file_location('ps_output',SCRIPT)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

    def records(self):
        self.current_records = [
            {'path':'/hid','sources':['/dev/hidraw1'],'owned':True,'targets':['/default-hid']},
            {'path':'/buttons','sources':['/dev/input/event17'],'owned':True,'targets':['/default-buttons']},
            {'path':'/motion','sources':['/dev/input/event18'],'owned':True,'targets':['/default-motion']}]
        return self.current_records

    def controller(self, clock=lambda:0, max_attempts=3):
        m=self.load();calls=[];nodes=['old1','old2'];pad=[False]
        def set_targets(path,targets):
            calls.append((path,targets))
            for record in self.current_records:
                if record['path']==path:
                    record['targets']=[] if targets==['null'] else ['/single-output']
        controller=m.PlayStationOutput(set_targets,
            parent_for=lambda path:'physical' if path!='other' else 'other',
            required_for=lambda source:{'/dev/hidraw1','/dev/input/event17','/dev/input/event18'},
            virtual_devices=lambda:list(nodes),pad_ready=lambda:pad[0],
            clock=clock,binding_timeout=10,max_binding_attempts=max_attempts)
        return controller,calls,nodes,pad

    def test_drains_duplicates_before_creating_one_real_output(self):
        c,calls,nodes,pad=self.controller();records=self.records()
        self.assertFalse(c.update(records))
        self.assertEqual(calls,[('/hid',['null']),('/buttons',['null']),('/motion',['null'])])
        self.assertFalse(c.update(records));self.assertEqual(len(calls),3)
        nodes.clear()
        self.assertFalse(c.update(records))
        self.assertEqual(calls[-1],('/hid',['ds5','mouse','keyboard']))
        nodes.append('single');pad[0]=True
        self.assertTrue(c.update(records));self.assertEqual(c.companions,{'/buttons','/motion'})
        self.assertTrue(c.update(records));self.assertEqual(len(calls),4)

    def test_waits_for_siblings_before_mutation(self):
        c,calls,_,_=self.controller()
        self.assertFalse(c.update(self.records()[:1]));self.assertEqual(calls,[])

    def test_preserves_existing_owner(self):
        c,calls,_,_=self.controller();records=self.records();records[1]['owned']=False
        with self.assertRaises(RuntimeError):c.update(records)
        self.assertEqual(calls,[])

    def test_rejects_multiple_physical_playstation_controllers_without_mutation(self):
        c,calls,_,_=self.controller();records=self.records()
        records.append({'path':'/second','sources':['/dev/hidraw2'],'owned':True})
        with self.assertRaises(RuntimeError):c.update(records)
        self.assertEqual(calls,[])

    def test_does_not_change_unrelated_controller(self):
        c,calls,_,_=self.controller();records=self.records()
        records.append({'path':'/unrelated','sources':['other'],'owned':False})
        c.update(records)
        self.assertNotIn('/unrelated',[path for path,_ in calls])

    def test_drain_waits_for_dbus_target_removal_even_without_hidraw_nodes(self):
        c,calls,nodes,pad=self.controller();records=self.records()
        c.update(records);nodes.clear()
        records[1]['targets']=['/pending-default-pad']
        self.assertFalse(c.update(records));self.assertEqual(len(calls),3)
        records[1]['targets']=[]
        self.assertFalse(c.update(records));self.assertEqual(calls[-1],('/hid',['ds5','mouse','keyboard']))

    def test_failed_binding_retries_only_after_all_owned_outputs_are_drained(self):
        clock=[0]
        c,calls,nodes,pad=self.controller(clock=lambda:clock[0]);records=self.records()
        c.update(records);nodes.clear();c.update(records)
        self.assertEqual(c.phase,'binding')
        nodes.append('failed-unbound-UHID')
        clock[0]=9;self.assertFalse(c.update(records));self.assertEqual(len(calls),4)
        clock[0]=10;self.assertFalse(c.update(records));self.assertEqual(c.phase,'draining')
        self.assertEqual(calls[-3:],[('/hid',['null']),('/buttons',['null']),('/motion',['null'])])
        self.assertFalse(c.update(records));self.assertEqual(len(calls),7)
        nodes.clear();self.assertFalse(c.update(records))
        self.assertEqual(calls[-1],('/hid',['ds5','mouse','keyboard']))
        pad[0]=True;self.assertTrue(c.update(records));self.assertEqual(c.phase,'ready')

    def test_failed_binding_stops_retrying_at_limit_and_preserves_foreign_owners(self):
        clock=[0]
        c,calls,nodes,pad=self.controller(clock=lambda:clock[0],max_attempts=2);records=self.records()
        c.update(records);nodes.clear();c.update(records)
        clock[0]=10;c.update(records);c.update(records)
        clock[0]=20
        with self.assertRaisesRegex(RuntimeError,'failed.*2'):
            c.update(records)
        self.assertEqual(c.phase,'failed');count=len(calls)
        with self.assertRaises(RuntimeError):c.update(records)
        self.assertEqual(len(calls),count)
        c,calls,nodes,pad=self.controller(clock=lambda:clock[0]);records=self.records()
        c.update(records);nodes.clear();c.update(records)
        records[1]['owned']=False;clock[0]+=10
        with self.assertRaisesRegex(RuntimeError,'Existing owner'):c.update(records)
        self.assertEqual(len(calls),4)

    def test_virtual_device_scan_includes_failed_uhid_without_hidraw(self):
        m=self.load()
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            failed=root/'0003:054C:0CE6.0001';failed.mkdir()
            (failed/'uevent').write_text('HID_ID=0003:0000054C:00000CE6\n')
            unrelated=root/'other';unrelated.mkdir();(unrelated/'uevent').write_text('HID_ID=other\n')
            self.assertEqual(m.virtual_devices(root),[str(failed)])

    def test_waits_for_initial_target_creation_before_requesting_drain(self):
        c,calls,nodes,pad=self.controller();records=self.records()
        records[0]['targets']=[]
        self.assertFalse(c.update(records));self.assertEqual(calls,[])
        records[0]['targets']=['/default-hid']
        self.assertFalse(c.update(records));self.assertEqual(c.phase,'draining')

    def test_stalled_drain_fails_without_creating_another_pad(self):
        clock=[0]
        c,calls,nodes,pad=self.controller(clock=lambda:clock[0]);records=self.records()
        c.update(records);clock[0]=14
        self.assertFalse(c.update(records));self.assertEqual(len(calls),3)
        clock[0]=15
        with self.assertRaisesRegex(RuntimeError,'drain'):c.update(records)
        self.assertEqual(c.phase,'failed');self.assertEqual(len(calls),3)

    def test_partial_drain_failure_is_terminal_instead_of_stalling_discovery(self):
        c,calls,nodes,pad=self.controller();records=self.records()
        setter=c.set_targets
        def partial(path,targets):
            if path=='/buttons':raise RuntimeError('D-Bus timeout')
            setter(path,targets)
        c.set_targets=partial
        with self.assertRaisesRegex(RuntimeError,'drain failed'):c.update(records)
        self.assertEqual(c.phase,'failed');self.assertEqual(records[0]['targets'],[])
        count=len(calls)
        with self.assertRaises(RuntimeError):c.update(records)
        self.assertEqual(len(calls),count)

    def test_ambiguous_binding_request_failure_is_terminal(self):
        c,calls,nodes,pad=self.controller();records=self.records()
        c.update(records);nodes.clear();setter=c.set_targets
        def accepted_then_timeout(path,targets):
            setter(path,targets)
            raise RuntimeError('D-Bus timeout after acceptance')
        c.set_targets=accepted_then_timeout
        with self.assertRaisesRegex(RuntimeError,'binding request failed'):c.update(records)
        self.assertEqual(c.phase,'failed');count=len(calls)
        with self.assertRaises(RuntimeError):c.update(records)
        self.assertEqual(len(calls),count)
