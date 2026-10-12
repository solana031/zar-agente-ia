import json,os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from flask import Flask
from app import reposnews as rn
class ReposNewsTest(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.env=patch.dict(os.environ,{'ZAR_DATA_DIR':self.tmp.name});self.env.start()
  self.rows=json.loads(Path('app/reposnews_content.json').read_text(encoding='utf-8'));rn.write({'owner':'owner','articles':self.rows,'domain_status':'ACTIVE','publisher':'pub-4119869448727531'})
  self.app=Flask(__name__,template_folder=str(Path('app/templates').resolve()));self.app.before_request(rn.public_dispatch);rn.register(self.app,lambda:'owner');self.c=self.app.test_client()
 def tearDown(self): self.env.stop();self.tmp.cleanup()
 def get(self,path):return self.c.get(path,base_url=rn.ORIGIN)
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
if __name__=='__main__':unittest.main()
