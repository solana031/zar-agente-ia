import hashlib,hmac,json,os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch,Mock
from flask import Flask
from app import reposnews as rn,reposnews_inbox as inbox

class InstagramInboxTest(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.env=patch.dict(os.environ,{'ZAR_DATA_DIR':self.tmp.name,'INSTAGRAM_IG_USER_ID':'account','INSTAGRAM_REPOSNEWS_SENDERS':'sender','INSTAGRAM_APP_SECRET':'fixture-secret','INSTAGRAM_WEBHOOK_VERIFY_TOKEN':'fixture-verify'});self.env.start()
  rn.write({'owner':'owner','articles':[]});self.app=Flask(__name__);self.app.secret_key='fixture-session';inbox.register(self.app,lambda:'owner');self.client=self.app.test_client();self.client.environ_base['HTTP_ACCEPT']='application/json'
 def tearDown(self):self.env.stop();self.tmp.cleanup()
 def event(self,text='https://github.com/example/project',mid='one',sender='sender',attachments=None):
  return {'object':'instagram','entry':[{'id':'account','messaging':[{'sender':{'id':sender},'recipient':{'id':'account'},'message':{'mid':mid,'text':text,'attachments':attachments or []}}]}]}
 def test_plain_greeting_confirms_authorized_delivery_without_editorial_draft(self):
  self.assertEqual(inbox.receive(self.event(text='hola2')),[])
  self.assertTrue(rn.read().get('instagram_last_authorized_message'))
  self.assertFalse(rn.read().get('instagram_inbox'))
 def test_changes_messages_envelope_keeps_authorization_checks(self):
  payload=self.event();entry=payload['entry'][0];event=entry.pop('messaging')[0]
  entry['changes']=[{'field':'messages','value':event}]
  self.assertTrue(inbox.record_event_structure(payload)['message_mid_present'])
  self.assertEqual(len(inbox.receive(payload)),1)
  event['sender']['id']='unknown';event['message']['mid']='other'
  self.assertEqual(inbox.receive(payload),[])
 def test_other_changes_fields_never_ingested(self):
  payload=self.event();entry=payload['entry'][0];event=entry.pop('messaging')[0]
  entry['changes']=[{'field':'comments','value':event}]
  self.assertEqual(inbox.receive(payload),[])
  self.assertFalse(rn.read().get('instagram_last_authorized_message'))
 def test_recovery_preserves_item_and_grants_only_two_extra_attempts(self):
  item=inbox.receive(self.event())[0]
  inbox.update(item,status='FAILED',attempts=2,error='AI_HTTP_503; legacy',failed_stage='IDENTIFYING')
  original=rn.read()['instagram_inbox'][0].copy()
  inbox.recover_existing(item)
  row=rn.read()['instagram_inbox'][0]
  for field in ('id','external_id','sender','source_url','received_at','attempts'):
   self.assertEqual(row[field],original[field])
  self.assertEqual(row['attempt_limit'],4);self.assertEqual(len(row['error_history']),1)
  inbox.update(item,status='FAILED_RETRYABLE')
  with self.assertRaises(ValueError):inbox.recover_existing(item)
 def test_permalink_recovery_skips_optional_media_and_classifies_503(self):
  item=inbox.receive(self.event(text='',attachments=[{'type':'share','payload':{'url':'https://www.instagram.com/reel/fixture/'}}]))[0]
  inbox.update(item,status='FAILED',attempts=2);inbox.recover_existing(item)
  inbox.update(item,local_worker_done=True,analysis={'transcript':'Example tool'})
  with patch('app.jev_decision.proposal',return_value={'decision':'ALLOW'}),patch.object(inbox,'analyze_media') as media,patch.object(inbox,'public_metadata',return_value={}) as metadata,patch.object(inbox,'public_discovery',return_value={'status':'PUBLIC_TEXT_AVAILABLE','text':'Example tool'}),patch.object(inbox,'resolve_entity',side_effect=ValueError('AI_PROVIDER_503')):
   inbox.process(item);media.assert_not_called();metadata.assert_called_once()
  row=rn.read()['instagram_inbox'][0]
  self.assertEqual(row['status'],'FAILED_RETRYABLE');self.assertEqual(row['attempts'],3)
  self.assertEqual(row['error_diagnostic']['component'],'IDENTIFYING')
  self.assertEqual(row['error_diagnostic']['provider'],'Gemini')
  self.assertEqual(row['error_diagnostic']['http'],503)
 def test_no_accessible_permalink_text_does_not_invent_a_project(self):
  self.assertEqual(inbox.resolve_entity('')['reason'],'NO_ACCESSIBLE_DISCOVERY_TEXT')
 def test_local_single_word_cannot_truncate_a_compound_name(self):
  self.assertIsNone(inbox.complete_media_name({'project_names':['open'],'transcript':"It's called Open Montage."}))
  self.assertIsNone(inbox.complete_media_name({'project_names':['real'],'transcript':"It's called Real Mimic."}))
  self.assertEqual(inbox.complete_media_name({'project_names':['OpenCode'],'transcript':'Se llama OpenCode y sirve para programar.'}),'OpenCode')
 def test_repository_found_on_a_site_must_corroborate_that_domain(self):
  item=inbox.receive(self.event(text='https://www.instagram.com/reel/fixture/'))[0]
  inbox.update(item,local_worker_done=True,analysis={'project_names':['Example'],'transcript':'Example'})
  resolution={'status':'RESOLVED','type':'REPOSITORY','repo':'official/Example','website':'https://example.org/'}
  package={'repo':'official/Example','metadata':{'homepage':'https://unrelated.test/'},'readme':'No official backlink','sources':['https://github.com/official/Example'],'verified_at':'today'}
  with patch('app.jev_decision.proposal',return_value={'decision':'ALLOW'}),patch.object(inbox,'public_metadata',return_value={}),patch('app.reposnews_discovery.service_resolution',return_value=resolution),patch.object(inbox,'research',return_value=package),patch.object(inbox,'build') as build:
   inbox.process(item)
  build.assert_not_called();row=rn.read()['instagram_inbox'][0]
  self.assertEqual(row['error'],'OFFICIAL_REPOSITORY_UNRESOLVED');self.assertEqual(row['status'],'FAILED_SOURCE')
 def test_visible_github_owner_can_identify_a_repo_without_a_separate_homepage(self):
  result={'total_count':200,'items':[{'name':'ReelMimic','full_name':'creator123/ReelMimic','homepage':''},{'name':'ReelMimic','full_name':'another123/ReelMimic','homepage':''}]}
  with patch.object(rn,'github',return_value=result),patch.object(inbox,'homepage_confirms_repository') as homepage:
   unresolved=inbox.resolve_entity('Tool: ReelMimic',deterministic_only=True)
   resolved=inbox.resolve_entity('Tool: ReelMimic',deterministic_only=True,visual_evidence='creator123 Ask Gemini github.com/creator123... README ReelMimic')
  self.assertEqual(unresolved['reason'],'SEARCH_NOT_EXHAUSTIVE');self.assertEqual(resolved['repo'],'creator123/ReelMimic')
  self.assertEqual(resolved['confidence'],'VISIBLE_GITHUB_OWNER_AND_EXACT_NAME');homepage.assert_not_called()
 def test_two_visible_owners_are_not_resolved_by_popularity(self):
  result={'total_count':200,'items':[{'name':'Tool','full_name':'creator123/Tool'},{'name':'Tool','full_name':'another123/Tool'}]}
  with patch.object(rn,'github',return_value=result):
   resolution=inbox.resolve_entity('Tool: Tool',deterministic_only=True,visual_evidence='creator123 github.com\nanother123 github.com')
  self.assertEqual(resolution['status'],'NEEDS_DISAMBIGUATION')
 def test_github_limit_preserves_http_and_waits_without_losing_item(self):
  import time
  item=inbox.receive(self.event())[0];inbox.update(item,local_worker_done=True)
  with patch('app.jev_decision.proposal',return_value={'decision':'ALLOW'}),patch.object(inbox,'research',side_effect=rn.GitHubReadError(429,120)):
   inbox.process(item)
  row=rn.read()['instagram_inbox'][0]
  self.assertEqual(row['status'],'FAILED_RETRYABLE');self.assertEqual(row['error'],'GITHUB_RATE_LIMIT')
  self.assertEqual(row['error_diagnostic']['http'],429);self.assertEqual(row['error_diagnostic']['provider'],'GitHub')
  self.assertGreater(row['retry_after'],time.time()+115);self.assertEqual(row['attempts'],1)
 def test_missing_official_source_is_permanent_and_keeps_http_diagnostic(self):
  import requests
  item=inbox.receive(self.event())[0];inbox.update(item,local_worker_done=True)
  response=requests.Response();response.status_code=410
  failure=requests.HTTPError('gone',response=response)
  with patch('app.jev_decision.proposal',return_value={'decision':'ALLOW'}),patch.object(inbox,'research',side_effect=failure):inbox.process(item)
  row=rn.read()['instagram_inbox'][0]
  self.assertEqual(row['status'],'FAILED_PERMANENT');self.assertEqual(row['error_diagnostic']['http'],410)
  self.assertFalse(row['error_diagnostic']['retryable'])
  self.assertEqual(rn.read()['editorial_notifications'][0]['status'],'FAILED_PERMANENT')
 def test_public_metadata_extracts_head_clues(self):
  meta=inbox.extract_public_metadata('<title>Project: Example</title><meta property="og:description" content="Tool: Example"><meta property="og:image" content="https://example.com/a.png"><script>private junk</script>')
  self.assertIn('Example',meta['text']);self.assertNotIn('private junk',meta['text']);self.assertTrue(meta['og:image'])
 def test_deterministic_resolution_does_not_require_ai(self):
  with patch.object(inbox,'generate_json') as ai,patch.object(rn,'github',return_value={'items':[{'name':'Example','full_name':'org/Example','homepage':'https://example.com'}],'total_count':1}),patch.object(inbox,'homepage_confirms_repository',return_value=True):
   result=inbox.resolve_entity('Project: Example',deterministic_only=True)
  ai.assert_not_called();self.assertEqual(result['repo'],'org/Example')
 def test_metadata_recovery_once_preserves_identity(self):
  item=inbox.receive(self.event())[0];inbox.update(item,status='FAILED_SOURCE',attempts=4)
  original=rn.read()['instagram_inbox'][0].copy();inbox.recover_metadata_once(item)
  row=rn.read()['instagram_inbox'][0]
  for key in ('id','external_id','source_url','sender','received_at'):self.assertEqual(row[key],original[key])
  self.assertEqual(row['attempt_limit'],5)
  inbox.update(item,status='FAILED_SOURCE')
  with self.assertRaises(ValueError):inbox.recover_metadata_once(item)
 def test_clarification_is_generic_and_continues_same_item_automatically(self):
  item=inbox.receive(self.event())[0];inbox.update(item,status='NEEDS_DISAMBIGUATION',attempts=5)
  rn.operate('owner','inbox_resolve',{'id':item,'name':'Example Service'})
  data=rn.read();row=data['instagram_inbox'][0]
  self.assertEqual(row['id'],item);self.assertEqual(row['status'],'RECEIVED')
  self.assertEqual(row['clarified_project'],'Example Service');self.assertEqual(row['attempt_limit'],13)
  self.assertEqual(data['articles'],[])

 def test_oauth_not_configured_and_invalid_state(self):
  with patch.dict(os.environ,{'INSTAGRAM_APP_ID':'','INSTAGRAM_APP_SECRET':''}):
   self.assertEqual(self.client.get('/api/reposnews/instagram/connect').status_code,409)
  self.assertEqual(self.client.get('/api/reposnews/instagram/callback?state=wrong&code=fixture').status_code,403)
 def test_oauth_missing_scope_does_not_store_token(self):
  with self.client.session_transaction() as session:session['reposnews_ig_state']={'value':'fixture-state','expires':9999999999}
  token=Mock(ok=True);token.json.return_value={'access_token':'fixture-token','user_id':'account'}
  identity=Mock(ok=True);identity.json.return_value={'user_id':'12345','username':'zaragente031'}
  permissions=Mock(ok=True,status_code=200);permissions.json.return_value={'data':[{'permission':inbox.PERMISSIONS[0],'status':'granted'},{'permission':inbox.PERMISSIONS[1],'status':'declined'}]}
  with patch.dict(os.environ,{'INSTAGRAM_APP_ID':'fixture-app'}),patch.object(inbox.requests,'post',return_value=token),patch.object(inbox.requests,'get',side_effect=[identity,permissions,Mock(ok=True,json=lambda:{'data':[]}),Mock(ok=False,status_code=403,json=lambda:{'error':{'code':10,'message':'Permission denied'}})]):
   response=self.client.get('/api/reposnews/instagram/callback?state=fixture-state&code=fixture')
  self.assertEqual(response.status_code,400);self.assertEqual(response.json['denied'],[inbox.PERMISSIONS[1]])
  self.assertFalse((rn._path().parent/'instagram-oauth').exists())
 def test_oauth_stores_only_verified_operational_identity_and_scopes(self):
  with self.client.session_transaction() as session:session['reposnews_ig_state']={'value':'fixture-state','expires':9999999999}
  token=Mock(ok=True);token.json.return_value={'access_token':'fixture-token','user_id':'account'}
  identity=Mock(ok=True);identity.json.return_value={'user_id':'12345','username':'zaragente031'}
  permissions=Mock(ok=True,status_code=200);permissions.json.return_value={'data':[{'permission':p,'status':'granted'} for p in inbox.PERMISSIONS]}
  with patch.dict(os.environ,{'INSTAGRAM_APP_ID':'fixture-app'}),patch.object(inbox.requests,'post',side_effect=[token,Mock(ok=True,json=lambda:{'success':True})]),patch.object(inbox.requests,'get',side_effect=[identity,permissions,Mock(ok=True,json=lambda:{'data':[]}),Mock(ok=True,json=lambda:{'data':[]})]):
   self.assertEqual(self.client.get('/api/reposnews/instagram/callback?state=fixture-state&code=fixture').status_code,302)
  self.assertNotIn('fixture-token',(rn._path().parent/'instagram-oauth').read_text())
  result=inbox.integration();self.assertEqual(result['permissions']['status'],'VERIFIED');self.assertEqual(result['oauth'],'CONNECTED')
  self.assertNotIn('fixture-token',json.dumps(result));self.assertEqual(result['facebook_page']['status'],'NOT_REQUIRED_FOR_INSTAGRAM_LOGIN')
 def test_capability_tracks_permalink_without_claiming_full_media(self):
  inbox.receive(self.event(text='',attachments=[{'type':'share','payload':{'url':'https://www.instagram.com/reel/fixture/'}}]))
  result=inbox.integration();self.assertEqual(result['reel_access'],'PERMALINK_ONLY');self.assertEqual(result['last_event']['status'],'RECEIVED')

 def test_permission_endpoint_unavailable_uses_read_only_capabilities(self):
  unavailable=Mock(ok=False,status_code=400,json=lambda:{'error':{'code':100,'error_subcode':33,'type':'GraphMethodException','message':'Unsupported request fixture-token'}})
  with patch.object(inbox.requests,'get',side_effect=[unavailable,Mock(ok=True,json=lambda:{'data':[]}),Mock(ok=True,json=lambda:{'data':[]})]) as get:
   result=inbox.verify_capabilities('fixture-token','12345')
  self.assertEqual(result['granted'],list(inbox.PERMISSIONS));self.assertEqual(result['verification_method'],'FUNCTIONAL_CAPABILITY_TEST')
  self.assertEqual(result['permission_endpoint']['code'],100);self.assertNotIn('fixture-token',json.dumps(result))
  self.assertTrue(get.call_args_list[-1].args[0].endswith('/me/conversations'))
  self.assertEqual(get.call_args_list[-1].kwargs['params']['fields'],'id')

 def test_subscription_requires_provider_acknowledgement(self):
  with patch.object(inbox.requests,'post',return_value=Mock(ok=True,json=lambda:{'success':False})):
   self.assertEqual(inbox.subscribe_messages('fixture-token','12345')['status'],'UNKNOWN')
  with patch.object(inbox.requests,'post',return_value=Mock(ok=True,json=lambda:{'success':True})) as post:
   self.assertEqual(inbox.subscribe_messages('fixture-token','12345')['status'],'VERIFIED')
   self.assertEqual(post.call_args.kwargs['data'],{'subscribed_fields':'messages'})

 def test_browser_failure_redirects_without_code_or_token(self):
  with self.client.session_transaction() as session:session['reposnews_ig_state']={'value':'fixture-state','expires':9999999999}
  with patch.dict(os.environ,{'INSTAGRAM_APP_ID':'fixture-app'}),patch.object(inbox.requests,'post',return_value=Mock(ok=False,status_code=400,json=lambda:{'error':{'code':100,'message':'Bad request'}})):
   response=self.client.get('/api/reposnews/instagram/callback?state=fixture-state&code=fixture',headers={'Accept':'text/html'})
  self.assertEqual(response.status_code,302);self.assertEqual(response.location,'/?zar_workspace=sites#reposnewsEditor')
  self.assertEqual(rn.read()['instagram_callback']['status'],'ERROR')

 def test_personal_instagram_is_not_persisted(self):
  with self.client.session_transaction() as session:session['reposnews_ig_state']={'value':'fixture-state','expires':9999999999}
  with patch.dict(os.environ,{'INSTAGRAM_APP_ID':'fixture-app'}),patch.object(inbox.requests,'post',return_value=Mock(ok=True,json=lambda:{'access_token':'fixture-token','user_id':'12345'})),patch.object(inbox.requests,'get',return_value=Mock(ok=True,json=lambda:{'username':'personal','user_id':'12345'})):
   self.assertEqual(self.client.get('/api/reposnews/instagram/callback?state=fixture-state&code=fixture').status_code,400)
  self.assertFalse((rn._path().parent/'instagram-oauth-pending').exists())

 def test_reverify_recovers_encrypted_token_without_code_exchange(self):
  from app import oauth_vault
  root=rn._path().parent
  oauth_vault.persist(root/'instagram-oauth-pending',json.dumps({'access_token':'fixture-token','user_id':'12345','username':'zaragente031'}),root)
  with patch.object(inbox.requests,'get',side_effect=[Mock(ok=True,json=lambda:{'username':'zaragente031'}),Mock(ok=False,status_code=400,json=lambda:{'error':{'code':100}}),Mock(ok=True,json=lambda:{'data':[]}),Mock(ok=True,json=lambda:{'data':[]})]),patch.object(inbox.requests,'post',return_value=Mock(ok=True,json=lambda:{'success':True})) as post:
   result=inbox.reverify_connection()
  self.assertEqual(result['status'],'CONNECTED');self.assertTrue((root/'instagram-oauth').exists())
  self.assertTrue(post.call_args.args[0].endswith('/12345/subscribed_apps'))
  self.assertNotIn('fixture-token',json.dumps(result));self.assertNotIn('fixture-token',(root/'instagram-oauth').read_text())

 def test_reverify_missing_token_never_requests_oauth(self):
  with patch.object(inbox.requests,'get') as get,patch.object(inbox.requests,'post') as post:
   self.assertEqual(inbox.reverify_connection()['error'],'TOKEN_UNAVAILABLE');get.assert_not_called();post.assert_not_called()

 def test_authorized_username_resolves_only_from_official_sender_metadata(self):
  with patch.object(inbox,'credentials',return_value={'access_token':'fixture-token'}),patch.object(inbox.requests,'get',side_effect=[Mock(ok=True,json=lambda:{'data':[{'id':'conversation'}]}),Mock(ok=True,json=lambda:{'messages':{'data':[{'id':'message'}]}}),Mock(ok=True,json=lambda:{'from':{'username':'solana031','id':'98765'}})]) as get:
   result=inbox.authorize_solana_sender()
  self.assertEqual(result['id'],'98765');self.assertIn('98765',inbox.sender_ids())
  self.assertEqual(get.call_args.kwargs['params'],{'fields':'from'})
  self.assertNotIn('fixture-token',json.dumps(rn.read()))

 def test_sender_resolver_never_authorizes_a_different_username(self):
  with patch.object(inbox,'credentials',return_value={'access_token':'fixture-token'}),patch.object(inbox.requests,'get',side_effect=[Mock(ok=True,json=lambda:{'data':[{'id':'conversation'}]}),Mock(ok=True,json=lambda:{'messages':{'data':[{'id':'message'}]}}),Mock(ok=True,json=lambda:{'from':{'username':'stranger','id':'98765'}})]):
   with self.assertRaises(ValueError):inbox.authorize_solana_sender()
  self.assertNotIn('98765',inbox.sender_ids());self.assertFalse(rn.read().get('instagram_authorized_senders'))

 def test_signed_structure_records_presence_without_unapproved_content(self):
  payload=self.event(text='fixture-private-text',sender='unknown');payload['entry'][0]['messaging'][0]['timestamp']=123
  with patch.dict(os.environ,{'INSTAGRAM_REPOSNEWS_SENDERS':''}):
   summary=inbox.record_event_structure(payload);self.assertEqual(inbox.receive(payload),[])
  self.assertTrue(summary['sender_id_present']);self.assertTrue(summary['message_mid_present'])
  self.assertFalse(summary['allowlist_configured']);self.assertNotIn('fixture-private-text',json.dumps(summary));self.assertNotIn('unknown',json.dumps(summary))

 def test_subscription_readback_matches_exact_app_and_messages(self):
  with patch.object(inbox,'credentials',return_value={'access_token':'fixture-token','user_id':'12345'}),patch.object(inbox.requests,'get',return_value=Mock(ok=True,json=lambda:{'data':[{'id':'1705003441255228','subscribed_fields':['messages']}]})):
   self.assertEqual(inbox.inspect_subscription()['status'],'VERIFIED')
  with patch.object(inbox,'credentials',return_value={'access_token':'fixture-token','user_id':'12345'}),patch.object(inbox.requests,'get',return_value=Mock(ok=True,json=lambda:{'data':[{'id':'unrelated','subscribed_fields':['messages']}]})):
   self.assertEqual(inbox.inspect_subscription()['status'],'UNKNOWN')
 def test_discard_survives_late_worker_updates(self):
  item=inbox.receive(self.event())[0];inbox.update(item,status='DISCARDED');inbox.update(item,status='READY')
  self.assertEqual(rn.read()['instagram_inbox'][0]['status'],'DISCARDED')
 def test_caption_redacts_credentials_and_query(self):
  self.assertNotIn('fixture-secret',inbox.safe_caption('AI api_key=fixture-secret https://github.com/example/project?token=fixture-secret'))
 def test_media_cleanup_without_fetching_instagram_page(self):
  item=inbox.receive(self.event(text='',attachments=[{'type':'share','payload':{'url':'https://www.instagram.com/reel/fixture?secret=fixture'}}]))[0]
  with patch('app.browser_network.start_proxy') as proxy:
   self.assertEqual(inbox.analyze_media(item),{});proxy.assert_not_called()
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
  inbox.receive(self.event(mid='two'));self.assertEqual(len(rn.read()['instagram_inbox']),1);self.assertEqual(rn.read()['instagram_inbox'][0]['external_ids'],['one','two'])
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
  with patch('app.jev_decision.proposal',return_value={'decision':'ALLOW'}),patch.object(inbox,'analyze_media',return_value={}),patch.object(inbox,'public_discovery',return_value={'status':'LOGIN_REQUIRED'}),patch.object(inbox,'public_metadata',return_value={}):inbox.process(item)
  row=rn.read()['instagram_inbox'][0];self.assertEqual(row['status'],'WAITING_LOCAL_WORKER');self.assertEqual(row['attempts'],0);self.assertEqual(rn.read()['articles'],[])

 def test_entity_resolves_name_only_with_official_backlink(self):
  candidate={'name':'open-webui','full_name':'open-webui/open-webui','homepage':'https://openwebui.com/','fork':False}
  with patch.object(inbox,'generate_json',return_value={'name':'Open WebUI','ambiguous':False}),patch.object(rn,'github',return_value={'items':[candidate]}),patch.object(inbox,'homepage_confirms_repository',return_value=True):
   result=inbox.resolve_entity('Reel: Open WebUI is a software project')
  self.assertEqual(result['repo'],'open-webui/open-webui');self.assertEqual(result['status'],'RESOLVED')

 def test_entity_does_not_choose_between_exact_candidates(self):
  candidates=[{'name':'tool','full_name':owner+'/tool','homepage':'https://example.org/'} for owner in ('one','two')]
  with patch.object(inbox,'generate_json',return_value={'name':'Tool','ambiguous':False}),patch.object(rn,'github',return_value={'items':candidates}),patch.object(inbox,'homepage_confirms_repository') as verify:
   self.assertEqual(inbox.resolve_entity('Tool project')['status'],'NEEDS_DISAMBIGUATION');verify.assert_not_called()

 def test_entity_rejects_uncorroborated_repository(self):
  with patch.object(inbox,'generate_json',return_value={'name':'Tool','ambiguous':False}),patch.object(rn,'github',return_value={'items':[{'name':'tool','full_name':'one/tool','homepage':'https://example.org/'}]}),patch.object(inbox,'homepage_confirms_repository',return_value=False):
   self.assertEqual(inbox.resolve_entity('Tool project')['reason'],'OFFICIAL_WEBSITE_NOT_CORROBORATED')

 def test_entity_does_not_search_ambiguous_discovery(self):
  with patch.object(inbox,'generate_json',return_value={'name':'Tool','ambiguous':True}),patch.object(rn,'github') as search:
   self.assertEqual(inbox.resolve_entity('Several tools')['status'],'NEEDS_DISAMBIGUATION');search.assert_not_called()
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
  article=rn.article_defaults({'id':'example-project','repo':'example/project','published':False,'state':'READY_PRIVATE','sources':['https://github.com/example/project','https://example.org'],'review_kind':'AUTOMATED_SOURCE_REVIEW',**{k:('verified word '*260 if k.startswith('body') else 'Fixture title') for k in ('title_es','title_en','summary_es','summary_en','body_es','body_en')}})
  with patch('app.jev_decision.proposal',return_value={'decision':'ALLOW'}),patch.object(inbox,'analyze_media',return_value={}),patch.object(inbox,'research',return_value={'repo':'example/project'}),patch.object(inbox,'build',return_value=article),patch.object(rn,'operate') as publish:
   inbox.process(item);publish.assert_not_called()
  data=rn.read();self.assertEqual(data['instagram_inbox'][0]['status'],'READY_PRIVATE');self.assertFalse(data['articles'][0]['published']);self.assertEqual(data['editorial_notifications'][0]['status'],'AWAITING_APPROVAL')
 def test_generation_failure_persists_and_retries_bounded(self):
  item=inbox.receive(self.event())[0]
  with patch('app.jev_decision.proposal',return_value={'decision':'ALLOW'}),patch.object(inbox,'analyze_media',return_value={}),patch.object(inbox,'research',side_effect=ValueError('fixture')) as research:
   for _ in range(10):inbox.process(item)
   self.assertEqual(research.call_count,8)
  row=rn.read()['instagram_inbox'][0];self.assertEqual(row['status'],'FAILED_RETRYABLE');self.assertEqual(row['attempts'],8)
 def test_builder_rejects_invented_installation(self):
  generated={k:('word '*260 if k.startswith('body') else 'Fixture title') for k in ('title_es','title_en','summary_es','summary_en','body_es','body_en')};generated['commands']=['pip install invented']
  with patch.object(inbox,'generate_json',return_value=generated):
   with self.assertRaisesRegex(ValueError,'UNVERIFIED_COMMAND'):inbox.build({'readme':'no install command'},'discovery')

if __name__=='__main__':unittest.main()
