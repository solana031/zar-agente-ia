import os
import tempfile
import unittest
from unittest.mock import patch, MagicMock
from app import sites_domains, sites_native, site_projects


class DomainTests(unittest.TestCase):
    def test_format_and_private_destinations(self):
        self.assertEqual(sites_domains.normalize('Example.COM.'),'example.com')
        for value in ('https://example.com','example.com/path','localhost','127.0.0.1','x.local','a..com'):
            with self.assertRaises(ValueError): sites_domains.normalize(value)

    def test_save_keeps_published_url_and_tls_alone_is_not_active(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ,{'ZAR_DATA_DIR':tmp},clear=True):
            p=sites_native.build_demo('owner',{},'https://site.example')['project']
            sites_native.publish('owner',p['id'],True)
            result=sites_domains.save('owner',{'id':p['id'],'domain':'owned-domain.com'})
            self.assertEqual(result['status'],'DOMAIN_ENTERED')
            self.assertEqual(result['public_url'],p['canonical'])
            with self.assertRaises(StopIteration): sites_domains.save('other',{'id':p['id'],'domain':'owned-domain.com'})
            client=MagicMock(); response=client.__enter__.return_value.get.return_value.__enter__.return_value
            response.status_code=200;response.iter_content.return_value=[b'<html>Unrelated website</html>']
            proxy=MagicMock();proxy.server_address=('127.0.0.1',12345)
            with patch('app.browser_network.public_addresses',return_value=['93.184.216.34']), patch('app.browser_network.start_proxy',return_value=proxy),patch('app.sites_domains.requests.Session',return_value=client):
                result=sites_domains.verify('owner',{'id':p['id']})
            self.assertEqual(result['status'],'DNS_REQUIRED')
            self.assertEqual(result['https'],'VERIFIED')
            self.assertEqual(site_projects.get('owner',p['id'])['canonical'],p['canonical'])
            from app import sites_company
            root=sites_company._public_root()/p['slug']
            expected=(root/'index.html').read_text(encoding='utf-8').replace(p['canonical'],'https://owned-domain.com/')
            def probe(confirmed):
                response.iter_content.return_value=[expected.encode()]
                with patch('app.browser_network.public_addresses',return_value=['93.184.216.34']),patch('app.browser_network.start_proxy',return_value=proxy),patch('app.sites_domains.requests.Session',return_value=client):
                    return sites_domains.verify('owner',{'id':p['id'],'confirmed':confirmed})
            self.assertEqual(probe(False)['status'],'DNS_REQUIRED')
            self.assertEqual(site_projects.get('owner',p['id'])['canonical'],p['canonical'])
            self.assertEqual(probe(True)['status'],'ACTIVE')
            self.assertEqual(site_projects.get('owner',p['id'])['canonical'],'https://owned-domain.com/')
            self.assertIn('https://owned-domain.com/',(root/'sitemap.xml').read_text())

    def test_editorial_plan_validates_and_stays_private(self):
        from app import sites_editorial
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ,{'ZAR_DATA_DIR':tmp},clear=True):
            p=sites_native.build_demo('owner',{},'https://site.example')['project']
            data={'id':p['id'],'title':'Guía','body':'Texto revisado','editorial_stage':'READY','intent':'INFORMATIONAL','publish_date':'2026-11-01','internal_links':'about.html'}
            result=sites_editorial.operate('owner','save',data)
            self.assertEqual(result['plan'][0]['status'],'READY')
            self.assertEqual(result['articles'][0]['state'],'DRAFT')
            for changes in ({'publish_date':'not-a-date'},{'editorial_stage':'PUBLISHED'},{'internal_links':'https://evil.example/' }):
                with self.assertRaises(ValueError):sites_editorial.operate('owner','save',{**data,**changes})
