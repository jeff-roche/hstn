import importlib.util
import os
from pathlib import Path
import unittest

SCRIPT=Path(__file__).resolve().parents[1]/'scripts/session-close.py'
class ClosePlanTest(unittest.TestCase):
    def load(self):
        spec=importlib.util.spec_from_file_location('close_plan',SCRIPT)
        m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
    def process(self,pid,name,heroic='',prefix='/games/prefix',start=100):
        return {'pid':pid,'start':start,'uid':os.getuid(),'name':name,'heroic_id':heroic,
                'steam_id':'','prefix':prefix,'namespace_pids':[pid]}
    def plan(self,records):
        return self.load().build_plan('desktop',records,{('heroic','game'):'Agentos'},
                                     {'/games/prefix'},set(),{'switcher'})
    def test_game_and_related_launcher_are_listed_separately(self):
        plan=self.plan([self.process(1,'Agentos.exe','game'),self.process(2,'upc.exe'),
                        self.process(3,'UplayWebCore.exe')])
        apps={app['label']:app for app in plan['apps']}
        self.assertEqual(set(apps),{'Agentos','Ubisoft Connect'})
        self.assertEqual([p['pid'] for p in apps['Ubisoft Connect']['processes']],[2,3])
    def test_unrelated_prefix_and_frontends_and_shared_wine_are_preserved(self):
        plan=self.plan([self.process(1,'Agentos.exe','game'),self.process(2,'upc.exe',prefix='/other'),
                        self.process(3,'heroic','game'),self.process(4,'wineserver','game'),
                        self.process(5,'services.exe','game'),self.process(6,'flatpak-spawn','switcher')])
        self.assertEqual([p['pid'] for a in plan['apps'] for p in a['processes']],[1])
    def test_lingering_related_launcher_is_included_without_running_game(self):
        self.assertEqual(self.plan([self.process(1,'upc.exe')])['apps'][0]['label'],'Ubisoft Connect')
    def test_new_or_reused_process_requires_new_confirmation(self):
        m=self.load();old=self.plan([self.process(1,'Agentos.exe','game')])
        self.assertTrue(m.plan_covers(old,old))
        self.assertFalse(m.plan_covers(old,self.plan([self.process(1,'Agentos.exe','game',start=101)])))
        self.assertFalse(m.plan_covers(old,self.plan([self.process(2,'Agentos.exe','game')])))
        self.assertTrue(m.plan_covers(old,self.plan([])))

    def test_other_user_process_is_not_in_close_list(self):
        record=self.process(1,'Agentos.exe','game');record['uid']=os.getuid()+1
        self.assertEqual(self.plan([record])['apps'],[])
