"""Focused plan/recipient/policy checks. All external actions are mocked."""
import runpy,unittest,shutil
from pathlib import Path
from unittest.mock import patch
base=runpy.run_path(str(Path(__file__).with_name('release-3310.py')))
main=base['main'];holdings=base['holdings']
from app import semantic_tasks as tasks,semantic_planner,jev_decision
build_plan=semantic_planner.build
class Release3312(base['Release3310']):
 def create(self,msg):
  with patch('app.semantic_planner.build',side_effect=lambda scope,message,fallback:build_plan(scope,message,fallback,allow_model=False)):
   return tasks.create(self.scope,msg)
 def test_full_request_keeps_all_intents(self):
  t=self.create('Hazme un estudio de ayudas para vivienda. Hazme un informe resumido con links y envíamelo a mi propio email.')
  self.assertEqual([s['kind'] for s in t['subtasks']],['RESEARCH','VERIFY_SOURCES','CREATE_REPORT','STORE_ARTIFACT','RESOLVE_CONTACT','DRAFT_EMAIL','ATTACH_ARTIFACT','FINAL_CONFIRMATION','SEND_EMAIL'])
  self.assertEqual(t['entities']['recipient'],'SELF')
  self.assertIn(t['subtasks'][1]['id'],t['subtasks'][2]['dependencies'])
 def test_plan_confirmation_is_required_and_does_not_send(self):
  t=self.create('Investiga vivienda y envíamelo a mi propio email')
  with patch('app.research_agent.investigate') as research,self.assertRaises(ValueError):tasks.run(self.scope,t['id'])
  research.assert_not_called()
  tasks.confirm_plan(self.scope,t['id'])
  with main.app.test_request_context('/'),patch('app.research_agent.investigate',return_value={'ok':True,'text':'Evidence','sources':[{'url':'https://example.test','title':'Source'}]}),patch('app.web_search.fetch_webpage',return_value={'ok':True,'text':'Verified source evidence'}),patch('app.artifact_engine.create',return_value={'artifact_id':'f1'}),patch('app.file_store.FileStore.read',return_value=b'fixture'),patch('app.identity_mail.operate') as send:
   main.session['google_account_email']='owner@example.test'
   result=tasks.run(self.scope,t['id'])
   self.assertEqual(result['status'],'WAITING');self.assertEqual(result['outputs']['DRAFT_EMAIL']['to'],'owner@example.test');send.assert_not_called()
  decisions=holdings.read(self.scope)['jev_decisions'];self.assertTrue(any(r['decision']=='ALLOW' for r in decisions));self.assertEqual(decisions[-1]['decision'],'CONFIRM')
 def test_official_housing_fallback_reads_live_evidence(self):
  from app.research_agent import investigate
  with patch('app.web_search.google_web_search',return_value={'ok':False,'error':'quota'}),patch('app.web_search.fetch_webpage',return_value={'ok':True,'text':'Los requisitos de acceso a vivienda de jóvenes y los plazos de solicitudes deben comprobarse en la convocatoria oficial publicada.'}) as read:
   result=investigate('Ayudas vivienda Majadahonda joven 26 años')
   self.assertEqual(read.call_count,3);self.assertEqual(len(result['evidence']),3);self.assertEqual(result['synthesis'],'DOCUMENTARY_EVIDENCE')
  with patch('app.web_search.google_web_search',return_value={'ok':False,'error':'quota'}),self.assertRaises(ValueError):investigate('Un asunto sin fuentes')
 def test_research_preserves_inline_fragments_and_records_failed_sources(self):
  from app.research_agent import investigate
  pages=[{'ok':False,'error':'HTTP 403'}, {'ok':True,'text':'Requisitos de acceso\npara jóvenes de Majadahonda\npublicados en la convocatoria\noficial de vivienda protegida.'}, {'ok':False,'error':'timeout'}]
  with patch('app.web_search.google_web_search',return_value={'ok':False}),patch('app.web_search.fetch_webpage',side_effect=pages):
   result=investigate('Vivienda joven Majadahonda')
   self.assertEqual(len(result['evidence']),1)
   self.assertEqual(len(result['failed_sources']),2)
   self.assertIn('HTTP 403',result['failed_sources'][0]['error'])
 def test_prepare_to_send_recognizes_complete_graph(self):
  task=self.create('Hazme un estudio de las ayudas, vivienda protegida y sorteos de vivienda a los que podría acceder un joven de 26 años que vive en Majadahonda. Hazme un informe resumido con enlaces y prepáralo para enviarlo a mi propio email.')
  self.assertEqual(len(task['subtasks']),9)
  self.assertEqual(task['entities']['recipient'],'SELF')
  self.assertIn('Majadahonda',task['topic'])
  self.assertIn('vivienda protegida',task['topic'])
  self.assertFalse(task['plan_confirmed'])
 def test_cancelled_plan_cannot_resume(self):
  t=self.create('Investiga vivienda y envíamelo a mi propio email');tasks.cancel_plan(self.scope,t['id'])
  with self.assertRaises(ValueError):tasks.confirm_plan(self.scope,t['id'])
  self.assertEqual(tasks.run(self.scope,t['id'])['status'],'CANCELLED')
 def test_jev_live_and_stop_are_denied(self):
  self.assertEqual(jev_decision.evaluate(self.scope,{'action':'TRADING_LIVE'})['decision'],'DENY')
  state=holdings.read(self.scope);state['global_stop']=True;holdings.write(self.scope,state)
  self.assertEqual(jev_decision.evaluate(self.scope,{'action':'RESEARCH'})['decision'],'DENY')
 def test_mail_read_is_not_implied_by_research_request(self):
  t=tasks.plan('Investiga alquiler y envíamelo por email');self.assertNotIn('READ_MAIL',[s['kind'] for s in t['subtasks']])
if __name__=='__main__':
 try:result=unittest.TextTestRunner().run(unittest.defaultTestLoader.loadTestsFromTestCase(Release3312))
 finally:base['env'].stop();shutil.rmtree(base['temp'])
 if not result.wasSuccessful():raise SystemExit(1)
