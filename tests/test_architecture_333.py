"""Offline architecture, authenticated notifications and identity regression."""
import hashlib
import hmac
import json
import os
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from app import business_orchestration, agency_events, stonks_automaton

class ArchitectureTests(unittest.TestCase):
    def test_business_has_no_trading_tools(self):
        self.assertEqual(len(business_orchestration.ORCHESTRATORS),5)
        for domain,tool in business_orchestration.TOOLS.values():
            self.assertNotIn(domain,('trading','stonks','automaton'))
            self.assertNotIn(tool,('submit_order','paper_auto'))
        self.assertIn('PHONE',business_orchestration.ACCOUNT_TYPES)

    def test_automaton_does_not_touch_wallet_or_business(self):
        state={'ledger':[{'amount':'10'}],'orchestration':{'mode':'OFF'}}
        stonks_automaton.start(state)
        stonks_automaton.pause(state)
        stonks_automaton.stop(state)
        self.assertEqual(state['ledger'],[{'amount':'10'}])
        self.assertEqual(state['orchestration'],{'mode':'OFF'})
        self.assertFalse(state['automaton']['live_authority'])

    def test_separate_panel_and_shadow_kill(self):
        root=Path(__file__).resolve().parents[1]
        template=(root/'app/templates/index.html').read_text(encoding='utf-8')
        start=template.index('<section id="zsTab-automaton"')
        end=template.index('</section>',start)
        self.assertIn('zsAutomatonCard',template[start:end])
        self.assertIn('KILL SWITCH',template[start:end])
        self.assertIn('SHADOW',template[start:end])
        for name in ('business-orchestration.js','commerce-agency.js'):
            self.assertNotIn('registro Automaton',(root/'app/static'/name).read_text(encoding='utf-8'))

    def test_preflight_without_heartbeat_is_unverified(self):
        from app import stonks_preflight
        result=stonks_preflight.evaluate({'engine_last_run':None},'AAPL',{},False,False)
        heartbeat=next(x for x in result['checks'] if x['code']=='HEARTBEAT')
        self.assertEqual(heartbeat['status'],'UNVERIFIED')
        self.assertEqual(result['status'],'BLOCKED')

    def test_signature_and_missing_secret(self):
        raw=json.dumps({'id':'evt_offline','type':'unknown'}).encode()
        stamp=str(int(time.time()))
        digest=hmac.new(b'offline-secret',stamp.encode()+b'.'+raw,hashlib.sha256).hexdigest()
        with patch.dict(os.environ,{'STRIPE_WEBHOOK_SECRET':'offline-secret'},clear=True):
            event=agency_events.verify_event(raw,'t='+stamp+',v1='+digest)
            self.assertEqual(agency_events.apply_event(event),{'ignored':True})
            with self.assertRaises(ValueError):agency_events.verify_event(raw+b' ','t='+stamp+',v1='+digest)
            with self.assertRaises(ValueError):agency_events.verify_event(raw,'t=1,v1='+digest)
        with patch.dict(os.environ,{},clear=True):
            with self.assertRaises(ValueError):agency_events.verify_event(raw,'t='+stamp+',v1='+digest)

if __name__=='__main__': unittest.main()
