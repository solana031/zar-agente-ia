import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from app import sites_native, sites_editorial


class EditorialTests(unittest.TestCase):
    def test_private_draft_publish_edit_unpublish_and_scope(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'ZAR_DATA_DIR':tmp}, clear=True):
            p=sites_native.build_demo('owner',{},'https://site.example')['project']
            sites_native.publish('owner',p['id'],True)
            result=sites_editorial.operate('owner','save',{'id':p['id'],'title':'Guía <nueva>', 'body':'Texto original\n<script>alert(1)</script>'})
            a=result['articles'][0];root=Path(tmp)/'holdings_public_sites'/p['slug']
            self.assertEqual(result['saved_article_id'], a['id'])
            again=sites_editorial.operate('owner','save',{'id':p['id'],'article_id':result['saved_article_id'],'title':'Guía <nueva>', 'body':'Texto original\n<script>alert(1)</script>'})
            self.assertEqual(len(again['articles']), 1)
            self.assertFalse(sites_native.public_request(p['slug'],'draft-'+a['id']+'.html'))
            self.assertIn('&lt;script&gt;', (root/('draft-'+a['id']+'.html')).read_text(encoding='utf-8'))
            with self.assertRaises(StopIteration):sites_editorial.view('other',p['id'])
            with self.assertRaises(ValueError):sites_editorial.operate('owner','publish',{'id':p['id'],'article_id':a['id']})
            sites_editorial.operate('owner','publish',{'id':p['id'],'article_id':a['id'],'confirmed':True})
            file='article-'+a['id']+'.html';self.assertTrue(sites_native.public_request(p['slug'],file))
            content=(root/file).read_text(encoding='utf-8')
            sites_editorial.operate('owner','save',{'id':p['id'],'article_id':a['id'],'title':'Borrador distinto','body':'Edición privada'})
            self.assertEqual(content,(root/file).read_text(encoding='utf-8'))
            sites_editorial.operate('owner','unpublish',{'id':p['id'],'article_id':a['id'],'confirmed':True})
            self.assertFalse(sites_native.public_request(p['slug'],file));self.assertFalse((root/file).exists())
            self.assertTrue((root/('draft-'+a['id']+'.html')).exists())
            self.assertNotIn(file,(root/'sitemap.xml').read_text())
            self.assertTrue((root/'ordenar-archivos.html').exists())

    def test_test_content_never_public_and_paths_rejected(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'ZAR_DATA_DIR':tmp}, clear=True):
            p=sites_native.build_demo('owner',{},'https://site.example')['project'];sites_native.publish('owner',p['id'],True)
            a=sites_editorial.operate('owner','save',{'id':p['id'],'title':'TEST','body':'Privado','is_test':True})['articles'][0]
            with self.assertRaises(ValueError): sites_editorial.operate('owner','publish',{'id':p['id'],'article_id':a['id'],'confirmed':True})
            with self.assertRaises(ValueError): sites_editorial.operate('owner','save',{'id':p['id'],'article_id':'../../x','title':'x','body':'x'})
            self.assertFalse(sites_native.readiness('owner',p['id'])['checks']['adsense_domain'])

    def test_wise_optional_keeps_evidence(self):
        from app.identity_center import human_action_groups
        row={'id':'a','service':'FINANCIAL_PROVIDER','action':'OBSERVED_BLOCKER','status':'ACTION_REQUIRED','reason':'Wise Advanced 60 EUR', 'instructions':['No contratar']}
        result=human_action_groups({'human_actions':[row]})[0]
        self.assertEqual(result['requirement'],'OPTIONAL');self.assertEqual(result['related_ids'],['a'])
        self.assertEqual(row['status'],'ACTION_REQUIRED')
