import json,os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from flask import Flask
from app import reposnews as rn
class ReposNewsTest(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.env=patch.dict(os.environ,{'ZAR_DATA_DIR':self.tmp.name});self.env.start()
  self.rows=[rn.article_defaults(a) for a in json.loads(Path('app/reposnews_content.json').read_text(encoding='utf-8'))];rn.write({'owner':'owner','articles':self.rows,'domain_status':'ACTIVE','publisher':'pub-4119869448727531'})
  self.app=Flask(__name__,template_folder=str(Path('app/templates').resolve()));self.app.before_request(rn.public_dispatch);rn.register(self.app,lambda:'owner');self.c=self.app.test_client()
 def tearDown(self): self.env.stop();self.tmp.cleanup()
 def get(self,path):return self.c.get(path,base_url=rn.ORIGIN)
 def test_public_economic_profile_never_exposes_private_identity(self):
  data=rn.read();data['legal']={'controller':'Approved owner','address':'PRIVATE STREET 999','tax_id':'12345678Z','registration':'PRIVATE REGISTER','privacy_contact':'private@example.test','activity_mode':'ECONOMIC','entity_type':'PERSON','processing_basis':'Approved basis 12345678Z','retention':'Approved retention PRIVATE STREET 999','providers_reviewed':True};data['legal_reviewed']=True
  for a in data['articles']:a['published']=True
  rn.write(data)
  self.assertEqual(rn.legal_status(data)['status'],'LEGAL_READY')
  for lang in ('es','en'):
   for page in ('','legal/','privacy/','cookies/','contact/','about/','repositories/','guides/',('repositorios/' if lang=='es' else 'repositories/')+'uv/'):
    response=self.get('/'+lang+'/'+page);self.assertEqual(response.status_code,200)
    for private in ('PRIVATE STREET 999','12345678Z','PRIVATE REGISTER','private@example.test'):self.assertNotIn(private,response.get_data(as_text=True))
   preview=self.c.get('/reposnews-preview/'+lang+'/legal').get_data(as_text=True)
   self.assertNotIn('12345678Z',preview);self.assertNotIn('PRIVATE STREET 999',preview)
  self.assertEqual(rn.read()['legal'],data['legal'])
  profile=rn.public_legal_profile(data);self.assertEqual(profile['email'],'zaragente031@gmail.com');self.assertEqual(profile['controller'],'Approved owner');self.assertNotIn('tax_id',profile)
 def test_private_drafts(self):
  self.assertEqual(self.get('/es/repositorios/uv/').status_code,404)
  self.assertNotIn(b'uv:',self.get('/es/').data)
  self.assertEqual(self.get('/api/holdings/workflows').status_code,404)
  self.assertEqual(self.get('/login').status_code,404)
 def test_language(self):
  self.assertEqual(self.c.get('/',base_url=rn.ORIGIN,headers={'Accept-Language':'en-US,en;q=.8'}).location,'/en/')
  self.c.set_cookie('reposnews_lang','es',domain='www.reposnews.com');self.assertEqual(self.c.get('/',base_url=rn.ORIGIN,headers={'Accept-Language':'en'}).location,'/es/')
 def test_preview(self):
  r=self.c.get('/reposnews-preview/es/uv');self.assertEqual(r.status_code,200);self.assertIn('noindex',r.headers['X-Robots-Tag']);self.assertIn(b'pip install uv',r.data)
 def test_scope(self):
  with self.assertRaises(ValueError):rn.state('other')
 def test_confirmation(self):
  with self.assertRaises(ValueError):rn.operate('owner','publish',{'id':'uv'})
 def test_snapshot_isolation(self):
  data=rn.read();a=data['articles'][0];a['published_snapshot']=dict(a);a['published']=True;a['title_es']='SECRET NEW DRAFT';rn.write(data)
  r=self.get('/es/repositorios/uv/');self.assertEqual(r.status_code,200);self.assertNotIn(b'SECRET NEW DRAFT',r.data);self.assertIn(b'hreflang="en"',r.data)
 def test_seo(self):
  self.assertEqual(self.get('/ads.txt').status_code,200);self.assertNotIn(b'/uv/',self.get('/sitemap.xml').data)
  self.assertIn(b'https://www.reposnews.com/es/',self.get('/es/').data)
 def test_escape(self):self.assertNotIn('<script>',str(rn.body_html('<script>alert(1)</script>')))
 def test_bootstrap_reload(self):
  rn._path().unlink();scope=rn.bootstrap();first=rn.state(scope);ids=[a['id'] for a in first['articles']]
  import importlib
  importlib.reload(rn);rn.bootstrap();again=rn.state(scope)
  self.assertEqual(ids,[a['id'] for a in again['articles']]);self.assertEqual(len(ids),3)
  self.assertTrue(all(not a['published'] and a['status']=='READY' for a in again['articles']))
  for a in again['articles']:
   self.assertTrue(a['history']);self.assertTrue(a['seo']['en']['canonical']);self.assertTrue(a['latest_release']['url'])
  self.assertFalse(again['readiness']['checks']['PUBLIC_CONTENT']);self.assertEqual(again['readiness']['status'],'ACTION_REQUIRED')
 def test_history(self):
  data=rn.read();data['articles']=[rn.article_defaults(a) for a in data['articles']];rn.write(data)
  result=rn.operate('owner','save',{'id':'uv','title_es':'Titulo revisado','reason':'Corrección editorial','state':'REVIEW'})
  self.assertIn('title_es',result['articles'][0]['history'][-1]['fields']);self.assertFalse(result['articles'][0]['published'])
 def test_legal_draft_isolation(self):
  rn.operate('owner','legal_save',{'controller':'PRIVATE UNREVIEWED'})
  r=self.get('/es/legal/');self.assertEqual(r.status_code,200);self.assertNotIn(b'PRIVATE UNREVIEWED',r.data);self.assertIn(b'ACTION_REQUIRED',r.data)
 def test_breadcrumb_and_related(self):
  r=self.c.get('/reposnews-preview/en/playwright');self.assertEqual(r.status_code,200);self.assertIn(b'BreadcrumbList',r.data);self.assertIn(b'Related guides',r.data)
 def test_legal_applicability(self):
  l={'controller':'Fixture owner','privacy_contact':'fixture@example.test','activity_mode':'NONCOMMERCIAL','entity_type':'PERSON','processing_basis':'Test fixture basis','retention':'Fixture retention','providers_reviewed':True}
  data={'legal':l,'legal_reviewed':True};self.assertEqual(rn.legal_status(data)['status'],'LEGAL_READY');self.assertEqual(rn.legal_status(data)['fields']['tax_id']['level'],'NOT_APPLICABLE')
  l['activity_mode']='ECONOMIC';self.assertIn('tax_id',rn.legal_status(data)['missing_required']);self.assertIn('address',rn.legal_status(data)['missing_required'])
  l['entity_type']='REGISTERED_ENTITY';self.assertIn('registration',rn.legal_status(data)['missing_required'])
 def test_dry_run_no_write(self):
  before=rn._path().read_bytes();plan=rn.operate('owner','dry_run',{'ids':['uv','playwright','fastapi']})
  self.assertEqual(len(plan['urls']),6);self.assertEqual(plan['seo'],'PASS');self.assertFalse(plan['ready_to_publish']);self.assertEqual(before,rn._path().read_bytes())
 def test_batch_confirmation_and_stale_plan(self):
  data=rn.read();data.update(legal={'controller':'Fixture owner','privacy_contact':'fixture@example.test','activity_mode':'NONCOMMERCIAL','entity_type':'PERSON','processing_basis':'Fixture basis','retention':'Fixture retention','providers_reviewed':True},legal_reviewed=True);rn.write(data)
  plan=rn.publication_plan(data,['uv','playwright','fastapi']);self.assertTrue(plan['ready_to_publish'])
  with self.assertRaises(ValueError):rn.operate('owner','publish_batch',{'ids':plan['ids'],'approved_digest':plan['digest']})
  data['articles'][0]['title_es']='Changed title';rn.write(data)
  with self.assertRaises(ValueError):rn.operate('owner','publish_batch',{'ids':plan['ids'],'approved_digest':plan['digest'],'confirmed':True})
 def test_fixture_batch_publish_and_unpublish(self):
  data=rn.read();data.update(legal={'controller':'Fixture owner','privacy_contact':'fixture@example.test','activity_mode':'NONCOMMERCIAL','entity_type':'PERSON','processing_basis':'Fixture basis','retention':'Fixture retention','providers_reviewed':True},legal_reviewed=True);rn.write(data)
  plan=rn.publication_plan(data,['uv','playwright','fastapi'])
  with patch('app.holdings.read',return_value={'global_stop':False}),patch('app.jev_decision.proposal',return_value={'id':'fixture','decision':'ALLOW'}),patch('app.jev_decision.decision_state'):
   rn.operate('owner','publish_batch',{'ids':plan['ids'],'approved_digest':plan['digest'],'confirmed':True})
   xml=self.get('/sitemap.xml').data
   for u in plan['urls']:self.assertIn(u.encode(),xml)
   for id in plan['ids']:rn.operate('owner','unpublish',{'id':id,'confirmed':True})
  self.assertEqual(len(rn.read()['articles']),3);self.assertTrue(all(not a['published'] for a in rn.read()['articles']));self.assertNotIn(b'/uv/',self.get('/sitemap.xml').data)
 def test_private_optional_legal_fields(self):
  data=rn.read();data.update(legal={'controller':'Fixture owner','privacy_contact':'fixture@example.test','activity_mode':'NONCOMMERCIAL','entity_type':'PERSON','processing_basis':'Fixture basis','retention':'Fixture retention','providers_reviewed':True,'tax_id':'PRIVATE_TAX','address':'PRIVATE_ADDRESS'},legal_reviewed=True);rn.write(data)
  r=self.get('/es/legal/');self.assertNotIn(b'PRIVATE_TAX',r.data);self.assertNotIn(b'PRIVATE_ADDRESS',r.data)
 def test_partial_legal_is_saved_without_approval(self):
  result=rn.operate('owner','legal_save',{'controller':'Fixture draft owner','reviewed':True})
  self.assertEqual(result['legal']['controller'],'Fixture draft owner');self.assertFalse(result['legal_reviewed']);self.assertEqual(result['legal_status']['status'],'LEGAL_INCOMPLETE');self.assertIn('Guardado privado',result['legal_save_notice'])
 def test_complete_legal_survives_restart(self):
  import importlib
  legal={'controller':'Fixture owner','privacy_contact':'fixture@example.test','activity_mode':'ECONOMIC','entity_type':'PERSON','address':'Fixture address','tax_id':'TEST_ONLY','processing_basis':'Fixture basis','retention':'Fixture retention','providers_reviewed':True,'reviewed':True}
  rn.operate('owner','legal_save',legal)
  importlib.reload(rn);rn.initialize('owner')
  saved=rn.state('owner')
  for key,value in legal.items():
   if key!='reviewed':self.assertEqual(saved['legal'][key],value)
  self.assertEqual(saved['legal_status']['status'],'LEGAL_READY')
  self.assertIn('VERIFIED',saved['search_console_status'])
 def test_diagnostic_redacts_and_finds_copy(self):
  folder=rn._path().parent
  secret={'owner':'owner','legal':{'controller':'PRIVATE_FIXTURE','tax_id':'PRIVATE_TAX'}}
  (folder/'editorial.backup.json').write_text(json.dumps(secret))
  result=rn.legal_diagnostic('owner')
  self.assertTrue(any(c['fields']['controller'] for c in result['copies']))
  self.assertNotIn('PRIVATE_FIXTURE',json.dumps(result));self.assertNotIn('PRIVATE_TAX',json.dumps(result))
  with self.assertRaises(ValueError):rn.legal_diagnostic('another')
 def test_media_isolation(self):
  r=self.get('/media/reposnews/uv.png');self.assertEqual(r.status_code,200);self.assertEqual(r.mimetype,'image/png');r.close()
  self.assertEqual(self.get('/media/reposnews/../index.html').status_code,404)
  self.assertEqual(self.get('/media/reposnews/private.json').status_code,404)
 def test_social_visuals(self):
  r=self.c.get('/reposnews-preview/en/uv');self.assertIn(b'og:image',r.data);self.assertIn(b'summary_large_image',r.data);self.assertIn(b'/media/reposnews/uv.png',r.data)
if __name__=='__main__':unittest.main()
