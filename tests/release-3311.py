"""Focused offline 33.3.11 checks; never generates, posts or sends orders."""
import runpy,unittest
from pathlib import Path
from unittest.mock import Mock,patch
base=runpy.run_path(str(Path(__file__).with_name('release-3310.py')))
media=base['media'];surface=base['media_surface'];holdings=base['holdings']
class Release3311(base['Release3310']):
 def fixture(self):
  task=media.queue_story(self.scope,'Historia real',options={'duration':30})
  record=media._read(self.scope,task['id']);record.update(status='ERROR',checkpoint={'stage':'characters','status':'blocked','project_id':'p1','tasks':[{'task_id':'ingested'}],'active_task':{'task_id':'failed1','status':'failed'}})
  media._save(self.scope,task['id'],record);return task,record
 def test_retry_preserves_prior_outputs_and_stage(self):
  task,_=self.fixture();client=Mock();client.capabilities.return_value={'configured':True}
  with patch.object(media,'_client',return_value=client):surface.retry_stage(self.scope,task['id'])
  cp=media._read(self.scope,task['id'])['checkpoint'];self.assertEqual(cp['stage'],'characters');self.assertEqual(cp['project_id'],'p1');self.assertEqual(cp['tasks'][0]['task_id'],'ingested');self.assertNotIn('active_task',cp)
  client.assert_not_called()
 def test_retry_missing_credentials_never_submits(self):
  task,_=self.fixture();client=Mock();client.capabilities.return_value={'configured':False}
  with patch.object(media,'_client',return_value=client),self.assertRaises(ValueError):surface.retry_stage(self.scope,task['id'])
  self.assertEqual(media._read(self.scope,task['id'])['checkpoint']['active_task']['task_id'],'failed1');client.advance.assert_not_called()
 def test_srt_is_persisted_and_requires_new_review(self):
  task,_=self.fixture();text='1\n00:00:00,000 --> 00:00:02,000\nHistoria\n'
  result=surface.subtitles(self.scope,{'task_id':task['id'],'text':text,'enabled':False})
  self.assertEqual(media._path(self.scope,task['id']).with_suffix('.srt').read_text(encoding='utf-8'),text)
  record=media._read(self.scope,task['id']);self.assertTrue(record['needs_final_render']);self.assertFalse(record['subtitles']['enabled']);self.assertIn(task['id'],result['url'])
 def test_invalid_srt_is_rejected(self):
  task,_=self.fixture()
  with self.assertRaises(ValueError):surface.subtitles(self.scope,{'task_id':task['id'],'text':'untimed words'})
 def test_cluster_preferences_are_scoped(self):
  saved=base['orchestration_map'].save(self.scope,{'zoom':.7,'pan_x':20,'pan_y':50,'collapsed':['Media','TRADING','bad']})
  self.assertEqual(saved['collapsed'],['Media','TRADING']);self.assertEqual(holdings.read(self.scope)['map_view']['zoom'],.7)
 def test_global_stop_blocks_stage_retry(self):
  task,_=self.fixture();d=holdings.read(self.scope);d['global_stop']=True;holdings.write(self.scope,d)
  with patch.object(media,'_client') as client,self.assertRaises(ValueError):surface.retry_stage(self.scope,task['id'])
  client.assert_not_called()
 def test_youtube_no_channel_and_real_handle(self):
  from app import identity_center
  creds=Mock();creds.scopes=[identity_center.PREFIX+'youtube.readonly',identity_center.PREFIX+'youtube.upload'];creds.token='fixture'
  response=Mock(ok=True);response.json.return_value={'items':[]}
  with patch.object(identity_center.requests,'get',return_value=response):result=identity_center._probe('YOUTUBE',creds)
  self.assertEqual(result['status'],'NOT_ELIGIBLE');self.assertFalse(result['upload_capability'])
  response.json.return_value={'items':[{'id':'real-channel','snippet':{'title':'Real title','customUrl':'@real-returned-handle'}}]}
  with patch.object(identity_center.requests,'get',return_value=response):result=identity_center._probe('YOUTUBE',creds)
  self.assertTrue(result['upload_capability']);self.assertEqual(result['channels'][0]['handle'],'@real-returned-handle')
 def test_social_missing_configuration_is_action_required(self):
  from app.social_publish import publishing_readiness
  with patch.dict(base['os'].environ,{'TIKTOK_ACCESS_TOKEN':'','INSTAGRAM_ACCESS_TOKEN':'','INSTAGRAM_IG_USER_ID':''}):
   self.assertFalse(publishing_readiness('instagram')['connected']);self.assertFalse(publishing_readiness('tiktok')['connected'])
 def test_oauth_never_accumulates_incompatible_youtube_grants(self):
  from app import cloud_auth
  from urllib.parse import parse_qs,urlsplit
  previous=Mock();previous.scopes=cloud_auth.SERVICE_SCOPES['core']+cloud_auth.SERVICE_SCOPES['youtube']+cloud_auth.SERVICE_SCOPES['docs']
  with patch.object(cloud_auth,'_oauth_client',return_value=('fixture','fixture')),patch.object(cloud_auth,'get_credentials',return_value=previous):
   for service in ('core','docs','youtube'):
    url,_,_=cloud_auth.authorization_url(service=service)
    params=parse_qs(urlsplit(url).query);self.assertEqual(params['include_granted_scopes'],['false'])
    if service=='youtube':self.assertNotIn('drive.file',params['scope'][0])
    else:self.assertNotIn('/youtube',params['scope'][0]);self.assertIn('/documents',params['scope'][0])
if __name__=='__main__':
 try:result=unittest.TextTestRunner().run(unittest.defaultTestLoader.loadTestsFromTestCase(Release3311))
 finally:base['env'].stop();base['shutil'].rmtree(base['temp'])
 if not result.wasSuccessful():raise SystemExit(1)
