import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree
from app import sites_native, site_projects

class NativeSitesTests(unittest.TestCase):
    def test_build_publish_readiness_and_isolation(self):
        with tempfile.TemporaryDirectory(prefix='zar-sites-') as tmp, patch.dict(os.environ,{'ZAR_DATA_DIR':tmp,'ADSENSE_PUBLISHER_ID':''},clear=True):
            result=sites_native.build_demo('owner',{'name':'Productividad <demo>'},'https://zar.example')
            row=result['project'];root=Path(tmp)/'holdings_public_sites'/row['slug']
            self.assertEqual(row['state'],'PREVIEW');self.assertEqual(len(list(root.glob('*.html'))),7)
            self.assertIn('noindex,nofollow',(root/'index.html').read_text(encoding='utf-8'))
            sitemap=ElementTree.parse(root/'sitemap.xml');self.assertEqual(len(sitemap.getroot()),7)
            self.assertEqual(site_projects.analyze('owner',row['id'])['score'],100)
            self.assertFalse(result['readiness']['checks']['privacy_reviewed']);self.assertFalse((root/'ads.txt').exists())
            with self.assertRaises(StopIteration): site_projects.get('other',row['id'])
            with self.assertRaises(ValueError): sites_native.publish('owner',row['id'])
            published=sites_native.publish('owner',row['id'],True)
            self.assertEqual(published['state'],'PUBLISHED');self.assertIn('index,follow',(root/'index.html').read_text(encoding='utf-8'))
            self.assertFalse(sites_native.readiness('owner',row['id'])['approval_guaranteed'])
            self.assertIn('privacy_reviewed',sites_native.readiness('owner',row['id'])['blockers'])
    def test_separate_builds_keep_originals(self):
        with tempfile.TemporaryDirectory(prefix='zar-sites-') as tmp, patch.dict(os.environ,{'ZAR_DATA_DIR':tmp},clear=True):
            a=sites_native.build_demo('owner',{},'https://zar.example')['project']
            b=sites_native.build_demo('owner',{},'https://zar.example')['project']
            self.assertNotEqual(a['id'],b['id']);self.assertEqual(site_projects.get('owner',a['id'])['state'],'PREVIEW')

if __name__=='__main__': unittest.main()
