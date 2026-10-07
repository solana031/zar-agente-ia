import unittest
import shutil
import uuid
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch
from app import holdings, business_orchestration as control


def test_disconnected_and_currency_separation(scope):
    assert control.view(scope)['wallet']['state'] == 'NO CONECTADO'
    control.mutate(scope, 'deposit', {'amount':'100.00', 'reference':'one'})
    control.mutate(scope, 'deposit', {'amount':'100.00', 'reference':'one'})
    holdings.add_ledger(scope, 'sites', 'revenue', 50, currency='USD', verified=True)
    balances = control.view(scope)['wallet']['balances']
    assert float(balances['EUR']['available']) == 100
    assert float(balances['USD']['available']) == 50
    assert control.view('other')['wallet']['balances'] == {}


def test_invalid_ledger(scope):
    for amount in [float('nan'), float('inf'), -1, 0]:
        with unittest.TestCase().assertRaises(ValueError):
            holdings.add_ledger(scope, 'sites', 'revenue', amount)


def test_pending_expenses_and_cancelled_revenue(scope):
    holdings.add_ledger(scope, 'sites', 'cost', 10, status='pending')
    holdings.add_ledger(scope, 'sites', 'revenue', 100, status='cancelled')
    assert holdings.public_view(scope)['companies']['sites']['metrics']['costs'] == 0
    b = control.view(scope)['wallet']['balances']['EUR']
    assert float(b['pending_payments']) == 10
    assert float(b['revenue']) == 0


def test_reservation_requires_confirmation_and_releases(scope):
    control.mutate(scope, 'deposit', {'amount':'100.00', 'reference':'fund'})
    control.mutate(scope, 'mode', {'mode':'SUPERVISED'})
    j = control.mutate(scope, 'prepare', {'item':'Domain', 'provider':'Registrar', 'price':'20.00', 'tax':'4.00'})
    p = j['approvals'][0]
    for payload in ({'id':p['id']}, {'id':p['id'], 'confirmed':True, 'total':'20.00'}):
        with unittest.TestCase().assertRaises(ValueError): control.mutate(scope, 'approve', payload)
    j = control.mutate(scope, 'approve', {'id':p['id'], 'total':p['total'], 'confirmed':True})
    assert float(j['wallet']['balances']['EUR']['available']) == 76
    with unittest.TestCase().assertRaises(ValueError): control.mutate(scope, 'approve', {'id':p['id'], 'total':p['total'], 'confirmed':True})
    j = control.mutate(scope, 'cancel', {'id':p['id']})
    assert float(j['wallet']['balances']['EUR']['available']) == 100
    assert len(j['ledger']) == 1  # no payment was invented


def test_dependency_shadow_pause_and_stop(scope):
    payload = {'agent':'RevenueAgent', 'tool':'wallet_snapshot', 'request_id':'same'}
    j = control.mutate(scope, 'task', payload)
    control.mutate(scope, 'task', payload)
    first = j['tasks'][0]['id']
    control.mutate(scope, 'task', {'agent':'OptimizationAgent', 'tool':'profitability_review', 'dependencies':[first]})
    assert len(control.view(scope)['tasks']) == 2
    control.mutate(scope, 'mode', {'mode':'SHADOW'})
    control.tick(scope)
    assert control.view(scope)['tasks'][0]['state'] == 'QUEUED'
    control.mutate(scope, 'mode', {'mode':'ACTIVE'})
    control.mutate(scope, 'agent', {'id':'RevenueAgent', 'state':'PAUSED'})
    control.tick(scope)
    assert all(t['state']=='QUEUED' for t in control.view(scope)['tasks'])
    control.mutate(scope, 'agent', {'id':'RevenueAgent', 'state':'IDLE'})
    control.tick(scope); control.tick(scope)
    assert all(t['state']=='DONE' for t in control.view(scope)['tasks'])
    holdings.set_global_stop(scope, True)
    cycles = control.view(scope)['cycles']
    control.tick(scope)
    assert control.view(scope)['cycles'] == cycles


def test_financial_history_not_truncated():
    state = holdings.default_state()
    state['ledger'] = [{'id':str(i)} for i in range(5001)]
    assert len(holdings.ensure(state)['ledger']) == 5001


def test_no_unauthorized_tool(scope):
    with unittest.TestCase().assertRaises(ValueError):
        control.mutate(scope, 'task', {'agent':'RevenueAgent', 'tool':'send_money'})


def test_accounts_reject_secrets_and_wait_for_human(scope):
    with unittest.TestCase().assertRaises(ValueError):
        control.mutate(scope, 'account', {'provider':'Mail', 'identity':'zar@example.invalid', 'password':'secret'})
    data = {'provider':'Mail', 'identity':'zar@example.invalid', 'secret_ref':'ZAR_MAIL_TOKEN', 'human_step':'KYC'}
    control.mutate(scope, 'account', data)
    j = control.mutate(scope, 'account', data)
    assert len(j['accounts']) == 1
    assert j['accounts'][0]['state'] == 'AWAITING_HUMAN'
    assert all(n['state'] != 'LISTO' for n in j['connectors'])


def test_corrupt_store_is_not_overwritten(scope):
    path = holdings._file(scope)
    path.write_text('{broken', encoding='utf-8')
    with unittest.TestCase().assertRaises(ValueError):
        control.mutate(scope, 'mode', {'mode':'ACTIVE'})
    assert path.read_text(encoding='utf-8') == '{broken'


def test_multiple_workers_keep_all_entries(scope):
    script = "from app import holdings; import sys; [holdings.add_ledger('business-test','sites','revenue',1,reference=sys.argv[1]+str(i)) for i in range(10)]"
    workers = [subprocess.Popen([sys.executable, '-c', script, str(i)], stdout=subprocess.PIPE, stderr=subprocess.PIPE) for i in range(2)]
    for worker in workers:
        output, error = worker.communicate(timeout=30)
        assert worker.returncode == 0, error.decode(errors='replace')
    assert len(holdings.read(scope)['ledger']) == 20


def test_domain_autonomy_only_prepares_and_legacy_flag_cannot_pay(scope):
    from app import sites_company as sites
    holdings.update_company(scope, 'sites', config={'allow_domain_reinvestment':True, 'auto_domain_purchase':True})
    holdings.add_ledger(scope, 'sites', 'revenue', 100)
    with patch.object(sites, 'status', return_value={'vercel_configured':True, 'domain_registrant_configured':True}), \
         patch.object(sites, '_domain_candidates', return_value=['example.com']), \
         patch.object(sites, 'search_domains', return_value={'results':{}}), \
         patch.object(sites, '_extract_domain_quote', return_value={'available':True, 'price':10}), \
         patch.object(sites, '_usd_to_eur_rate', return_value=1), \
         patch.object(sites, 'gate', return_value={}), \
         patch.object(sites.requests, 'post') as post:
        result = sites._maybe_auto_domain(scope, {'slug':'site'})
        assert result['requires_review']
        assert result['task']['status'] == 'AWAITING_APPROVAL'
        result = sites.buy_domain(scope, 'site', 'example.com', 10, confirmed=True)
        assert result['requires_review']
        assert not result['total_verified']
        post.assert_not_called()


def test_http_csrf_and_scoped_persistence(scope):
    from flask import Flask, session
    app = Flask(__name__)
    app.secret_key = 'offline-test-only'
    def scope_fn():
        return session.setdefault('test_scope', uuid.uuid4().hex)
    control.register(app, scope_fn)
    with app.test_client() as client:
        assert client.post('/api/holdings/orchestration/mode', json={'mode':'ACTIVE'}).status_code == 403
        token = client.get('/api/holdings/orchestration').json['csrf']
        headers = {'X-ZAR-Business-CSRF':token}
        assert client.post('/api/holdings/orchestration/mode', headers=headers, json={'mode':'SUPERVISED'}).status_code == 200
        assert client.post('/api/holdings/orchestration/deposit', headers=headers, json={'amount':'10.00','reference':'test'}).status_code == 200
        assert client.get('/api/holdings/orchestration').json['wallet']['balances']['EUR']['available'] == '10.0'
        assert client.post('/api/holdings/orchestration/mode', headers=headers, json=['ACTIVE']).status_code == 400
    with app.test_client() as other:
        assert other.get('/api/holdings/orchestration').json['wallet']['balances'] == {}
        assert other.post('/api/holdings/orchestration/mode', headers=headers, json={'mode':'ACTIVE'}).status_code == 403


class BusinessControlTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parents[1]
        self.tmp = self.root / ('zar-test-' + uuid.uuid4().hex)
        self.tmp.mkdir()
        self.env = patch.dict('os.environ', {'ZAR_DATA_DIR': str(self.tmp)})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        assert self.tmp.resolve().is_relative_to(self.root)
        shutil.rmtree(self.tmp)


def _test(function):
    def run(self):
        if function.__code__.co_argcount:
            function('business-test')
        else:
            function()
    return run


for name, function in list(globals().items()):
    if name.startswith('test_') and callable(function):
        setattr(BusinessControlTests, name, _test(function))

if __name__ == '__main__':
    unittest.main()
