from app import jev_decision, conway_adapter, coding_capability
import pytest


@pytest.fixture(autouse=True)
def isolated_mock_provider(monkeypatch, tmp_path):
    # These contract tests use fake responses, never a real paid provider.
    monkeypatch.setenv('ZAR_DATA_DIR', str(tmp_path))
    monkeypatch.setattr(jev_decision.control, 'paid_call', lambda *args: 'mock-reservation')


@pytest.mark.parametrize('answer', [
    {'type':'choice','choice':'allow'},
    {'type':'choice','choice':[]},
    {'type':'choice','choice':{}},
    {'type':'choice','choice':None},
    {'type':'choice'},
    {'type':'choice','choice':True},
    {'type':'choice','choice':1},
    {'type':'choice','choice':'unknown'},
    {'type':'noul','noul':0.5},
    None, [], 'allow',
])
def test_jev_choice_validation_degrades_safely(monkeypatch, answer):
    monkeypatch.setenv('JEV_API_KEY', 'fixture-key')
    monkeypatch.setattr(jev_decision.time, 'sleep', lambda _: None)
    data = {'model':'jev-latest', 'answers':{'route':answer}}
    class Response:
        ok = True
        def json(self): return data
    monkeypatch.setattr(jev_decision.requests, 'post', lambda *a, **k: Response())
    result = jev_decision.decide('test', {
        'route':{'type':'choice','criteria':{'allow':'Allowed','deny':'Denied'}}})
    valid = answer == {'type':'choice','choice':'allow'}
    assert result['fallback'] is not valid
    assert result['state'] == ('ONLINE' if valid else 'DEGRADED')
    if valid:
        assert result is data
        assert result['answers']['route'] == answer
    else:
        assert result['model'] == 'zar-deterministic-fallback'


@pytest.mark.parametrize('body', [None, [], 'invalid', {}, {'answers':None},
                                     {'answers':[]}, {'answers':{}}])
def test_jev_invalid_api_body_degrades(monkeypatch, body):
    monkeypatch.setenv('JEV_API_KEY', 'fixture-key')
    monkeypatch.setattr(jev_decision.time, 'sleep', lambda _: None)
    class Response:
        ok = True
        def json(self): return body
    monkeypatch.setattr(jev_decision.requests, 'post', lambda *a, **k: Response())
    assert jev_decision.decide('test', {'route':{'type':'choice','criteria':{'allow':'yes'}}})['state'] == 'DEGRADED'


@pytest.mark.parametrize('failure', ['json', 'http', 'transport', 'programming'])
def test_jev_api_failures_and_programming_errors(monkeypatch, failure):
    monkeypatch.setenv('JEV_API_KEY', 'fixture-key')
    monkeypatch.setattr(jev_decision.time, 'sleep', lambda _: None)
    class Response:
        ok = failure != 'http'
        status_code = 503
        def json(self): raise ValueError('invalid JSON')
    def post(*args, **kwargs):
        if failure == 'transport': raise jev_decision.requests.Timeout('fixture')
        if failure == 'programming': raise TypeError('unrelated bug')
        return Response()
    monkeypatch.setattr(jev_decision.requests, 'post', post)
    if failure == 'programming':
        with pytest.raises(TypeError, match='unrelated bug'):
            jev_decision.decide('test', {})
    else:
        assert jev_decision.decide('test', {})['state'] == 'DEGRADED'


@pytest.mark.parametrize('value', [[], {}, '0.5', None, True, float('nan'), float('inf'), 10**400])
def test_jev_unexpected_numeric_types_degrade(monkeypatch, value):
    monkeypatch.setenv('JEV_API_KEY', 'fixture-key')
    monkeypatch.setattr(jev_decision.time, 'sleep', lambda _: None)
    class Response:
        ok = True
        def json(self): return {'answers':{'review':{'type':'noul','noul':value}}}
    monkeypatch.setattr(jev_decision.requests, 'post', lambda *a, **k: Response())
    assert jev_decision.decide('test', {'review':{'type':'noul'}})['state'] == 'DEGRADED'


def test_jev_real_contract_and_malformed_fallback(monkeypatch):
    monkeypatch.setenv('JEV_API_KEY', 'fixture-key')
    monkeypatch.setattr(jev_decision.time, 'sleep', lambda _: None)
    questions = {'review': {'type': 'noul', 'instructions': 'Needs review?'}}
    class Response:
        ok = True
        def json(self): return {'model': 'jev-latest', 'answers': {'review': {'type': 'noul', 'noul': .8}}}
    def post(url, **kwargs):
        assert url == 'https://api.typesafe.ai/v1/systemone'
        assert kwargs['json']['questions'] == questions
        assert kwargs['allow_redirects'] is False
        return Response()
    monkeypatch.setattr(jev_decision.requests, 'post', post)
    assert not jev_decision.decide('state', questions)['fallback']
    monkeypatch.setattr(Response, 'json', lambda _: {'answers': {'review': {'type': 'noul', 'noul': float('nan')}}})
    assert jev_decision.decide('state', questions)['state'] == 'DEGRADED'
    monkeypatch.delenv('JEV_API_KEY')
    monkeypatch.delenv('TYPESAFE_API_KEY', raising=False)
    assert jev_decision.status()['state'] == 'NOT_CONFIGURED'


def test_conway_missing_runtime_and_codex_policy(tmp_path, monkeypatch):
    monkeypatch.setattr(conway_adapter, 'SOURCE', tmp_path)
    assert conway_adapter.status(probe=True)['state'] == 'NOT_CONFIGURED'
    monkeypatch.setenv('ZAR_CODEX_ENABLED', '0')
    with pytest.raises(PermissionError):
        coding_capability.prepare('task', tmp_path, authorized=True)
    monkeypatch.setenv('ZAR_CODEX_ENABLED', '1')
    monkeypatch.setattr(coding_capability.shutil, 'which', lambda _: '/fixture/codex')
    monkeypatch.setattr(coding_capability, 'ROOT', tmp_path)
    checkout = tmp_path / '.local/workspaces/repo'
    (checkout / '.git').mkdir(parents=True)
    with pytest.raises(PermissionError):
        coding_capability.prepare('task', checkout)
    with pytest.raises(ValueError):
        coding_capability.prepare('task', tmp_path, authorized=True)
    plan = coding_capability.prepare('review this code', checkout, authorized=True)
    assert plan['state'] == 'PREPARED_NOT_EXECUTED'
    assert 'read-only' in plan['argv']
    assert '--ignore-user-config' in plan['argv']
