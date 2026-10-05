import hashlib
import json
import pytest
from app.node_worker import Worker
from app.node_coordinator import create_app


def test_identity_restart_queue_cancel_recovery(tmp_path):
    worker = Worker(tmp_path)
    identity = worker.identity()
    jid = worker.enqueue({'id': 'durable', 'kind': 'diagnostics'})
    assert worker.enqueue({'id': jid, 'kind': 'diagnostics'}) == jid
    restarted = Worker(tmp_path)
    assert restarted.identity() == identity
    assert restarted.heartbeat()['name'] == 'ZAR-NODE-02-MAC'
    with restarted.connect() as con:
        con.execute("UPDATE jobs SET state='RUNNING'")
    restarted.recover()
    assert restarted.get(jid)['state'] == 'INTERRUPTED'
    assert not restarted.run_one()
    jid = restarted.enqueue({'kind':'diagnostics'})
    assert restarted.run_one()
    assert restarted.get(jid)['state'] == 'SUCCEEDED'
    cancelled = restarted.enqueue({'kind': 'diagnostics'})
    restarted.cancel(cancelled)
    assert not restarted.run_one()
    assert Worker(tmp_path).get(cancelled)['state'] == 'CANCELLED'


def test_files_policy_and_running_cancellation(tmp_path, monkeypatch):
    worker = Worker(tmp_path)
    inputs = tmp_path / 'inputs'
    inputs.mkdir()
    (inputs / 'text.txt').write_bytes(b'hello\n')
    jid = worker.enqueue({'kind': 'workspace-summary', 'payload': {'path': 'text.txt'}})
    worker.run_one()
    assert worker.get(jid)['result'] == {'sha256': hashlib.sha256(b'hello\n').hexdigest(), 'bytes': 6, 'lines': 1}
    for path in ['../worker.sqlite3', '/etc/passwd']:
        jid = worker.enqueue({'kind': 'file-sha256', 'payload': {'path': path}})
        worker.run_one()
        assert worker.get(jid)['state'] == 'FAILED'
    with pytest.raises(ValueError):
        worker.enqueue({'kind': 'shell', 'payload': {'command': 'anything'}})
    jid = worker.enqueue({'kind': 'file-sha256', 'payload': {'path': 'text.txt'}})
    original = worker.safe_file
    def cancel_during_execution(value):
        worker.cancel(jid)
        return original(value)
    monkeypatch.setattr(worker, 'safe_file', cancel_during_execution)
    worker.run_one()
    assert worker.get(jid)['state'] == 'CANCELLED'


def test_outbound_protocol_auth_idempotency_restart(tmp_path, monkeypatch):
    worker = Worker(tmp_path / 'worker')
    nid = worker.identity()['id']
    app = create_app(tmp_path / 'cloud', nid, 'n'*43, 'a'*43)
    client = app.test_client()
    admin = {'Authorization': 'Bearer '+ 'a'*43}
    assert client.get('/api/nodes').status_code == 403
    admin['X-ZAR-Nodes-CSRF'] = client.get('/api/nodes',headers=admin).json['csrf']
    assert client.post('/api/node-jobs', json={'kind': 'shell'}, headers=admin).status_code == 400
    job = client.post('/api/node-jobs', json={'kind': 'diagnostics'}, headers=admin).json
    monkeypatch.setenv('ZAR_CLOUD_URL', 'http://127.0.0.1:8766')
    monkeypatch.setenv('ZAR_NODE_TOKEN', 'n'*43)
    def post(url, headers, json, **kwargs):
        from urllib.parse import urlparse
        response = client.post(urlparse(url).path, headers=headers, json=json)
        assert response.status_code == 200
        class Response:
            status_code = 200
            def raise_for_status(self): pass
            def json(self): return response.json
        return Response()
    monkeypatch.setattr('app.node_worker.requests.post', post)
    assert worker.sync()['state'] == 'ONLINE'
    worker.sync()  # lost delivery acknowledgement must not duplicate job
    assert worker.get(job['id'])['state'] == 'QUEUED'
    worker.run_one()
    worker.sync()
    assert client.get('/api/node-jobs/' + job['id'], headers=admin).json['state'] == 'SUCCEEDED'
    assert worker.get(job['id'])['reported'] == 1
    app2 = create_app(tmp_path / 'cloud', nid, 'n'*43, 'a'*43)
    assert app2.test_client().get('/api/node-jobs/' + job['id'], headers=admin).json['state'] == 'SUCCEEDED'
    nodes = client.get('/api/nodes', headers=admin).json['nodes']
    assert nodes[0]['state'] == 'ONLINE'
    import time
    now = time.time()
    monkeypatch.setattr('app.node_coordinator.time.time', lambda: now + 40)
    assert client.get('/api/nodes', headers=admin).json['nodes'][0]['state'] == 'OFFLINE'
    second = client.post('/api/node-jobs', json={'kind': 'diagnostics'}, headers=admin).json
    worker.sync()
    client.post('/api/node-jobs/' + second['id'] + '/cancel', headers=admin)
    worker.sync()
    assert worker.get(second['id'])['state'] == 'CANCELLED'
    assert client.post('/v1/nodes/poll', json={'heartbeat': {'id': 'other'}},
                       headers={'Authorization': 'Bearer '+ 'n'*43}).status_code == 401


def test_unconfigured_and_insecure_transport(tmp_path, monkeypatch):
    worker = Worker(tmp_path)
    monkeypatch.delenv('ZAR_CLOUD_URL', raising=False)
    assert worker.sync()['state'] == 'NOT_CONFIGURED'
    monkeypatch.setenv('ZAR_CLOUD_URL', 'http://cloud.example')
    monkeypatch.setenv('ZAR_NODE_TOKEN', 'test')
    with pytest.raises(ValueError):
        worker.sync()


def test_coordinator_multiple_enrolled_nodes_priority_and_scope(tmp_path):
    one,two = '11111111-1111-4111-8111-111111111111','22222222-2222-4222-8222-222222222222'
    app = create_app(tmp_path, admin_token='admin', enrollment={one: '1'*43, two: '2'*43})
    client = app.test_client()
    admin = {'Authorization': 'Bearer admin'}
    admin['X-ZAR-Nodes-CSRF'] = client.get('/api/nodes',headers=admin).json['csrf']
    low = client.post('/api/node-jobs', headers=admin, json={'kind': 'diagnostics', 'priority': 1}).json
    high = client.post('/api/node-jobs', headers=admin, json={'kind': 'diagnostics', 'priority': 10}).json
    def beat(nid, key, reports=None):
        return client.post('/v1/nodes/poll', headers={'Authorization': 'Bearer ' + key}, json={
            'heartbeat': {'id': nid, 'capabilities': ['python'], 'active_jobs': 0,
                          'resources': {'cpu_count': 4, 'load': [0]}}, 'reports': reports or []})
    assert beat(two, '1'*43).status_code == 401
    assert beat(one, '1'*43).json['jobs'][0]['id'] == high['id']
    assert beat(two, '2'*43, [{'id': high['id'], 'state': 'SUCCEEDED'}]).json['jobs'][0]['id'] == low['id']
    assert client.get('/api/node-jobs/' + high['id'], headers=admin).json['state'] == 'ASSIGNED'
    assert client.get('/api/node-jobs/' + low['id'], headers={'Authorization': 'Bearer '+ '2'*43}).status_code == 403
