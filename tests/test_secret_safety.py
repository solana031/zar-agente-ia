"""Incident regression tests: synthetic secrets, offline providers, no real keys."""
import io
import json
import logging
from unittest.mock import Mock,patch
import pytest
from flask import Flask,jsonify,session
from app import config
from app.secret_safety import install,redact_text,redact_payload,redact_credential_error


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


@pytest.mark.parametrize('message',[
    'Authorization: Basic fixture-opaque-basic-value',
    '{"client_secret":"fixture-opaque-basic-value"}',
    "accessToken='fixture-opaque-basic-value'",
    'https://example.test/callback#id_token=fixture-opaque-basic-value',
    'postgresql://user:fixture-opaque-basic-value@db.test/app',
])
def test_opaque_credentials_in_error_text_are_redacted(message):
    assert 'fixture-opaque-basic-value' not in redact_text(message)


def test_scalar_json_and_file_only_refresh_errors_are_redacted(monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setenv('GEMINI_API_KEY','fixture-scalar-env-value')
    app=Flask('scalar-fixture');install(app)
    @app.get('/')
    def scalar():return jsonify('fixture-scalar-env-value')
    assert app.test_client().get('/').json=='[REDACTED]'
    creds=SimpleNamespace(token='fixture-file-access',refresh_token='fixture-file-refresh',client_secret='fixture-file-client')
    result=redact_credential_error('failed fixture-file-access fixture-file-refresh fixture-file-client',creds)
    assert 'fixture-file-' not in result and result.count('[REDACTED]')==3


@pytest.mark.parametrize('module_name',['cloud_auth','youtube_auth'])
def test_refresh_error_never_exposes_or_rewrites_existing_vault(tmp_path,monkeypatch,module_name):
    import importlib
    from app import holdings,oauth_vault
    module=importlib.import_module('app.'+module_name)
    path=tmp_path/'oauth.json';original='{"format":"ZAR_OAUTH_ENCRYPTED_V1","ciphertext":"fixture-only"}'
    path.write_text(original)
    class Credentials:
        expired=True;token='fixture-vault-access';refresh_token='fixture-vault-refresh';client_secret='fixture-vault-client'
        def refresh(self,request):raise module.RefreshError(self.token+' '+self.refresh_token+' '+self.client_secret)
    monkeypatch.setattr(module.Credentials,'from_authorized_user_info',lambda *args:Credentials())
    monkeypatch.setattr(oauth_vault,'decode',lambda *args:{})
    monkeypatch.setattr(holdings,'read',lambda *args:{})
    monkeypatch.setattr(module,'TOKEN_FILE',path)
    if module_name=='cloud_auth':monkeypatch.setattr(module,'_token_file',lambda user_id=None:path)
    monkeypatch.setattr(module,'_save_credentials',lambda *args,**kw:pytest.fail('Failed refresh must not overwrite vault'))
    assert module.get_credentials() is None
    assert 'fixture-vault-' not in module._LAST_ERROR
    assert module._LAST_ERROR.count('[REDACTED]')==3
    assert path.read_text()==original
