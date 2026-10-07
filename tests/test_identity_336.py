"""Identity, OAuth, Mail and provisioning tests: zero real account/provider writes."""
import os,json,shutil,uuid,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
from urllib.parse import urlparse,parse_qs
from app import holdings,identity_center as center,identity_mail as mail,cloud_auth,orchestration_map
from app import business_orchestration as business

class IdentityTests(unittest.TestCase):
 def setUp(self):
  self.root=Path(__file__).resolve().parents[1];self.tmp=self.root/('zar-336-'+uuid.uuid4().hex);self.tmp.mkdir()
  self.env=patch.dict(os.environ,{'ZAR_DATA_DIR':str(self.tmp)},clear=True);self.env.start();self.scope='identity-offline';self.address='zar.offline@gmail.com'
  center.register_google(self.scope,self.address)
 def tearDown(self):
  self.env.stop();assert self.tmp.resolve().is_relative_to(self.root);shutil.rmtree(self.tmp)
 def test_existing_account_not_signup(self):
  s=center.view(self.scope);self.assertTrue(s['google']['account_exists']);self.assertEqual(s['google']['status'],'NEEDS_OAUTH')
  self.assertEqual(s['google']['email'],self.address);self.assertIn('purpose=zar',s['connect_url']);self.assertNotIn('signup',s['connect_url'])
  center.register_google(self.scope,self.address);self.assertEqual(len(center.view(self.scope)['human_actions']),1)
  accounts=holdings.read(self.scope)['orchestration']['accounts'];self.assertEqual(len(accounts),1);self.assertEqual(accounts[0]['provider'],'GOOGLE')
 def test_no_token_never_active(self):
  with patch.object(cloud_auth,'get_credentials',return_value=None):center.verify_google(self.scope)
  self.assertEqual(center.view(self.scope)['google']['status'],'NEEDS_OAUTH')
 def test_wrong_identity_rejected(self):
  with patch.object(cloud_auth,'get_credentials',return_value=Mock()),patch.object(cloud_auth,'get_account_email',return_value='someone.else@gmail.com'):
   with self.assertRaises(ValueError):center.verify_google(self.scope)
  self.assertEqual(center.view(self.scope)['google']['status'],'NEEDS_OAUTH')
 def test_real_probes_and_granular_permissions(self):
  creds=SimpleNamespace(token='mock-access-token-never-public',scopes=[center.PREFIX+'gmail.modify',center.PREFIX+'drive.file'])
  with patch.object(cloud_auth,'get_credentials',return_value=creds),patch.object(cloud_auth,'get_account_email',return_value=self.address),patch.object(center.requests,'get',return_value=Mock(ok=True,json=lambda:{'emailAddress':self.address,'files':[]})) as get:
   state=center.verify_google(self.scope)
  self.assertEqual(state['google']['status'],'ACTIVE');self.assertEqual(state['capabilities']['GMAIL']['status'],'CONNECTED')
  self.assertEqual(state['capabilities']['YOUTUBE']['status'],'NOT_CONNECTED');self.assertEqual(state['capabilities']['DOCS']['status'],'AVAILABLE')
  self.assertEqual(get.call_count,2);self.assertEqual(state['human_actions'][0]['status'],'DONE')
  self.assertNotIn(creds.token,json.dumps(state));center.register_google(self.scope,self.address);self.assertEqual(len(center.view(self.scope)['human_actions']),1)
 def test_youtube_no_channel_adsense_no_account(self):
  creds=SimpleNamespace(token='offline',scopes=[center.PREFIX+'youtube.readonly',center.PREFIX+'adsense.readonly'])
  with patch.object(center.requests,'get',return_value=Mock(ok=True,json=lambda:{})):
   self.assertEqual(center._probe('YOUTUBE',creds)['status'],'NOT_ELIGIBLE');self.assertEqual(center._probe('ADSENSE',creds)['account_state'],'NO_ACCOUNT')
 def test_provider_error_not_connected(self):
  creds=SimpleNamespace(token='offline',scopes=[center.PREFIX+'calendar'])
  with patch.object(center.requests,'get',return_value=Mock(ok=False,status_code=403)):
   self.assertEqual(center._probe('CALENDAR',creds)['status'],'ERROR')
 def test_public_plans_dedup_and_dynamic_hierarchy(self):
  rows=center.natural_request(self.scope,'Necesito TikTok e Instagram para ZAR')
  self.assertEqual(len(rows),2);self.assertEqual(rows[0]['identity'],self.address)
  center.natural_request(self.scope,'Necesito TikTok e Instagram para ZAR');state=center.view(self.scope)
  self.assertEqual(len(state['plans']),2);self.assertEqual(len(state['human_actions']),3)
  graph=orchestration_map.graph({'agents':[],'edges':[]},holdings.read(self.scope));self.assertIn(['IDENTITY','Identity:GOOGLE'],graph['edges'])
  self.assertIn(['Identity:TIKTOK','AccountProvisioningAgent:TIKTOK'],graph['edges'])
 def test_unknown_provider_no_fictional_signup(self):
  with self.assertRaises(ValueError):center.provider_plan(self.scope,'invented')
  with self.assertRaises(ValueError):center.provider_plan(self.scope,'GOOGLE')
 def test_continue_not_fake_active(self):
  p=center.provider_plan(self.scope,'STRIPE');action=next(a for a in center.view(self.scope)['human_actions'] if a['plan_id']==p['id'])
  with patch('app.business_workflows.operate',return_value={'state':'POR CONFIGURAR'}):result=center.operate(self.scope,'continue',{'id':action['id']})
  self.assertEqual(result['status'],'ACTION_REQUIRED');self.assertEqual(center.view(self.scope)['plans'][0]['status'],'API_CONFIG')
 def test_continue_verified_provider_resumes(self):
  p=center.provider_plan(self.scope,'SHOPIFY');action=next(a for a in center.view(self.scope)['human_actions'] if a['plan_id']==p['id'])
  def verified(*a):
   from app.business_connectors import verification
   d=holdings.read(self.scope);d.setdefault('verified_connectors',{})['Shopify']=verification('Shopify','LISTO','offline shop verified');holdings.write(self.scope,d)
  with patch('app.business_workflows.operate',side_effect=verified):result=center.operate(self.scope,'continue',{'id':action['id']})
  self.assertEqual(result['status'],'DONE');self.assertEqual(center.view(self.scope)['plans'][0]['status'],'ACTIVE')
 def test_password_fields_rejected(self):
  with self.assertRaises(ValueError):center.operate(self.scope,'register',{'email':self.address,'password':'never-store'})
  self.assertNotIn('never-store',json.dumps(holdings.read(self.scope)))
 def test_core_oauth_scopes_and_pkce(self):
  with patch.object(cloud_auth,'_oauth_client',return_value=('offline-id','offline-secret')):
   url,state,verifier=cloud_auth.authorization_url(True,'https://zar.invalid/oauth2callback','core',self.address)
  params=parse_qs(urlparse(url).query);scopes=params['scope'][0].split()
  self.assertIn(center.PREFIX+'gmail.modify',scopes);self.assertNotIn(center.PREFIX+'adsense.readonly',scopes)
  self.assertNotIn(center.PREFIX+'youtube.upload',scopes);self.assertEqual(params['login_hint'],[self.address]);self.assertTrue(state and verifier)
 def test_oauth_wrong_account_never_saved(self):
  response=Mock(ok=True,json=lambda:{'access_token':'offline','refresh_token':'offline-refresh','scope':'openid email'})
  with patch.object(cloud_auth,'_oauth_client',return_value=('offline-id','offline-secret')),patch.object(cloud_auth.requests,'post',return_value=response),patch.object(cloud_auth,'get_account_email',return_value='wrong@gmail.com'),patch.object(cloud_auth,'_save_credentials') as save:
   with self.assertRaises(ValueError):cloud_auth.finish_oauth('state','code','verifier','https://zar.invalid/oauth2callback',self.scope,self.address)
   save.assert_not_called()
 def test_oauth_preserves_real_scopes(self):
  from google.oauth2.credentials import Credentials
  creds=Credentials(token='offline',refresh_token='offline-r',client_id='offline-id',client_secret='offline-secret',token_uri='https://oauth2.googleapis.com/token',scopes=[center.PREFIX+'drive.file'])
  with patch.object(cloud_auth,'DATA_DIR',self.tmp):
   cloud_auth._save_credentials(creds,self.scope);loaded=cloud_auth.get_credentials(False,self.scope)
   self.assertEqual(loaded.scopes,[center.PREFIX+'drive.file']);self.assertNotIn('offline-r',cloud_auth._token_file(self.scope).read_text())
 def test_revoke_requires_confirmation(self):
  with self.assertRaises(ValueError):center.operate(self.scope,'revoke',{})
 def test_mail_confirmation_dedup_audit(self):
  data={'to':'recipient@example.test','subject':'Offline','body':'Test','transaction_id':uuid.uuid4().hex,'confirmed':True,'client':'client','business':'agency','agent':'Pablo'}
  with patch.object(mail,'require_mail'),patch.object(mail.gmail,'gmail_status',return_value={'email':self.address}),patch.object(mail.gmail,'send_with_attachments',return_value={'id':'mock-message','threadId':'mock-thread'}) as send:
   first=mail.operate(self.scope,'send',data);self.assertEqual(mail.operate(self.scope,'send',data),first);self.assertEqual(send.call_count,1)
   with self.assertRaises(ValueError):mail.operate(self.scope,'send',{**data,'to':'other@example.test'})
  self.assertEqual(first['message_id'],'mock-message');self.assertEqual(first['business'],'agency');self.assertNotIn('body',first)
 def test_ambiguous_mail_not_repeated(self):
  data={'to':'recipient@example.test','subject':'Offline','body':'Test','transaction_id':uuid.uuid4().hex,'confirmed':True}
  with patch.object(mail,'require_mail'),patch.object(mail.gmail,'gmail_status',return_value={'email':self.address}),patch.object(mail.gmail,'send_with_attachments',side_effect=TimeoutError) as send:
   with self.assertRaises(ValueError):mail.operate(self.scope,'send',data)
   self.assertEqual(mail.operate(self.scope,'send',data)['status'],'REVIEW_REQUIRED');self.assertEqual(send.call_count,1)
 def test_mail_wrong_principal_blocked(self):
  with patch('app.gmail.gmail_status',return_value={'email':'personal@gmail.com'}):
   with self.assertRaises(ValueError):center.require_mail(self.scope)

 def test_workspace_writes_require_confirmation(self):
  from app import identity_workspace as workspace
  with patch.object(cloud_auth,'get_credentials',return_value=Mock()),patch.object(cloud_auth,'get_account_email',return_value=self.address),patch.object(workspace.workspace,'docs_create',return_value={'documentId':'offline-doc'}) as create:
   with self.assertRaises(ValueError):workspace.operate(self.scope,'docs_create',{'name':'Offline'})
   self.assertEqual(workspace.operate(self.scope,'docs_create',{'name':'Offline','confirmed':True})['documentId'],'offline-doc')
   create.assert_called_once()
 def test_youtube_uses_scoped_zar_credentials(self):
  from app import youtube_auth
  creds=SimpleNamespace(scopes=[youtube_auth.YOUTUBE_SCOPE],token='offline')
  with patch('app.user_scope.get_current_user',return_value=self.scope),patch.object(cloud_auth,'get_credentials',return_value=creds):
   self.assertIs(youtube_auth.get_credentials(),creds)
  with patch('app.user_scope.get_current_user',return_value=self.scope),patch.object(cloud_auth,'get_credentials',return_value=None):
   self.assertIsNone(youtube_auth.get_credentials())
 def test_adsense_uses_oauth_without_plaintext_env_token(self):
  from app.adsense_adapter import AdSenseAdapter
  creds=SimpleNamespace(scopes=[center.PREFIX+'adsense.readonly'],token='offline-adsense-token')
  session=Mock();session.get.return_value=Mock(ok=True,json=lambda:{'accounts':[]})
  with patch.object(cloud_auth,'get_credentials',return_value=creds):self.assertEqual(AdSenseAdapter(session).accounts(),[])
  self.assertEqual(session.get.call_args.kwargs['headers']['Authorization'],'Bearer offline-adsense-token')
 def test_provisioning_agent_executes_real_local_plan(self):
  business.mutate(self.scope,'mode',{'mode':'SUPERVISED'})
  business.mutate(self.scope,'task',{'agent':'AccountProvisioningAgent','tool':'provisioning_request','payload':{'request':'Necesito Shopify para ZAR'},'request_id':'offline-plan'})
  with patch('app.jev_decision.proposal',return_value={'id':'offline-gate','decision':'APPROVE'}):business.tick(self.scope)
  state=holdings.read(self.scope);self.assertEqual(state['orchestration']['tasks'][0]['state'],'DONE')
  self.assertEqual(state['identity_center']['plans'][0]['service'],'SHOPIFY')
 def test_selected_identity_plans_survive_oauth_login_scope(self):
  business.mutate(self.scope,'deposit',{'amount':'50','currency':'USD','reference':'offline-local-wallet'})
  center.provider_plan(self.scope,'SHOPIFY')
  center.link_identity(self.scope,'new-google-login','different@gmail.com')
  self.assertEqual(center.view('new-google-login')['plans'],[])
  center.link_identity(self.scope,'new-google-login',self.address)
  center.link_identity(self.scope,'new-google-login',self.address)
  self.assertEqual(len(center.view('new-google-login')['plans']),1)
  self.assertEqual(holdings.read('new-google-login')['ledger'],[])

if __name__=='__main__':unittest.main()
