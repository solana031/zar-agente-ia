"""Focused 33.3.10 regression checks; providers mocked, no orders/posts."""
import os,uuid,unittest,shutil
from pathlib import Path
from unittest.mock import patch
root=Path(__file__).resolve().parents[1];temp=root/('zar-3310-'+uuid.uuid4().hex);temp.mkdir()
env=patch.dict(os.environ,{'ZAR_DATA_DIR':str(temp),'RAILWAY_ENVIRONMENT_ID':''});env.start()
with patch('threading.Thread.start'):
 from app import main,holdings,media_company as media,media_surface,orchestration_map
 from app.user_scope import set_current_user
class Release3310(unittest.TestCase):
 def setUp(self):self.scope='fixture_'+uuid.uuid4().hex;set_current_user(self.scope)
 def test_generate_reuses_persisted_project_without_duplicate(self):
  data={'story':'Historia completa','duration':30,'format':'16:9','platform':'youtube'}
  with patch.object(media,'produce_local',side_effect=lambda scope,id:{'task_id':id}):
   one=media_surface.generate(self.scope,data);two=media_surface.generate(self.scope,data)
  self.assertEqual(one,two);self.assertEqual(len(holdings.read(self.scope)['companies']['media']['queue']),1)
  self.assertEqual(media._read(self.scope,one['task_id'])['project']['format'],'16:9')
 def test_edit_preserves_story_and_old_render_but_not_generation_key(self):
  with patch.object(media,'produce_local',side_effect=lambda scope,id:{'task_id':id}):task=media_surface.generate(self.scope,{'story':'Original'})
  id=task['task_id'];record=media._read(self.scope,id);record.update(status='PRODUCED',checkpoint={'stage':'done','project_id':'p1'},artifact=id+'.mp4');media._path(self.scope,id).with_suffix('.mp4').write_bytes(b'fixture');media._save(self.scope,id,record)
  media_surface.edit(self.scope,{'task_id':id,'story':'Edited','duration':40})
  record=media._read(self.scope,id);self.assertEqual(record['payload']['editor_story'],'Edited');self.assertNotIn('generation_key',record['payload']);self.assertNotIn('artifact',record)
  result=media._result(media._task(self.scope,id),record);self.assertNotIn('preview_url',result);self.assertIn('previous_preview_url',result)
  self.assertEqual(media.video_path(self.scope,id,previous=True).read_bytes(),b'fixture')
  with self.assertRaises(ValueError):media.video_path('different-user',id,previous=True)
 def test_pause_keeps_accepted_task_identifiers(self):
  task=media.queue_story(self.scope,'Original');record=media._read(self.scope,task['id']);record.update(status='PRODUCING',checkpoint={'stage':'script','active_task':{'task_id':'one'}});media._save(self.scope,task['id'],record)
  media_surface.pause(self.scope,task['id']);record=media._read(self.scope,task['id']);self.assertEqual(record['status'],'PAUSED');self.assertEqual(record['checkpoint']['active_task']['task_id'],'one')
 def test_equity_history_and_chart_subscription_plan(self):
  bars=[{'t':'2026-10-08T10:00:00Z','o':1,'h':2,'l':1,'c':2,'v':3}]
  with main.app.test_request_context('/api/stonks/chart/asset?symbol=AAPL&timeframe=4Hour'),patch.object(main,'_alpaca_market_request',return_value={'bars':bars}) as req,patch.object(main,'_stonks_stream_plan') as plan:
   data=main.stonks_btc_chart_api().get_json();self.assertTrue(data['zero_tokens']);self.assertEqual(data['symbol'],'AAPL');self.assertEqual(req.call_args.kwargs['params']['timeframe'],'4Hour');self.assertEqual(req.call_args.kwargs['params']['feed'],'iex');self.assertEqual(plan.call_args.args[0]['chart_symbol'],'AAPL')
 def test_asset_search_uses_broker_no_model(self):
  with main.app.test_request_context('/api/stonks/chart/assets?q=apple'),patch.object(main,'_alpaca_paper_request',return_value=[{'symbol':'AAPL','name':'Apple Inc','tradable':True},{'symbol':'BAD','name':'Apple fake','tradable':False}]),patch('app.agent.api_text') as model:
   data=main.stonks_chart_assets_api().get_json();self.assertEqual([a['symbol'] for a in data['assets']],['AAPL']);model.assert_not_called()
 def test_persisted_provider_failure_is_not_processing(self):
  result=media._result({'id':'fixture','payload':{}},{'status':'ERROR','checkpoint':{'stage':'characters','status':'blocked','error_code':'task_failed','submission_state':'PROCESSING'}})
  self.assertEqual(result['submission_state'],'FAILED')
 def test_direct_endpoint_requires_csrf(self):
  with main.app.test_request_context('/api/holdings/media/direct/generate',method='POST',json={'story':'Original'}):
   response,status=main.holdings_media_direct_api('generate');self.assertEqual(status,403)
 def test_tiktok_privacy_never_falls_back_to_public(self):
  from app.social_publish import tiktok_direct_post
  from unittest.mock import Mock
  info=Mock(ok=True);info.json.return_value={'data':{'privacy_level_options':['PUBLIC_TO_EVERYONE']}}
  with patch.dict(os.environ,{'TIKTOK_ACCESS_TOKEN':'fixture'}),patch('app.social_publish.requests.post',return_value=info) as request:
   with self.assertRaises(ValueError):tiktok_direct_post('https://fixture.test/video','caption',privacy='SELF_ONLY',confirmed=True)
   self.assertEqual(request.call_count,1)
if __name__=='__main__':
 try:result=unittest.TextTestRunner().run(unittest.defaultTestLoader.loadTestsFromTestCase(Release3310))
 finally:env.stop();shutil.rmtree(temp)
 if not result.wasSuccessful():raise SystemExit(1)
