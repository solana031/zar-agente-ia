"""Directed coordinator contract tests; no external connection or paid operation."""
import importlib.util
import json
from pathlib import Path
import secrets
import time
import uuid

import pytest
from app.node_coordinator import Coordinator, create_app, token_hash
from app.node_worker import Worker


@pytest.fixture
def system(tmp_path):
    nid = str(uuid.uuid4()); token = secrets.token_urlsafe(32)
    app = create_app(tmp_path/'cloud',nid,token,'isolated-test-admin')
    client = app.test_client()
    admin = {'Authorization':'Bearer isolated-test-admin'}
    admin['X-ZAR-Nodes-CSRF'] = client.get('/api/nodes',headers=admin).json['csrf']
    headers = {'Authorization':'Bearer '+token}
    beat = {'id':nid,'capabilities':['python','node','filesystem','shell','coding-agent'],
            'resources':{'os':'Darwin','architecture':'x86_64','cpu_count':4,'ram_bytes':8589934592,'load':[0]},
            'version':'33.2.0','worker_version':'1.0.0','uptime':12}
    return app,client,admin,headers,beat,token


def poll(client,headers,beat,reports=None):
    return client.post('/v1/nodes/poll',headers=headers,json={'heartbeat':beat,'reports':reports or []})


def test_auth_enrollment_revocation_hashes_no_disclosure(system):
    app,client,admin,headers,beat,token = system
    assert poll(client,{'Authorization':'Bearer '+secrets.token_urlsafe(32)},beat).status_code==401
    assert client.post('/v1/nodes/enroll',headers=headers,json={'heartbeat':beat}).status_code==200
    assert poll(client,headers,beat).status_code==200
    public = client.get('/api/nodes',headers=admin)
    assert token.encode() not in public.data and b'token_hash' not in public.data
    with app.extensions['node_coordinator'].connect() as con:
        row = con.execute('SELECT token_hash FROM distributed_nodes').fetchone()
        assert row[0]==token_hash(token) and row[0]!=token
    assert client.post('/api/nodes/'+beat['id']+'/revoke',headers=admin).status_code==200
    assert poll(client,headers,beat).status_code==403
    assert client.post('/api/nodes/'+beat['id']+'/resume',headers=admin).status_code==409
    assert client.get('/api/nodes',headers=admin).json['nodes'][0]['state']=='REVOKED'


def test_heartbeat_capabilities_pause_csrf_offline(system,monkeypatch):
    app,client,admin,headers,beat,_ = system
    poll(client,headers,beat)
    node = client.get('/api/nodes',headers=admin).json['nodes'][0]
    assert node['capabilities']==['filesystem','node','python']
    assert node['resources']['ram_bytes']==8589934592 and node['worker_version']=='1.0.0'
    assert client.post('/api/nodes/'+beat['id']+'/pause',headers={'Authorization':admin['Authorization']}).status_code==403
    bad = {**admin,'Origin':'https://evil.example'}
    assert client.post('/api/nodes/'+beat['id']+'/pause',headers=bad).status_code==403
    assert client.post('/api/nodes/'+beat['id']+'/pause',headers=admin).status_code==200
    assert poll(client,headers,beat).json['paused'] is True
    job = client.post('/api/node-jobs',headers=admin,json={'kind':'node-info'}).json
    assert poll(client,headers,beat).json['jobs']==[]
    client.post('/api/nodes/'+beat['id']+'/resume',headers=admin)
    assert poll(client,headers,beat).json['jobs'][0]['id']==job['id']
    original = time.time(); monkeypatch.setattr('app.node_coordinator.time.time',lambda:original+31)
    assert client.get('/api/nodes',headers=admin).json['nodes'][0]['state']=='OFFLINE'


def test_claim_progress_result_restart_and_cancellation(system,tmp_path):
    app,client,admin,headers,beat,token = system
    job = client.post('/api/node-jobs',headers=admin,json={'kind':'node-info'}).json
    assert poll(client,headers,beat).json['jobs'][0]['id']==job['id']
    claim = '/v1/jobs/'+job['id']+'/claim'
    assert client.post(claim,headers=headers,json={'heartbeat':beat}).status_code==200
    assert client.get('/api/nodes',headers=admin).json['nodes'][0]['state']=='BUSY'
    report = {'id':job['id'],'state':'RUNNING','progress':50}
    poll(client,headers,beat,[report])
    assert client.get('/api/nodes',headers=admin).json['nodes'][0]['current_job']['progress']==50
    report.update(state='SUCCEEDED',progress=100,result={'hostname':'test-host','architecture':'x86_64','python':'3.12','node':'v22','timestamp':'2026-10-05T00:00:00Z'})
    assert poll(client,headers,beat,[report]).json['ack']==[job['id']]
    assert client.get('/api/nodes',headers=admin).json['nodes'][0]['state']=='ONLINE'
    app2 = create_app(tmp_path/'cloud',beat['id'],token,'isolated-test-admin')
    result = app2.test_client().get('/api/node-jobs/'+job['id'],headers=admin)
    assert result.json['state']=='SUCCEEDED'
    second = client.post('/api/node-jobs',headers=admin,json={'kind':'node-info'}).json
    poll(client,headers,beat)
    client.post('/api/node-jobs/'+second['id']+'/cancel',headers=admin)
    assert second['id'] in poll(client,headers,beat).json['cancel']
    assert client.post('/v1/jobs/'+second['id']+'/claim',headers=headers,json={'heartbeat':beat}).status_code==409


def test_timeout_disconnect_and_no_arbitrary_jobs(system,monkeypatch):
    app,client,admin,headers,beat,_ = system
    for body in ({'kind':'shell','payload':{'command':'id'}},{'kind':'node-info','payload':{'command':'id'}},{'kind':'node-info','timeout':'invalid'},{'kind':'node-info','max_cost_per_job':float('nan')}):
        assert client.post('/api/node-jobs',headers=admin,json=body).status_code==400
    job = client.post('/api/node-jobs',headers=admin,json={'kind':'node-info','timeout':5}).json
    poll(client,headers,beat)
    original = time.time(); monkeypatch.setattr('app.node_coordinator.time.time',lambda:original+6)
    assert client.get('/api/node-jobs/'+job['id'],headers=admin).json['state']=='TIMED_OUT'
    # Expiration is visible without waiting for the next worker request.
    client.get('/api/nodes',headers=admin)
    assert client.get('/api/node-jobs/'+job['id'],headers=admin).json['state']=='TIMED_OUT'
    monkeypatch.setattr('app.node_coordinator.time.time',lambda:original)
    job = client.post('/api/node-jobs',headers=admin,json={'kind':'node-info','timeout':300}).json
    poll(client,headers,beat)
    client.post('/v1/jobs/'+job['id']+'/claim',headers=headers,json={'heartbeat':beat})
    monkeypatch.setattr('app.node_coordinator.time.time',lambda:original+65)
    reconnect = poll(client,headers,beat)
    assert job['id'] in reconnect.json['cancel']
    assert client.get('/api/node-jobs/'+job['id'],headers=admin).json['state']=='INTERRUPTED'


def test_real_handler_transport_contract_and_restart(tmp_path,monkeypatch):
    # Protocol tests isolate scheduling inputs; overload rejection is tested separately.
    monkeypatch.setattr('app.node_worker.resources',lambda:{'os':'Darwin','architecture':'x86_64','cpu_count':4,'ram_bytes':8589934592,'load':[0]})
    worker = Worker(tmp_path/'worker'); nid = worker.identity()['id']; token = secrets.token_urlsafe(32)
    app = create_app(tmp_path/'cloud',nid,token,'test-admin')
    client = app.test_client(); admin = {'Authorization':'Bearer test-admin'}
    admin['X-ZAR-Nodes-CSRF'] = client.get('/api/nodes',headers=admin).json['csrf']
    job = client.post('/api/node-jobs',headers=admin,json={'kind':'node-info'}).json
    monkeypatch.setenv('ZAR_CLOUD_URL','https://cloud.example'); monkeypatch.setenv('ZAR_NODE_TOKEN',token)
    from urllib.parse import urlparse
    class Response:
        def __init__(self,response): self.status_code=response.status_code; self.response=response
        def raise_for_status(self): assert self.status_code==200
        def json(self): return self.response.json
    monkeypatch.setattr('app.node_worker.requests.post',lambda url,**kw:Response(client.post(urlparse(url).path,headers=kw['headers'],json=kw['json'])))
    assert worker.sync()['state']=='ONLINE'
    assert worker.get(job['id'])['claimed']==1
    assert worker.run_one()
    worker.sync()
    result = worker.get(job['id'])
    assert result['state']=='SUCCEEDED' and set(result['result'])=={'hostname','architecture','python','node','timestamp'}
    restarted = Worker(tmp_path/'worker'); restarted.recover(); restarted.sync()
    assert restarted.identity()['id']==nid and restarted.get(job['id'])['state']=='SUCCEEDED'
    node = client.get('/api/nodes',headers=admin).json['nodes'][0]
    assert node['state']=='ONLINE'
    with app.extensions['node_coordinator'].connect() as con:
        states = [r[0] for r in con.execute('SELECT state FROM distributed_events WHERE job=?',(job['id'],))]
    assert 'RUNNING' in states and states[-1]=='SUCCEEDED'


def test_enrollment_secret_persists_and_permissions(tmp_path):
    spec = importlib.util.spec_from_file_location('node_enroll','scripts/node-enroll.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    (tmp_path/'.env.local').write_text('UNRELATED=preserved\nZAR_NODE_TOKEN=\n')
    first = module.configure(tmp_path,'https://verified-cloud.example')
    second = module.configure(tmp_path,'https://verified-cloud.example')
    assert first==second
    data = (tmp_path/'.env.local').read_text()
    assert 'UNRELATED=preserved' in data and 'ZAR_NODE_TOKEN=' in data
    assert 'token' not in first and len(first['token_hash'])==64
    assert (tmp_path/'.env.local').stat().st_mode & 0o777==0o600
    with pytest.raises(ValueError): module.configure(tmp_path,'http://untrusted.example')


def test_web_guard_node_auth_and_explicit_ui_owner_policy(monkeypatch):
    from app.main import app
    nid,token = str(uuid.uuid4()),secrets.token_urlsafe(32)
    app.extensions['node_coordinator'].provision(nid,'test-web-node',token_hash(token))
    client = app.test_client()
    monkeypatch.setenv('ZAR_ACCESS_PASSWORD','isolated-password')
    response = client.post('/v1/nodes/poll',headers={'Authorization':'Bearer '+token},json={'heartbeat':{'id':nid,'capabilities':['python']}})
    assert response.status_code==200  # Node never needs the web password.
    assert client.post('/v1/nodes/poll',json={'heartbeat':{'id':nid}}).status_code==401
    assert client.get('/api/nodes').status_code==401
    monkeypatch.delenv('ZAR_ACCESS_PASSWORD'); monkeypatch.delenv('ZAR_NODES_LOCAL_ADMIN',raising=False)
    assert client.get('/api/nodes').status_code==403
    monkeypatch.setenv('ZAR_NODES_ADMIN_EMAILS','owner@example.test')
    with client.session_transaction() as state: state['google_account_email']='other@example.test'
    assert client.get('/api/nodes').status_code==403
    with client.session_transaction() as state: state['google_account_email']='owner@example.test'
    assert client.get('/api/nodes').status_code==200


def test_malformed_request_and_claim_scope(system):
    app,client,admin,headers,beat,_ = system
    for data in ({'heartbeat':[]},{'heartbeat':{'id':[]}}, {'heartbeat':{**beat,'resources':{'cpu_count':-1}}}):
        assert client.post('/v1/nodes/poll',headers=headers,json=data).status_code in {400,401}
    assert client.post('/v1/nodes/poll',headers=headers,data='x'*300000,content_type='application/json').status_code==413
    job = client.post('/api/node-jobs',headers=admin,json={'kind':'node-info'}).json
    poll(client,headers,beat)
    other,key = str(uuid.uuid4()),secrets.token_urlsafe(32)
    app.extensions['node_coordinator'].provision(other,'other',token_hash(key))
    assert client.post('/v1/jobs/'+job['id']+'/claim',headers={'Authorization':'Bearer '+key},json={'heartbeat':{'id':other}}).status_code==409
    # A progress-only report has result=None; an interrupted job must still render.
    client.post('/v1/jobs/'+job['id']+'/claim',headers=headers,json={'heartbeat':beat})
    poll(client,headers,beat,[{'id':job['id'],'state':'INTERRUPTED','progress':1,'result':None}])
    assert client.get('/api/nodes',headers=admin).status_code==200


def test_trusted_provision_cli_uses_only_hash_stdin(tmp_path):
    import os
    import subprocess
    import sys
    nid,token = str(uuid.uuid4()),secrets.token_urlsafe(32)
    descriptor = {'node_id':nid,'name':'ZAR-NODE-TEST','token_hash':token_hash(token)}
    environment = {**os.environ,'ZAR_DATA_DIR':str(tmp_path)}
    response = subprocess.run([sys.executable,'scripts/node-provision.py','enroll'],input=json.dumps(descriptor),env=environment,capture_output=True,text=True,timeout=10)
    assert response.returncode==0, response.stderr
    assert json.loads(response.stdout)=={'ok':True,'node_id':nid}
    assert token not in response.stdout+response.stderr
    store = Coordinator(tmp_path/'coordinator')
    with store.connect() as con:
        assert con.execute('SELECT token_hash FROM distributed_nodes WHERE id=?',(nid,)).fetchone()[0]==descriptor['token_hash']
    again = subprocess.run([sys.executable,'scripts/node-provision.py','enroll'],input=json.dumps(descriptor),env=environment,capture_output=True,text=True,timeout=10)
    assert again.returncode==0
