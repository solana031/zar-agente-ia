"""Incident regression tests: synthetic secrets, offline providers, no real keys."""
import io
import json
import logging
from unittest.mock import Mock,patch
import pytest
from flask import Flask,jsonify,session
from app import config
from app.secret_safety import install,redact_text,redact_payload


@pytest.fixture(autouse=True)
def restore_logging_factory():
    previous=logging.getLogRecordFactory()
    yield
    logging.setLogRecordFactory(previous)


def test_known_and_nested_google_secrets_redacted(monkeypatch):
    monkeypatch.setenv('RELAYCLAW_USAGE_API_KEY','fixture-relay-opaque-credential')
    monkeypatch.setenv('GOOGLE_CLIENT_CONFIG_JSON',json.dumps({'web':{'client_secret':'fixture-google-client-credential'}}))
    text=redact_text('fixture-relay-opaque-credential fixture-google-client-credential')
    assert text=='[REDACTED] [REDACTED]'


def test_provider_patterns_bearer_and_query_codes():
    fabricated='sk-or-v1-'+'fixture'*12
    text=redact_text(fabricated+' Authorization: Bearer fixture-access-credential https://example.test/callback?code=fixture-auth-code&key=fixture-api-key')
    assert fabricated not in text and 'fixture-access-credential' not in text
    assert '?code=[REDACTED]&key=[REDACTED]' in text


def test_json_boundary_preserves_status_csrf_and_session():
    app=Flask('secret-fixture');app.secret_key='fixture-session-only';install(app)
    @app.get('/')
    def route():
        session['connected']=True
        return jsonify(status='CONNECTED',csrf='fixture-csrf-required-by-ui',capabilities={'publishing':'READY'},credentials={'access_token':'fixture-private-token'},diagnostic='Bearer fixture-header-credential')
    @app.get('/session')
    def check():return jsonify(connected=session.get('connected'))
    client=app.test_client();result=client.get('/').json
    assert result['status']=='CONNECTED' and result['capabilities']['publishing']=='READY'
    assert result['csrf']=='fixture-csrf-required-by-ui'
    assert result['credentials']['access_token']=='[REDACTED]'
    assert 'fixture-header-credential' not in result['diagnostic']
    assert client.get('/session').json['connected'] is True


def test_logs_include_no_secret_in_message_arguments_or_exception(monkeypatch):
    secret='fixture-private-provider-credential'
    monkeypatch.setenv('GEMINI_API_KEY',secret)
    app=Flask('logging-fixture');install(app)
    output=io.StringIO();handler=logging.StreamHandler(output)
    logger=logging.getLogger('zar.incident.fixture');logger.handlers=[handler];logger.propagate=False;logger.setLevel(logging.INFO)
    try:
        logger.info('provider %s',secret)
        try:raise ValueError('provider echoed '+secret)
        except ValueError:logger.exception('request failed')
        logged=output.getvalue()
        assert secret not in logged
        assert '[REDACTED]' in logged and 'ValueError' in logged
    finally:logger.handlers=[]


def test_openrouter_environment_replacement_and_empty_value_are_authoritative(tmp_path,monkeypatch):
    path=tmp_path/'config.json';path.write_text(json.dumps({'openrouter':{'api_key':'fixture-obsolete-file-key'}}))
    monkeypatch.setattr(config,'CONFIG_PATH',path)
    monkeypatch.setenv('OPENROUTER_API_KEY','fixture-replacement-env-key')
    assert config.load()['openrouter']['api_key']=='fixture-replacement-env-key'
    monkeypatch.setenv('OPENROUTER_API_KEY','')
    assert config.load()['openrouter']['api_key']==''
    config.save({'openrouter':{'api_key':'fixture-browser-old-key'}})
    assert json.loads(path.read_text())['openrouter']['api_key']==''


def test_cloud_save_does_not_persist_maps_key(tmp_path,monkeypatch):
    path=tmp_path/'config.json';monkeypatch.setattr(config,'CONFIG_PATH',path)
    monkeypatch.setenv('ZAR_MAPS_API_KEY','fixture-maps-credential')
    config.save({'maps':{'api_key':'fixture-maps-credential'}})
    assert 'fixture-maps-credential' not in path.read_text()


def test_provider_exception_cannot_echo_passed_key():
    from app.agent import _post_api_json
    secret='fixture-file-only-provider-key'
    response=Mock(ok=False,status_code=401,text='rejected '+secret)
    with patch('app.agent.requests.post',return_value=response):
        with pytest.raises(RuntimeError) as error:_post_api_json('https://provider.test',secret,{})
    assert secret not in str(error.value)
    assert '401' in str(error.value)


def test_recursive_redaction_does_not_mutate_evidence():
    original={'diagnostic':{'new_token_persisted':True,'source':'CANONICAL_OAUTH'},'tokens':[{'refresh_token':'fixture-refresh-only','apiKey':'fixture-file-only-key','clientSecret':'fixture-file-only-client'}]}
    clean=redact_payload(original)
    assert original['tokens'][0]['refresh_token']=='fixture-refresh-only'
    assert clean['tokens'][0]['refresh_token']=='[REDACTED]'
    assert clean['tokens'][0]['apiKey']=='[REDACTED]'
    assert clean['tokens'][0]['clientSecret']=='[REDACTED]'
    assert clean['diagnostic']==original['diagnostic']
