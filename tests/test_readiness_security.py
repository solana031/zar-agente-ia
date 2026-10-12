"""Offline RC regression tests. No accounts, publications or payments are touched."""
import ast
import copy
import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from flask import Flask, jsonify, request, send_file
from app import holdings, identity_center, jev_decision, sites_company, sites_native, web_agency
from app.site_projects import preview_headers


class ReadinessSecurityTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='zar-rc-test-')
        self.addCleanup(self.tmp.cleanup)
        self.env=patch.dict(os.environ,{'ZAR_DATA_DIR':self.tmp.name},clear=True)
        self.env.start();self.addCleanup(self.env.stop)

    def client(self,scope='TEST-owner'):
        app=Flask('readiness-security');app.secret_key='TEST-only'
        names={'holdings_sites_deploy_api','holdings_site_page','holdings_site_asset','holdings_demo_page'}
        tree=ast.parse(Path('app/main.py').read_text(encoding='utf-8-sig'))
        ns=dict(__name__='app.main',__package__='app',app=app,os=os,re=re,Path=Path,
                jsonify=jsonify,request=request,send_file=send_file,sites_company=sites_company,
                web_agency=web_agency,site_projects_preview=preview_headers,_user_scope_id=lambda:scope)
        exec(compile(ast.Module(body=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in names],type_ignores=[]),'app/main.py','exec'),ns)
        return app.test_client()

    def test_policy_required_decisions(self):
        for action,expected in [('RESEARCH','ALLOW'),('REPORT','ALLOW'),('SEND_EMAIL','CONFIRM'),('MEDIA_PUBLISH','CONFIRM'),('SITE_PUBLISH','CONFIRM'),('CALENDAR_CREATE','CONFIRM'),('PAYMENT','CONFIRM'),('TRADING_LIVE','DENY')]:
            self.assertEqual(jev_decision.evaluate('TEST-owner',{'action':action})['decision'],expected)

    def test_deploy_needs_literal_confirmation_before_network(self):
        client=self.client()
        with patch.object(sites_company.requests,'post') as post:
            for confirmed in (None,False,'true','false',1):
                self.assertEqual(client.post('/api/holdings/sites/deploy',json={'slug':'TEST','confirmed':confirmed}).status_code,409)
                with self.assertRaises(ValueError):sites_company.deploy_vercel('TEST-owner','TEST',confirmed=confirmed)
            post.assert_not_called()

    def test_stop_blocks_confirmed_deploy(self):
        state=holdings.read('TEST-owner');state['global_stop']=True;holdings.write('TEST-owner',state)
        with patch.object(sites_company.requests,'post') as post:
            with self.assertRaises(ValueError):sites_company.deploy_vercel('TEST-owner','TEST',confirmed=True)
            post.assert_not_called()

    def test_private_previews_are_scoped_and_published_site_remains_public(self):
        row=sites_native.build_demo('TEST-owner',{'name':'TEST internal'},'https://test.invalid')['project']
        url='/holdings/site/'+row['slug']+'/'
        own=self.client();other=self.client('TEST-other')
        self.assertEqual(own.get(url).status_code,200)
        self.assertIn('sandbox',own.get(url).headers['Content-Security-Policy'])
        self.assertEqual(other.get(url).status_code,404)
        self.assertEqual(other.get(url+'sitemap.xml').status_code,404)
        sites_native.publish('TEST-owner',row['id'],confirmed=True)
        self.assertEqual(other.get(url).status_code,200)
        self.assertEqual(other.get(url+'sitemap.xml').status_code,200)
        self.assertEqual(other.get(url+'published.json').status_code,404)

    def test_agency_demo_owner_and_legacy_provenance(self):
        row=web_agency.build_demo('TEST-owner',{'name':'TEST demo'},100)
        self.assertEqual(self.client().get(row['relative_url']).status_code,200)
        self.assertEqual(self.client('TEST-other').get(row['relative_url']).status_code,404)
        marker=Path(self.tmp.name)/'holdings_public_demos'/row['slug']/'owner.json'
        marker.unlink()  # Only this disposable TEST fixture.
        state=holdings.read('TEST-owner');state['agency_crm']={'leads':[{'demo':row}]};holdings.write('TEST-owner',state)
        self.assertTrue(web_agency.owns_demo('TEST-owner',row['slug']))
        self.assertFalse(web_agency.owns_demo('TEST-other',row['slug']))

    def test_human_actions_group_without_deleting_evidence_or_other_accounts(self):
        state={'google':{'email':'TEST@example.invalid'},'human_actions':[]}
        identity_center.queue(state,'SHOPIFY','SETUP','Configuration missing',None,['Configure'])
        observed=identity_center.queue(state,'SHOPIFY','OBSERVED_BLOCKER','Wrong account',None,['Sign in to correct account'])
        other=identity_center.queue(state,'SHOPIFY','OTHER','Other account',None,['Verify']);other['account']='other@example.invalid'
        before=copy.deepcopy(state)
        rows=identity_center.human_action_groups(state)
        self.assertEqual(len(rows),2);self.assertEqual(rows[0]['id'],observed['id'])
        self.assertEqual(len(rows[0]['related_ids']),2);self.assertEqual(state,before)
        self.assertEqual(rows[0]['exact_step'],'Sign in to correct account')

    def test_relay_continue_checks_billing_and_preserves_missing_money_blocker(self):
        with holdings.transaction('TEST-owner'):
            state=holdings.read('TEST-owner');identity=identity_center.ensure(state)
            row=identity_center.queue(identity,'RELAYCLAW','OBSERVED_BLOCKER','Old config error',None,['Configure key'])
            holdings.write('TEST-owner',state)
        result={'billing_sync':{'RelayClaw':{'status':'ACTION_REQUIRED','rows_without_money':3,'reason':'No monetary receipts'}}}
        with patch('app.business_orchestration.mutate',return_value=result) as mutate:
            action=identity_center.operate('TEST-owner','continue',{'id':row['id']})
            mutate.assert_called_once_with('TEST-owner','relayclaw_sync',{})
        self.assertEqual(action['status'],'ACTION_REQUIRED');self.assertEqual(action['reason'],'No monetary receipts')
        self.assertNotIn('Configure key',action['instructions'])


if __name__=='__main__':unittest.main()
