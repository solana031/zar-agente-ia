"""Health remains local and backward compatible; no provider/session work."""
from pathlib import Path
from flask import Flask
from app.runtime_health import install


def test_health_keeps_both_old_and_new_success_contracts(monkeypatch):
    monkeypatch.setenv('RAILWAY_GIT_COMMIT_SHA','a'*40)
    app=Flask(__name__);install(app)
    @app.before_request
    def forbidden_work():raise AssertionError('Health must not touch sessions or providers')
    response=app.test_client().get('/health')
    assert response.status_code==200
    assert response.json['ok'] is True
    assert response.json['status']=='ok'
    assert response.json['version']==Path('app/VERSION.txt').read_text().strip()
    assert response.json['commit']=='a'*40
    assert 'Set-Cookie' not in response.headers
    assert response.headers['Cache-Control']=='no-store'
