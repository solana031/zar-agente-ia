import hashlib,hmac,json,os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch,Mock
from flask import Flask
from app import reposnews as rn,reposnews_inbox as inbox

class InstagramInboxTest(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.env=patch.dict(os.environ,{'ZAR_DATA_DIR':self.tmp.name,'INSTAGRAM_IG_USER_ID':'account','INSTAGRAM_REPOSNEWS_SENDERS':'sender','INSTAGRAM_APP_SECRET':'fixture-secret','INSTAGRAM_WEBHOOK_VERIFY_TOKEN':'fixture-verify'});self.env.start()
  rn.write({'owner':'owner','articles':[]});self.app=Flask(__name__);self.app.secret_key='fixture-session';inbox.register(self.app,lambda:'owner');self.client=self.app.test_client()
 def tearDown(self):self.env.stop();self.tmp.cleanup()
 def event(self,text='https://github.com/example/project',mid='one',sender='sender',attachments=None):
  return {'object':'instagram','entry':[{'id':'account','messaging':[{'sender':{'id':sender},'recipient':{'id':'account'},'message':{'mid':mid,'text':text,'attachments':attachments or []}}]}]}
 def test_oauth_not_configured_and_invalid_state(self):
  with patch.dict(os.environ,{'INSTAGRAM_APP_ID':'','INSTAGRAM_APP_SECRET':''}):
   self.assertEqual(self.client.get('/api/reposnews/instagram/connect').status_code,409)
  self.assertEqual(self.client.get('/api/reposnews/instagram/callback?state=wrong&code=fixture').status_code,403)
 def test_oauth_missing_scope_does_not_store_token(self):
  with self.client.session_transaction() as session:session['reposnews_ig_state']={'value':'fixture-state','expires':9999999999}
  token=Mock(ok=True);token.json.return_value={'access_token':'fixture-token','user_id':'account'}
  identity=Mock(ok=True);identity.json.return_value={'user_id':'account','username':'zaragente031'}
  permissions=Mock(ok=True);permissions.json.return_value={'data':[{'permission':inbox.PERMISSIONS[0],'status':'granted'},{'permission':inbox.PERMISSIONS[1],'status':'declined'}]}
  with patch.dict(os.environ,{'INSTAGRAM_APP_ID':'fixture-app'}),patch.object(inbox.requests,'post',return_value=token),patch.object(inbox.requests,'get',side_effect=[identity,permissions]):
   response=self.client.get('/api/reposnews/instagram/callback?state=fixture-state&code=fixture')
  self.assertEqual(response.status_code,400);self.assertEqual(response.json['denied'],[inbox.PERMISSIONS[1]])
  self.assertFalse((rn._path().parent/'instagram-oauth').exists())
 def test_oauth_stores_only_verified_operational_identity_and_scopes(self):
  with self.client.session_transaction() as session:session['reposnews_ig_state']={'value':'fixture-state','expires':9999999999}
  token=Mock(ok=True);token.json.return_value={'access_token':'fixture-token','user_id':'account'}
  identity=Mock(ok=True);identity.json.return_value={'user_id':'account','username':'zaragente031'}
  permissions=Mock(ok=True);permissions.json.return_value={'data':[{'permission':p,'status':'granted'} for p in inbox.PERMISSIONS]}
  with patch.dict(os.environ,{'INSTAGRAM_APP_ID':'fixture-app'}),patch.object(inbox.requests,'post',return_value=token),patch.object(inbox.requests,'get',side_effect=[identity,permissions]):
   self.assertEqual(self.client.get('/api/reposnews/instagram/callback?state=fixture-state&code=fixture').status_code,302)
  self.assertNotIn('fixture-token',(rn._path().parent/'instagram-oauth').read_text())
  result=inbox.integration();self.assertEqual(result['permissions']['status'],'VERIFIED');self.assertEqual(result['oauth'],'CONNECTED')
  self.assertNotIn('fixture-token',json.dumps(result));self.assertEqual(result['facebook_page']['status'],'ACTION_REQUIRED')
 def test_capability_tracks_permalink_without_claiming_full_media(self):
  inbox.receive(self.event(text='',attachments=[{'type':'share','payload':{'url':'https://www.instagram.com/reel/fixture/'}}]))
  result=inbox.integration();self.assertEqual(result['reel_access'],'PERMALINK_ONLY');self.assertEqual(result['last_event']['status'],'RECEIVED')
 def test_discard_survives_late_worker_updates(self):
  item=inbox.receive(self.event())[0];inbox.update(item,status='DISCARDED');inbox.update(item,status='READY')
  self.assertEqual(rn.read()['instagram_inbox'][0]['status'],'DISCARDED')
 def test_caption_redacts_credentials_and_query(self):
  self.assertNotIn('fixture-secret',inbox.safe_caption('AI api_key=fixture-secret https://github.com/example/project?token=fixture-secret'))
 def test_media_cleanup_without_fetching_instagram_page(self):
  item=inbox.receive(self.event(text='',attachments=[{'type':'share','payload':{'url':'https://www.instagram.com/reel/fixture?secret=fixture'}}]))[0]
  with patch('app.browser_network.start_proxy') as proxy:
   self.assertEqual(inbox.analyze_media(item),{});proxy.return_value.shutdown.assert_called_once()
  self.assertFalse((rn._path().parent/'inbound'/item).exists())
 def test_signature_and_challenge(self):
  raw=json.dumps(self.event()).encode();signature='sha256='+hmac.new(b'fixture-secret',raw,hashlib.sha256).hexdigest()
  self.assertTrue(inbox.verify_signature(raw,signature));self.assertFalse(inbox.verify_signature(raw+b' ',signature))
  self.assertEqual(self.client.get('/api/reposnews/instagram/webhook?hub.mode=subscribe&hub.verify_token=wrong&hub.challenge=test').status_code,403)
  response=self.client.get('/api/reposnews/instagram/webhook?hub.mode=subscribe&hub.verify_token=fixture-verify&hub.challenge=test');self.assertEqual(response.data,b'test')
  self.assertTrue(rn.read()['instagram_webhook_verified_at'])
 def test_signed_webhook_persists_before_ack(self):
  raw=json.dumps(self.event()).encode();signature='sha256='+hmac.new(b'fixture-secret',raw,hashlib.sha256).hexdigest()
  with patch.object(inbox,'start_worker') as worker:
   response=self.client.post('/api/reposnews/instagram/webhook',data=raw,headers={'X-Hub-Signature-256':signature});self.assertEqual(response.status_code,200);worker.assert_called_once()
  self.assertEqual(len(rn.read()['instagram_inbox']),1)
  self.assertEqual(self.client.post('/api/reposnews/instagram/webhook',data=raw).status_code,403)
 def test_dedup_id_url(self):
  self.assertEqual(len(inbox.receive(self.event())),1);self.assertEqual(inbox.receive(self.event()),[])
  inbox.receive(self.event(mid='two'));self.assertEqual(rn.read()['instagram_inbox'][1]['status'],'UPDATE_PROPOSAL')
 def test_private_unrelated_sender_and_text_ignored(self):
  self.assertEqual(inbox.receive(self.event(sender='stranger')),[])
  self.assertEqual(inbox.receive(self.event(text='Private unrelated message')),[])
  self.assertFalse(rn.read().get('instagram_inbox'))
 def test_secure_media_reference_not_frontend(self):
  ids=inbox.receive(self.event(text='',attachments=[{'type':'video','payload':{'url':'https://scontent.example.fbcdn.net/video.mp4?secret=fixture'}}]))
  self.assertEqual(len(ids),1);self.assertNotIn('secret=fixture',json.dumps(rn.read()))
  path=rn._path().parent/'inbound'/ids[0];self.assertNotIn('secret=fixture',path.read_text());self.assertIn('ZAR_OAUTH_ENCRYPTED',path.read_text())
 def test_unsafe_url(self):
  for url in ('http://example.com','https://user:password@example.com/','https://example.com:8080/'):
   self.assertEqual(inbox.clean_url(url),'')
 def test_shared_permalink_only_is_honest(self):
  item=inbox.receive(self.event(text='https://www.instagram.com/reel/fixture',attachments=[{'type':'share','payload':{'url':'https://www.instagram.com/reel/fixture'}}]))[0]
  with patch('app.jev_decision.proposal',return_value={'decision':'ALLOW'}),patch.object(inbox,'analyze_media',return_value={}),patch.object(inbox,'public_discovery',return_value={'status':'LOGIN_REQUIRED'}):inbox.process(item)
  row=rn.read()['instagram_inbox'][0];self.assertEqual(row['status'],'ACTION_REQUIRED');self.assertIn('META_SHARED_URL_ONLY',row['error']);self.assertEqual(rn.read()['articles'],[])
 def test_public_fallback_never_reuses_authenticated_browser_or_stores_cookies(self):
  with patch('app.zar_browser.Actor') as actor:
   actor.return_value.run.return_value={'ok':True,'security_state':'READY','text':'Software https://github.com/example/project','storage':{'cookies':['fixture-private']},'screenshot':'fixture-private'}
   result=inbox.public_discovery('https://www.instagram.com/reel/fixture/')
   self.assertEqual(result['status'],'PUBLIC_TEXT_AVAILABLE');actor.return_value.close.assert_called_once()
   self.assertTrue(actor.call_args.args[0].startswith('reposnews-public-'));self.assertNotIn('fixture-private',json.dumps(result))
 def test_public_fallback_respects_login_and_unsupported_urls(self):
  with patch('app.zar_browser.Actor') as actor:
   self.assertEqual(inbox.public_discovery('https://www.instagram.com/accounts/login/'),{});actor.assert_not_called()
   actor.return_value.run.return_value={'ok':True,'security_state':'LOGIN_REQUIRED','storage':{'cookies':['fixture']}}
   self.assertEqual(inbox.public_discovery('https://www.instagram.com/p/fixture/'),{'status':'PUBLIC_CONTENT_BLOCKED'})
 def test_automatic_draft_never_publishes(self):
  item=inbox.receive(self.event())[0]
  article={'id':'example-project','repo':'example/project','published':False,'state':'READY'}
  with patch('app.jev_decision.proposal',return_value={'decision':'ALLOW'}),patch.object(inbox,'analyze_media',return_value={}),patch.object(inbox,'research',return_value={'repo':'example/project'}),patch.object(inbox,'build',return_value=article),patch.object(rn,'operate') as publish:
   inbox.process(item);publish.assert_not_called()
  data=rn.read();self.assertEqual(data['instagram_inbox'][0]['status'],'READY');self.assertFalse(data['articles'][0]['published'])
 def test_generation_failure_persists_and_retries_bounded(self):
  item=inbox.receive(self.event())[0]
  with patch('app.jev_decision.proposal',return_value={'decision':'ALLOW'}),patch.object(inbox,'analyze_media',return_value={}),patch.object(inbox,'research',side_effect=ValueError('fixture')) as research:
   for _ in range(4):inbox.process(item)
   self.assertEqual(research.call_count,2)
  row=rn.read()['instagram_inbox'][0];self.assertEqual(row['status'],'FAILED');self.assertEqual(row['attempts'],2)
 def test_builder_rejects_invented_installation(self):
  generated={k:('word '*260 if k.startswith('body') else 'Fixture title') for k in ('title_es','title_en','summary_es','summary_en','body_es','body_en')};generated['commands']=['pip install invented']
  with patch.object(inbox,'generate_json',return_value=generated):
   with self.assertRaisesRegex(ValueError,'UNVERIFIED_COMMAND'):inbox.build({'readme':'no install command'},'discovery')

if __name__=='__main__':unittest.main()
