import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree
from app import sites_native, site_projects

class NativeSitesTests(unittest.TestCase):
    def test_agency_pdf_preserves_scope_and_estimate(self):
        from app import agency_crm, business_workflows, user_scope
        with tempfile.TemporaryDirectory(prefix='zar-sites-') as tmp, patch.dict(os.environ,{'ZAR_DATA_DIR':tmp},clear=True):
            lead=agency_crm.operate('owner','lead',{'name':'TEST INTERNAL','sector':'Diseño'})
            agency_crm.operate('owner','pricing',{'lead_id':lead['id'],'cost':100,'minimum':200,'target':300,'premium':400,'scope':'Demo interna, sin envío'})
            token=user_scope.set_current_user('owner')
            try:
                with patch('app.artifact_engine.create',return_value={'artifact_id':'test'}) as create:
                    self.assertEqual(business_workflows.operate('owner','agency_proposal_pdf',{'lead_id':lead['id']})['artifact_id'],'test')
                    self.assertIn('no oferta aceptada',create.call_args.args[1])
                    self.assertEqual(create.call_args.kwargs['contacts'],[lead['id']])
                    with self.assertRaises(ValueError): business_workflows.operate('other','agency_proposal_pdf',{'lead_id':lead['id']})
            finally: user_scope.reset_current_user(token)
    def test_agency_handoff_keeps_source_and_is_private(self):
        from app import agency_crm, business_workflows
        with tempfile.TemporaryDirectory(prefix='zar-sites-') as tmp, patch.dict(os.environ,{'ZAR_DATA_DIR':tmp},clear=True):
            lead=agency_crm.operate('owner','lead',{'name':'TEST INTERNAL · ficticio','sector':'Diseño','services':'Demo interna sin cliente'})
            demo=agency_crm.operate('owner','demo',{'lead_id':lead['id'],'price':490})
            result=business_workflows.operate('owner','agency_site_handoff',{'lead_id':lead['id']})
            self.assertEqual(result['agency_source_lead_id'],lead['id'])
            self.assertEqual(result['source_kind'],'UPLOAD')
            self.assertFalse(sites_native.public_request(result['slug']))
            self.assertTrue((Path(tmp)/'holdings_public_demos'/demo['slug']/'index.html').exists())
            with self.assertRaises(StopIteration): business_workflows.operate('other','agency_site_handoff',{'lead_id':lead['id']})
    def test_build_publish_readiness_and_isolation(self):
        with tempfile.TemporaryDirectory(prefix='zar-sites-') as tmp, patch.dict(os.environ,{'ZAR_DATA_DIR':tmp,'ADSENSE_PUBLISHER_ID':''},clear=True):
            result=sites_native.build_demo('owner',{'name':'Productividad <demo>'},'https://zar.example')
            row=result['project'];root=Path(tmp)/'holdings_public_sites'/row['slug']
            self.assertEqual(row['state'],'PREVIEW');self.assertEqual(len(list(root.glob('*.html'))),7)
            self.assertFalse(sites_native.public_request(row['slug']))
            self.assertIn('noindex,nofollow',(root/'index.html').read_text(encoding='utf-8'))
            sitemap=ElementTree.parse(root/'sitemap.xml');self.assertEqual(len(sitemap.getroot()),7)
            self.assertEqual(site_projects.analyze('owner',row['id'])['score'],100)
            self.assertFalse(result['readiness']['checks']['privacy_reviewed']);self.assertFalse((root/'ads.txt').exists())
            with self.assertRaises(StopIteration): site_projects.get('other',row['id'])
            with self.assertRaises(ValueError): sites_native.publish('owner',row['id'])
            published=sites_native.publish('owner',row['id'],True)
            self.assertEqual(published['state'],'PUBLISHED');self.assertIn('index,follow',(root/'index.html').read_text(encoding='utf-8'))
            self.assertTrue(sites_native.public_request(row['slug']))
            self.assertTrue(sites_native.public_request(row['slug'],'sitemap.xml'))
            self.assertFalse(sites_native.public_request(row['slug'],'published.json'))
            self.assertFalse(sites_native.public_request('../'+row['slug']))
            self.assertFalse(sites_native.public_request(row['slug'],'../registry.json'))
            self.assertFalse(sites_native.readiness('owner',row['id'])['approval_guaranteed'])
            self.assertIn('privacy_reviewed',sites_native.readiness('owner',row['id'])['blockers'])
    def test_separate_builds_keep_originals(self):
        with tempfile.TemporaryDirectory(prefix='zar-sites-') as tmp, patch.dict(os.environ,{'ZAR_DATA_DIR':tmp},clear=True):
            a=sites_native.build_demo('owner',{},'https://zar.example')['project']
            b=sites_native.build_demo('owner',{},'https://zar.example')['project']
            self.assertNotEqual(a['id'],b['id']);self.assertEqual(site_projects.get('owner',a['id'])['state'],'PREVIEW')

if __name__=='__main__': unittest.main()
