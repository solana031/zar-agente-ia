"""Focused release checks; mocks only, workers disabled, zero provider writes."""
import os,shutil,uuid,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
root=Path(__file__).resolve().parents[1];temp=root/('zar-337-'+uuid.uuid4().hex);temp.mkdir()
environment=patch.dict(os.environ,{'ZAR_DATA_DIR':str(temp)},clear=True);environment.start()
with patch('threading.Thread.start'):
 from app import main,identity_center as center,cloud_auth,holdings,adsense_adapter
 from app.media_adapters import PublishingAdapter

class Release337(unittest.TestCase):
 def setUp(self):
  self.scope=uuid.uuid4().hex;self.address='zar.offline@gmail.com';center.register_google(self.scope,self.address)
 def test_channel_missing_present(self):
  creds=SimpleNamespace(token='offline',scopes=[center.PREFIX+'youtube.readonly',center.PREFIX+'youtube.upload'])
  for rows,connected in [([],False),([{'id':'fixture-channel','snippet':{'title':'ZAR Agente IA','customUrl':'@fixture'}}],True)]:
   with patch.object(center.requests,'get',return_value=Mock(ok=True,json=lambda:{'items':rows})):
    r=center._probe('YOUTUBE',creds)
   self.assertEqual(r['upload_capability'],connected)
   if connected:self.assertEqual(r['channels'][0]['handle'],'@fixture')
   else:self.assertEqual(r['channel_ids'],[])
 def test_publishing_validation_never_uploads(self):
  for ready in (False,True):
   cap={'status':'CONNECTED' if ready else 'NOT_ELIGIBLE','upload_capability':ready,'channels':[{'id':'fixture'}] if ready else []}
   with patch.object(center,'verify_google',return_value={'capabilities':{'YOUTUBE':cap}}),patch('app.youtube.upload',side_effect=AssertionError('No upload in validation')):
    r=PublishingAdapter().prepare_youtube(self.scope,'Title',privacy='private',thumbnail='fixture.jpg',subtitle_track='fixture.srt')
   self.assertEqual(r['status'],'READY_FOR_REVIEW' if ready else 'HUMAN_ACTION_REQUIRED');self.assertTrue(r['dry_run']);self.assertEqual(r['publish_status'],'NOT_UPLOADED')
 def test_adsense_no_account_no_reports(self):
  with patch.object(adsense_adapter.AdSenseAdapter,'accounts',return_value=[]),patch.object(adsense_adapter.AdSenseAdapter,'get',side_effect=AssertionError('No reports without account')):
   r=adsense_adapter.AdSenseAdapter().snapshot()
  self.assertEqual(r['account_state'],'NO_ACCOUNT');self.assertEqual(r['state'],'SIGNUP_REQUIRED');self.assertIsNone(r['metrics'])
 def test_adsense_state_and_resume(self):
  creds=SimpleNamespace(token='offline',scopes=[center.PREFIX+'adsense.readonly'])
  for source,target in [('READY','ACTIVE'),('GETTING_READY','PENDING_APPROVAL'),('REJECTED','REJECTED')]:
   with patch.object(center.requests,'get',return_value=Mock(ok=True,json=lambda:{'accounts':[{'name':'accounts/fixture','state':source}]})):
    self.assertEqual(center._probe('ADSENSE',creds)['account_state'],target)
  plan=center.provider_plan(self.scope,'ADSENSE');a=next(a for a in center.view(self.scope)['human_actions'] if a.get('plan_id')==plan['id'])
  with patch.object(center,'verify_google',return_value={'capabilities':{'ADSENSE':{'status':'CONNECTED','account_state':'PENDING_APPROVAL'}}}),patch('app.business_connectors.inventory',return_value=[{'name':'AdSense','state':'LISTO'}]):
   self.assertNotEqual(center.operate(self.scope,'continue',{'id':a['id']})['status'],'DONE')
  with patch.object(center,'verify_google',return_value={'capabilities':{'ADSENSE':{'status':'CONNECTED','account_state':'ACTIVE'}}}),patch('app.business_connectors.inventory',return_value=[{'name':'AdSense','state':'LISTO'}]):
   self.assertEqual(center.operate(self.scope,'continue',{'id':a['id']})['status'],'DONE')
 def test_queue_and_server_configuration(self):
  for service in ('YOUTUBE','ADSENSE','SHOPIFY','STRIPE'):center.provider_plan(self.scope,service)
  s=center.view(self.scope)
  for service in ('YOUTUBE','ADSENSE','SHOPIFY','STRIPE'):
   a=next(a for a in s['human_actions'] if a['service']==service)
   for field in ('service','title','reason','url','instructions','status'):self.assertTrue(a[field])
  yt=next(a for a in s['human_actions'] if a['service']=='YOUTUBE');self.assertEqual(yt['suggested_name'],'ZAR Agente IA');self.assertEqual(yt['suggested_handle'],'@zaragente031')
  self.assertIn('STRIPE_WEBHOOK_SECRET',str(next(a for a in s['human_actions'] if a['service']=='STRIPE')['instructions']))
 def test_paper_reset_guards_and_audit(self):
  main.app.config.update(TESTING=True,SECRET_KEY='offline');c=main.app.test_client();route='/api/stonks/automaton/reset-paper'
  with c.session_transaction() as s:s['business_csrf']='fixture-csrf'
  headers={'X-ZAR-Business-CSRF':'fixture-csrf'};data={'confirmed':True,'mode':'PAPER'}
  self.assertEqual(c.post(route,json=data).status_code,403)
  self.assertEqual(c.post(route,json={},headers=headers).status_code,400)
  for mode,ready,code in [('live',True,409),('paper',False,409),('paper',True,200)]:
   d=main._stonks_default();d.update(mode=mode,revoked=True)
   with patch.object(main,'_stonks_read',return_value=d),patch.object(main,'_automaton_preflight',return_value={'ready_to_start':ready,'checks':{'risk_engine':ready}}),patch.object(main,'_stonks_write') as write,patch.object(main,'_stonks_audit_append') as audit:
    r=c.post(route,json=data,headers=headers);self.assertEqual(r.status_code,code)
    if code!=200:write.assert_not_called();self.assertTrue(d['revoked'])
    else:self.assertFalse(d['revoked']);self.assertTrue(d['paused']);self.assertFalse(d['autonomous_engine']);self.assertTrue(audit.call_args.args[1]['previous_revoked'])
 def test_version(self):
  self.assertEqual(main.app.test_client().get('/health').json['version'],'33.3.7')
  self.assertEqual({(root/p).read_text().strip() for p in ['VERSION','VERSION.txt','app/VERSION.txt']},{'33.3.7'})

try:
 result=unittest.TextTestRunner(verbosity=1).run(unittest.defaultTestLoader.loadTestsFromTestCase(Release337))
finally:
 environment.stop();assert temp.resolve().is_relative_to(root);shutil.rmtree(temp)
if not result.wasSuccessful():raise SystemExit(1)
