"""Focused Paper activation and Gmail workflow regressions, entirely mocked."""
import json
import os
import shutil
import unittest
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch
from app import alpaca_configuration as alpaca, stonks_automaton as auto
from app import agency_crm, agency_mail, agency_events, holdings, business_connectors


class ActivationTests(unittest.TestCase):
    def test_real_ack_and_transitions(self):
        d={}
        auto.start(d)
        self.assertEqual(d['automaton']['state'],'STARTING')
        self.assertIsNone(d['automaton']['last_heartbeat'])
        auto.start(d)
        self.assertEqual(len(d['automaton']['journal']),1)
        auto.heartbeat(d)
        self.assertEqual(d['automaton']['state'],'ACTIVE')
        beat=d['automaton']['last_heartbeat']
        auto.pause(d)
        self.assertEqual(d['automaton']['last_heartbeat'],beat)
        auto.start(d); auto.heartbeat(d)
        auto.stopping(d)
        self.assertEqual(d['automaton']['state'],'STOPPING')
        auto.stop(d)
        self.assertEqual(d['automaton']['state'],'OFF')
        self.assertFalse(d['automaton']['live_authority'])

    def test_failure_and_stale_heartbeat(self):
        d={}; auto.start(d); auto.heartbeat(d)
        d['automaton']['last_heartbeat']=(datetime.now(timezone.utc)-timedelta(seconds=100)).isoformat()
        self.assertEqual(auto.public_view(d)['state'],'ERROR')
        auto.fail(d,'offline')
        self.assertTrue(d['paused'])
        auto.heartbeat(d)
        self.assertEqual(d['automaton']['state'],'ERROR')
        self.assertEqual(auto.ensure({'automaton':{'state':'RUNNING'}})['state'],'ACTIVE')

    def test_atomic_credentials_and_live_block(self):
        with patch.dict(os.environ,{'ALPACA_PAPER_API_KEY':'old','ALPACA_PAPER_API_SECRET':'old-secret'},clear=True):
            self.assertEqual(alpaca.credentials(),('old','old-secret'))
            with patch.dict(os.environ,{'ALPACA_API_KEY':'new'}):
                self.assertEqual(alpaca.credentials(),('new',''))
            with patch.dict(os.environ,{'ALPACA_BASE_URL':'https://api.alpaca.markets'}):
                with self.assertRaises(ValueError):alpaca.validate_environment()

    def test_preflight_is_fail_closed(self):
        state={'mode':'paper','execution_mode':'shadow','max_trade_eur':10,'max_daily_loss_eur':20,'max_position_pct':10}
        account={'id':'mock','status':'ACTIVE','trading_blocked':False,'account_blocked':False,'equity':'100','buying_power':'100'}
        feed={'p':100,'t':datetime.now(timezone.utc).isoformat()}
        self.assertTrue(alpaca.preflight(state,account,feed,True)['ready_to_start'])
        for changes in ({'revoked':True},{'max_daily_loss_eur':0},{'mode':'live'}):
            self.assertFalse(alpaca.preflight(dict(state,**changes),account,feed,True)['ready_to_start'])
        self.assertFalse(alpaca.preflight(state,dict(account,trading_blocked=True),feed,True)['ready_to_start'])
        self.assertFalse(alpaca.preflight(state,account,{},True)['ready_to_start'])
        self.assertFalse(alpaca.preflight(state,account,feed,True)['ready_to_trade'])
        stale=dict(feed,t=(datetime.now(timezone.utc)-timedelta(seconds=100)).isoformat())
        self.assertFalse(alpaca.preflight(state,account,stale,True,{'is_open':True})['ready_to_start'])
        self.assertTrue(alpaca.preflight(state,account,stale,True,{'is_open':False})['ready_to_start'])

    def test_node_guides_never_expose_values(self):
        with patch.dict(os.environ,{'ALPACA_API_KEY':'secret-offline-key','ALPACA_API_SECRET':'secret-offline-token'},clear=True):
            nodes=business_connectors.inventory()
        self.assertNotIn('secret-offline',json.dumps(nodes))
        node=next(x for x in nodes if x['name']=='Alpaca Paper')
        self.assertEqual(node['group'],'TRADING')
        self.assertEqual(node['state'],'POR CONFIGURAR')
        self.assertEqual(len(node['configuration']),3)


class MailTests(unittest.TestCase):
    def setUp(self):
        self.root=Path(__file__).resolve().parents[1]
        self.tmp=self.root/('zar-mail-test-'+uuid.uuid4().hex);self.tmp.mkdir()
        self.env=patch.dict(os.environ,{'ZAR_DATA_DIR':str(self.tmp)},clear=True);self.env.start()
        self.scope='offline-mail'
        self.lead=agency_crm.operate(self.scope,'lead',{'name':'Offline business','email':'lead@example.test'})
        d=holdings.read(self.scope);d['orchestration']={'mode':'SUPERVISED'}
        lead=d['agency_crm']['leads'][0]
        lead['emails']=[{'id':'draft','to':'lead@example.test','subject':'ZAR','body':'Somos ZAR. Baja disponible.'}]
        p={'id':'proposal','currency':'EUR','minimum':'100','target':'200','premium':'300','scope':'Reviewed'}
        lead['proposals']=[p];lead['proposal_id']=p['id'];holdings.write(self.scope,d)
    def tearDown(self):
        self.env.stop();assert self.tmp.resolve().is_relative_to(self.root);shutil.rmtree(self.tmp)
    def test_oauth_required(self):
        with patch('app.gmail.is_connected',return_value=False),patch('app.gmail.send_message') as send:
            with self.assertRaises(ValueError):agency_mail.send(self.scope,{'lead_id':self.lead['id'],'draft_id':'draft','confirmed':True})
            send.assert_not_called()
        with patch('app.gmail.is_connected',return_value=False):
            self.assertEqual(agency_mail.verify(self.scope)['state'],'POR CONFIGURAR')
    def test_mail_identity_and_scoped_threads(self):
        with patch('app.gmail.is_connected',return_value=True),patch('app.gmail.gmail_status',return_value={'email':'zar@example.test'}):
            self.assertEqual(agency_mail.verify(self.scope)['state'],'LISTO')
        d=holdings.read(self.scope);d['agency_crm']['leads'][0]['thread_id']='correct';holdings.write(self.scope,d)
        with patch('app.gmail.is_connected',return_value=True),patch('app.gmail.search_messages',return_value=[{'id':'a','threadId':'wrong'},{'id':'b','threadId':'correct'}]),patch('app.agency_events.inbound',return_value={'id':'b'}) as inbound:
            self.assertEqual(agency_mail.sync_inbound(self.scope,{'lead_id':self.lead['id']}),[{'id':'b'}])
            self.assertEqual(inbound.call_count,1)
            self.assertEqual(inbound.call_args.args[1]['message_id'],'b')
    def test_real_confirmed_send_is_idempotent(self):
        with patch('app.gmail.is_connected',return_value=True),patch('app.gmail.gmail_status',return_value={'email':'zar@example.test'}),patch('app.gmail.send_message',return_value={'id':'sent-mock','threadId':'thread'}) as send:
            payload={'lead_id':self.lead['id'],'draft_id':'draft','confirmed':True}
            agency_mail.send(self.scope,payload);agency_mail.send(self.scope,payload)
            self.assertEqual(send.call_count,1)
        self.assertEqual(holdings.read(self.scope)['agency_crm']['leads'][0]['state'],'CONTACTED')
    def test_ambiguous_send_never_retries(self):
        with patch('app.gmail.is_connected',return_value=True),patch('app.gmail.gmail_status',return_value={'email':'zar@example.test'}),patch('app.gmail.send_message',side_effect=TimeoutError) as send:
            payload={'lead_id':self.lead['id'],'draft_id':'draft','confirmed':True}
            with self.assertRaises(ValueError):agency_mail.send(self.scope,payload)
            self.assertEqual(agency_mail.send(self.scope,payload)['send_intent'],'REVIEW_REQUIRED')
            self.assertEqual(send.call_count,1)
    def test_inbound_classifies_negotiates_and_preserves_baja(self):
        message={'id':'mock-inbound','from':'lead@example.test','threadId':'thread','text':'Muy caro. Podemos pagar 150 EUR.'}
        with patch('app.gmail.get_message',return_value=message):
            row=agency_events.inbound(self.scope,{'lead_id':self.lead['id'],'message_id':message['id'],'auto_classify':True})
            self.assertEqual(row['classification'],'TOO_EXPENSIVE')
            agency_events.inbound(self.scope,{'lead_id':self.lead['id'],'message_id':message['id'],'auto_classify':True})
        lead=holdings.read(self.scope)['agency_crm']['leads'][0]
        self.assertEqual(lead['state'],'NEGOTIATING');self.assertEqual(len(lead['proposals']),2)
        self.assertFalse(lead['emails'][-1]['sent'])
        message.update(id='mock-baja',text='No me contactes')
        with patch('app.gmail.get_message',return_value=message):
            agency_events.inbound(self.scope,{'lead_id':self.lead['id'],'message_id':message['id'],'auto_classify':True})
        with patch('app.gmail.is_connected',return_value=True),patch('app.gmail.send_message') as send:
            with self.assertRaises(ValueError):agency_mail.send(self.scope,{'lead_id':self.lead['id'],'draft_id':'draft','confirmed':True})
            send.assert_not_called()
    def test_outside_and_ambiguous_offers_require_review(self):
        lead=holdings.read(self.scope)['agency_crm']['leads'][0]
        for text in ('50 EUR','150 EUR o 250 EUR'):
            row={'id':uuid.uuid4().hex,'classification':'TOO_EXPENSIVE','text':text}
            agency_mail.auto_negotiate(lead,row)
            self.assertEqual(len(lead['proposals']),1)
            self.assertIn('negotiation_state',row)


if __name__=='__main__':unittest.main()
