from app import jev_decision, conway_adapter, coding_capability
import pytest


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
