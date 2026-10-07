"""Offline integration/control tests. Real OS probes never invoke a model."""
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

from flask import Flask
import pytest
from app import automation_control as control, automation_sandbox as sandbox
from app import coding_runner, conway_adapter, integrations, jev_decision, media_company, media_narrator
from app.dramaclaw_client import DramaClawClient
from app.node_coordinator import Coordinator, token_hash
from app.node_worker import Worker


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.setenv('ZAR_DATA_DIR', str(tmp_path/'data'))
    monkeypatch.setenv('ZAR_NODE_DIR', str(tmp_path/'node'))
    for name in ['RAILWAY_ENVIRONMENT','JEV_API_KEY','TYPESAFE_API_KEY','DRAMACLAW_API_URL','ZAR_CODEX_ENABLED','ZAR_CODING_LOCAL_MODEL']:
        monkeypatch.delenv(name, raising=False)


def test_zero_budget_unknown_cost_and_execution_fail_closed():
    assert control.policy()['monthly_cents'] == 0
    for provider in ['dramaclaw','jev','elevenlabs','conway','codex']:
        with pytest.raises(PermissionError): control.paid_call(provider, 'task')
        with pytest.raises(PermissionError): control.reserve(provider, 'task', 1)
    with pytest.raises(ValueError): control.configure({'conway_mode':'EXECUTE'})
    assert control.policy()['conway_mode'] == 'OFF'
    assert control.policy()['coding_mode'] == 'DISABLED'


@pytest.mark.parametrize('value', [-1, True, 1.1, float('nan'), '10'])
def test_budget_rejects_non_integer_limits(value):
    with pytest.raises(ValueError): control.configure({'monthly_cents':value})


def test_atomic_budget_task_daily_monthly_and_provider():
    control.configure({'per_task_cents':10,'daily_cents':30,'monthly_cents':50,'providers':{'jev':20,'dramaclaw':50}})
    control.reserve('jev','first',10)
    with pytest.raises(PermissionError): control.reserve('jev','first',1)
    control.reserve('jev','second',10)
    with pytest.raises(PermissionError): control.reserve('jev','third',1)
    control.reserve('dramaclaw','third',10)
    with pytest.raises(PermissionError): control.reserve('dramaclaw','fourth',1)
    control.configure({'daily_cents':100,'monthly_cents':30})
    with pytest.raises(PermissionError): control.reserve('dramaclaw','fourth',1)
    control.configure({'kill_switch':True})
    with pytest.raises(PermissionError): control.reserve('dramaclaw','fourth',1)


def test_concurrent_reservations_do_not_overspend():
    control.configure({'per_task_cents':1,'daily_cents':3,'monthly_cents':3,'providers':{'jev':3}})
    def reserve(n):
        try: control.reserve('jev',str(n),1); return True
        except PermissionError: return False
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert sum(pool.map(reserve, range(10))) == 3


def test_approval_one_use_scope_and_expiration(monkeypatch):
    spec={'task':'review','files':['a.py']}
    rid=control.approve_locally(spec)
    with pytest.raises(PermissionError): control.consume_approval(rid,{'task':'different'})
    control.consume_approval(rid,spec)
    with pytest.raises(PermissionError): control.consume_approval(rid,spec)
    expired=control.approve_locally(spec,1)
    now=time.time();monkeypatch.setattr(control.time,'time',lambda:now+2)
    with pytest.raises(PermissionError): control.consume_approval(expired,spec)


def test_audit_redacts_payload_and_extra_metadata():
    control.audit('jev','recommendation',{'private_state':'fixture-private'}, {'tier':'small','api_key':'fixture-private'})
    with control.connection() as con:
        body=dict(con.execute('SELECT * FROM audit').fetchone())
    assert 'fixture-private' not in json.dumps(body)
    assert json.loads(body['details']) == {'tier':'small'}


def test_jev_budget_blocks_before_transport(monkeypatch):
    monkeypatch.setenv('TYPESAFE_API_KEY','fixture-key')
    monkeypatch.setattr(jev_decision.requests,'post',lambda *a,**k:pytest.fail('provider called'))
    result=jev_decision.decide('routing',{'tier':{'type':'choice','criteria':{'small':'yes'}}})
    assert result['fallback'] and result['provider_error']=='BUDGET_BLOCKED'
    assert jev_decision.status()['state']=='DEGRADED'


def test_jev_circuit_breaker_and_recovery(monkeypatch):
    monkeypatch.setenv('TYPESAFE_API_KEY','fixture-key')
    monkeypatch.setattr(control,'paid_call',lambda *a:'mock-reservation')
    calls=[]
    def failed(*a,**k):
        calls.append(k);raise jev_decision.requests.Timeout('fixture')
    monkeypatch.setattr(jev_decision.requests,'post',failed)
    for _ in range(3): assert jev_decision.decide('state',{})['fallback']
    assert jev_decision.status()['circuit_open']
    assert jev_decision.decide('state',{})['provider_error']=='JEV_CIRCUIT_OPEN'
    assert len(calls)==3 and all(0<k['timeout']<=10 for k in calls)
    now=time.time();monkeypatch.setattr(jev_decision.time,'time',lambda:now+61)
    class Response:
        ok=True
        def json(self): return {'answers':{}}
    monkeypatch.setattr(jev_decision.requests,'post',lambda *a,**k:Response())
    assert not jev_decision.decide('state',{})['fallback']
    assert jev_decision.status()['state']=='ONLINE'


def test_jev_only_official_endpoint_no_redirects(monkeypatch):
    monkeypatch.setenv('TYPESAFE_API_KEY','fixture-key')
    monkeypatch.setattr(jev_decision,'BASE','http://other.invalid')
    monkeypatch.setattr(jev_decision.requests,'post',lambda *a,**k:pytest.fail('provider called'))
    assert jev_decision.decide('state',{})['provider_error']=='INVALID_OFFICIAL_ENDPOINT'


def test_dramaclaw_mutation_and_media_production_blocked(monkeypatch):
    class Session:
        def request(self,*a,**k): pytest.fail('upstream mutation called')
    client=DramaClawClient('https://drama.invalid',session=Session())
    for method in ['POST','PUT','PATCH','DELETE']:
        with pytest.raises(PermissionError): client._request(method,'/api/v1/projects')
    monkeypatch.setattr(media_company,'_task',lambda *a:{'payload':{'master_brief':'brief'}})
    monkeypatch.setattr(media_company,'_client',lambda:client)
    with pytest.raises(PermissionError): media_company.produce_local('scope','task')


def test_optional_elevenlabs_never_paid_fallback(monkeypatch):
    from app import voice_pro
    monkeypatch.setenv('ZAR_MEDIA_VOICE_PROVIDER','elevenlabs')
    monkeypatch.setattr(voice_pro,'_eleven_configured',lambda:True)
    monkeypatch.setattr(voice_pro,'_eleven_synthesize',lambda *a:pytest.fail('paid ElevenLabs called'))
    monkeypatch.setattr(voice_pro,'synthesize',lambda *a:pytest.fail('paid fallback called'))
    monkeypatch.setattr(media_narrator.shutil,'which',lambda *a:None)
    assert media_narrator.sample() is None


def test_local_narrator_uses_offline_real_command_contract(monkeypatch):
    from app import voice_pro
    monkeypatch.setattr(voice_pro,'_eleven_configured',lambda:False)
    monkeypatch.setattr(media_narrator.shutil,'which',lambda *a:'/usr/bin/say')
    monkeypatch.setattr(sandbox,'available',lambda:True)
    def run(argv,cwd,boundary,**kw):
        assert argv[0]=='/usr/bin/say' and '--file-format=WAVE' in argv
        assert 'network-outbound' not in boundary
        Path(argv[2]).write_bytes(b'RIFF'+b'offline-fixture')
        return {'exit_code':0}
    monkeypatch.setattr(sandbox,'run',run)
    audio,mime,provider=media_narrator.sample()
    assert audio.startswith(b'RIFF') and mime=='audio/wav' and provider=='external/macOS-say'


def test_conway_off_denylist_scope_and_kill():
    with pytest.raises(PermissionError): conway_adapter.observe()
    with pytest.raises(PermissionError): conway_adapter.propose('exec',{'command':'anything'})
    control.configure({'conway_mode':'PROPOSE'})
    for tool in ['exec','transfer','purchase','deploy','publish','delete','wallet','change_secret']:
        assert conway_adapter.propose(tool,{})['action']=='deny'
    for name in ['../secret','.env','/private/file','.ssh/id_ed25519']:
        with pytest.raises(ValueError): conway_adapter.propose('read_file',{'path':name})
    control.configure({'kill_switch':True})
    with pytest.raises(PermissionError): conway_adapter.observe()


def spec(mode='PATCH',files=None):
    return {'task':'Change the constant safely','files':['a.py'] if files is None else files,'mode':mode,'tests':['python-syntax'],'approval_id':''}


@pytest.mark.parametrize('file', ['../a.py','.env','.ssh/key','/tmp/file','auth.json','key.pem','.local/file','.git/config',''])
def test_coding_scope_refuses_private_or_escaping_paths(file):
    with pytest.raises(ValueError): coding_runner.validate(spec(files=[file]))


def test_coding_default_disabled_and_unknown_approval(monkeypatch):
    with pytest.raises(PermissionError): coding_runner.run_task(spec())
    control.configure({'coding_mode':'PATCH'})
    monkeypatch.setattr(sandbox,'available',lambda:True)
    monkeypatch.setattr(coding_runner.shutil,'which',lambda name:'/fixture/'+name)
    monkeypatch.setenv('ZAR_CODING_LOCAL_MODEL','fixture-local:latest')
    mock_model_inventory(monkeypatch)
    monkeypatch.setattr(coding_runner,'_git',lambda *a,**k:'')
    with pytest.raises(PermissionError): coding_runner.run_task(spec())


def mock_model_inventory(monkeypatch):
    class Response:
        status_code=200
        def json(self):return {'models':[{'name':'fixture-local:latest','size':2000000,'details':{'format':'gguf'}}]}
    monkeypatch.setattr(coding_runner.requests,'get',lambda *a,**k:Response())


@pytest.fixture
def coding_repo(tmp_path, monkeypatch):
    repo=tmp_path/'repo';repo.mkdir();(repo/'a.py').write_text('VALUE = 1\n')
    def git(*args):
        return subprocess.check_output(['git',*args],cwd=repo,text=True,stderr=subprocess.DEVNULL)
    git('init','-b','main');git('add','a.py');git('-c','user.name=Offline Test','-c','user.email=offline@example.invalid','commit','-m','fixture')
    monkeypatch.setattr(coding_runner,'ROOT',repo)
    monkeypatch.setattr(sandbox,'available',lambda:True)
    monkeypatch.setenv('ZAR_CODING_LOCAL_MODEL','fixture-local:latest')
    mock_model_inventory(monkeypatch)
    control.configure({'coding_mode':'PATCH'})
    return repo,git


def test_real_worktree_mock_cli_patch_and_main_unchanged(coding_repo,monkeypatch):
    repo,git=coding_repo;head=git('rev-parse','HEAD')
    payload=spec();payload['approval_id']=control.approve_locally(coding_runner.validate(payload))
    def run(argv,cwd,boundary,**kw):
        assert '--oss' in argv and '--ignore-user-config' in argv and 'shell_tool' in argv
        for feature in coding_runner.DISABLED_FEATURES:
            assert argv[argv.index(feature)-1]=='--disable'
        assert '--local-provider' in argv and 'ollama' in argv
        worktree=Path(argv[argv.index('--cd')+1])
        assert worktree != repo and '--skip-git-repo-check' in argv
        assert 'localhost:11434' in boundary and '\\.git' in boundary
        (worktree/'a.py').write_text('VALUE = 2\n')
        return {'exit_code':0,'output':'fixture model output'}
    monkeypatch.setattr(sandbox,'run',run)
    result=coding_runner.run_task(payload)
    assert result['state']=='SUCCEEDED' and '+VALUE = 2' in result['diff']
    assert result['model_commands_limit']==0 and result['tests']==[{'file':'a.py','check':'python-syntax','ok':True}]
    assert git('rev-parse','HEAD')==head and git('status','--porcelain')==''
    assert (repo/'a.py').read_text()=='VALUE = 1\n'
    assert result['commit_push_deploy']=='HUMAN_ACTION_REQUIRED'
    assert result['snapshot_removed'] and result['worktree_removed'] and result['temporary_branch_removed']
    assert result['codex_home_removed']
    assert len(git('worktree','list').splitlines())==1
    assert git('branch','--list','zar-task/*')==''
    with pytest.raises(PermissionError): coding_runner.run_task(payload)
    with control.connection() as con:
        assert json.loads(con.execute('SELECT body FROM coding_results WHERE id=?',(result['id'],)).fetchone()[0])['diff']==result['diff']


def test_local_cancellation_and_persisted_result_read(web,coding_repo,monkeypatch):
    monkeypatch.setattr(media_company,'status',lambda:{'ready':False,'dramaclaw_direct_configured':False})
    payload=spec();payload['approval_id']=control.approve_locally(coding_runner.validate(payload))
    csrf=web.get('/api/integrations',base_url='http://127.0.0.1').json['csrf']
    def run(argv,cwd,boundary,**kw):
        with control.connection() as con:tid=con.execute('SELECT id FROM coding_results').fetchone()[0]
        path='/api/integrations/coding/results/'+tid
        assert web.get(path,base_url='http://127.0.0.1').json['result']['state']=='RUNNING'
        assert web.post(path+'/cancel',base_url='http://127.0.0.1').status_code==403
        assert web.post(path+'/cancel',headers={'X-ZAR-Integrations-CSRF':csrf},base_url='http://127.0.0.1').status_code==200
        assert kw['cancelled']() is True
        return {'exit_code':0,'output':'cancelled fixture'}
    monkeypatch.setattr(sandbox,'run',run)
    result=coding_runner.run_task(payload)
    assert result['state']=='CANCELLED'
    assert control.coding_result(result['id'])['state']=='CANCELLED'
    with pytest.raises(ValueError):control.cancel_coding(result['id'])


@pytest.mark.parametrize('failure',['scope','secret','syntax','cli','cancel'])
def test_coding_results_fail_closed_and_main_preserved(coding_repo,monkeypatch,failure):
    repo,git=coding_repo;payload=spec();payload['approval_id']=control.approve_locally(coding_runner.validate(payload))
    def run(argv,cwd,boundary,**kw):
        target=Path(argv[argv.index('--cd')+1])
        if failure=='scope': (target/'outside.py').write_text('unexpected')
        elif failure=='secret': (target/'a.py').write_text('ghp_'+'x'*30)
        elif failure=='syntax': (target/'a.py').write_text('def invalid(')
        return {'exit_code':1 if failure=='cli' else 0,'output':'fixture output'}
    monkeypatch.setattr(sandbox,'run',run)
    result=coding_runner.run_task(payload,cancelled=lambda:failure=='cancel')
    assert result['state']==('CANCELLED' if failure=='cancel' else 'FAILED')
    assert git('status','--porcelain')=='' and (repo/'a.py').read_text()=='VALUE = 1\n'
    assert 'x'*30 not in json.dumps(result)


def test_coordinator_worker_coding_contract_and_capability(tmp_path):
    coordinator=Coordinator(tmp_path/'coordinator')
    worker=Worker(tmp_path/'worker');identity=worker.identity()
    coordinator.provision(identity['id'],identity['name'],token_hash('fixture-node-'+'x'*40))
    beat=worker.heartbeat()
    assert 'coding-agent-local' not in beat['capabilities']
    assert beat['optional_capabilities']['coding-agent']['mode']=='DISABLED'
    assert coordinator.submit({'kind':'coding-task','payload':spec(),'timeout':30,'max_cost_per_job':0})
    with pytest.raises(ValueError): coordinator.submit({'kind':'coding-task','payload':{'task':'no scope'}})
    # No task is sent or claimed; a disabled worker refuses coding locally.
    jid=worker.enqueue({'kind':'coding-task','payload':spec()})
    assert worker.run_one() and worker.get(jid)['state']=='FAILED'


@pytest.fixture
def web(monkeypatch):
    app=Flask(__name__);app.secret_key='offline-test-session'
    monkeypatch.setenv('ZAR_NODES_LOCAL_ADMIN','1')
    integrations.register(app)
    return app.test_client()


def test_inventory_evidence_and_admin_csrf(web,monkeypatch):
    monkeypatch.setattr(media_company,'status',lambda:{'ready':True,'dramaclaw_direct_configured':True})
    response=web.get('/api/integrations',base_url='http://127.0.0.1')
    assert response.status_code==200
    data=response.json
    assert [c['name'] for c in data['cards']]==['DramaClaw','Jev','Conway Automaton','Coding Agent','NODE-01','NODE-02','ZAR Cloud']
    assert data['cards'][0]['state']=='DEGRADED' and not data['cards'][0]['generation_verified']
    assert data['policy']['monthly_cents']==0
    assert all(c['state']!='ONLINE' for c in data['cards'])
    headers={'X-ZAR-Integrations-CSRF':data['csrf']}
    assert web.post('/api/integrations/policy',json={'confirmed':True,'changes':{'coding_mode':'PATCH'}},base_url='http://127.0.0.1').status_code==403
    assert web.post('/api/integrations/policy',json={'confirmed':False,'changes':{}},headers=headers,base_url='http://127.0.0.1').status_code==400
    assert web.post('/api/integrations/policy',json={'confirmed':True,'changes':{'conway_mode':'EXECUTE'}},headers=headers,base_url='http://127.0.0.1').status_code==400
    assert web.post('/api/integrations/probe/jev',headers=headers,base_url='http://127.0.0.1').json['result']['external_call'] is False
    headers['Origin']='https://other.invalid'
    assert web.post('/api/integrations/policy',json={'confirmed':True,'changes':{}},headers=headers,base_url='http://127.0.0.1').status_code==403
    assert web.get('/api/integrations',base_url='http://external.invalid').status_code==403


def test_cloud_cannot_enable_node_execution(web,monkeypatch):
    from app import node_coordinator
    monkeypatch.setattr(node_coordinator,'production_admin',lambda:True)
    monkeypatch.setenv('RAILWAY_ENVIRONMENT','production')
    monkeypatch.setattr(media_company,'status',lambda:{'ready':False,'dramaclaw_direct_configured':False})
    data=web.get('/api/integrations',base_url='http://127.0.0.1').json
    assert web.post('/api/integrations/policy',json={'confirmed':True,'changes':{'coding_mode':'PATCH'}},headers={'X-ZAR-Integrations-CSRF':data['csrf']},base_url='http://127.0.0.1').status_code==403


def test_policy_malformed_modes_and_cloud_kill_only_coding(web,monkeypatch,tmp_path):
    monkeypatch.setattr(media_company,'status',lambda:{'ready':False,'dramaclaw_direct_configured':False})
    coordinator=Coordinator(tmp_path/'coordinator')
    web.application.extensions['node_coordinator']=coordinator
    job=coordinator.submit({'kind':'coding-task','payload':spec()})
    other=coordinator.submit({'kind':'diagnostics'})
    data=web.get('/api/integrations',base_url='http://127.0.0.1').json
    headers={'X-ZAR-Integrations-CSRF':data['csrf']}
    for changes in [[], {'coding_mode':[]}, {'conway_mode':None}]:
        assert web.post('/api/integrations/policy',json={'confirmed':True,'changes':changes},headers=headers,base_url='http://127.0.0.1').status_code==400
    assert web.post('/api/integrations/policy',json={'confirmed':True,'changes':{'kill_switch':True}},headers=headers,base_url='http://127.0.0.1').status_code==200
    with coordinator.connect() as con:
        assert con.execute('SELECT state FROM distributed_jobs WHERE id=?',(job['id'],)).fetchone()[0]=='CANCELLED'
        assert con.execute('SELECT state FROM distributed_jobs WHERE id=?',(other['id'],)).fetchone()[0]=='QUEUED'
    with pytest.raises(ValueError,match='kill switch'):coordinator.submit({'kind':'coding-task','payload':spec()})


def test_worker_observes_remote_cancel_during_coding(tmp_path,monkeypatch):
    worker=Worker(tmp_path/'worker')
    jid=worker.enqueue({'kind':'coding-task','payload':spec(),'deadline':time.time()+120},remote=True)
    with worker.connect() as con:con.execute('UPDATE jobs SET claimed=1 WHERE id=?',(jid,))
    clock=[0];polls=[]
    monkeypatch.setattr('app.node_worker.time.monotonic',lambda:clock[0])
    def sync():
        polls.append(True)
        if len(polls)>1:worker.cancel(jid)
    monkeypatch.setattr(worker,'sync',sync)
    def run(payload,cancelled):
        clock[0]=3
        assert cancelled() is True
        return {'state':'CANCELLED'}
    monkeypatch.setattr(coding_runner,'run_task',run)
    assert worker.run_one() and worker.get(jid)['state']=='CANCELLED' and len(polls)==2


def test_coding_scheduler_zero_cost_and_no_remote_activation(tmp_path,monkeypatch):
    coordinator=Coordinator(tmp_path/'cloud');worker=Worker(tmp_path/'worker');identity=worker.identity()
    coordinator.provision(identity['id'],identity['name'],token_hash('fixture-node-'+'x'*40))
    job=coordinator.submit({'kind':'coding-task','payload':spec(),'max_cost_per_job':0})
    beat={'capabilities':['coding-agent-local'],'resources':{'cpu_count':1,'load':[0]},'version':'33.3.0'}
    result=coordinator.poll(identity['id'],{'heartbeat':beat})
    assert [j['id'] for j in result['jobs']]==[job['id']]
    assert control.policy()['coding_mode']=='DISABLED'


def test_local_inventory_uses_recent_actual_node_cloud_heartbeat(tmp_path,monkeypatch):
    monkeypatch.setattr(media_company,'status',lambda:{'ready':False,'dramaclaw_direct_configured':False})
    worker=Worker();beat=worker.heartbeat();beat['cloud_state']='ONLINE'
    with worker.connect() as con:con.execute('UPDATE heartbeat SET payload=? WHERE id=1',(json.dumps(beat),))
    data=integrations.inventory()
    assert data['cards'][5]['state']=='ONLINE' and data['cards'][5]['node']==worker.identity()['id']
    assert data['cards'][6]['state']=='ONLINE' and data['cards'][6]['version'] is None
    assert data['cards'][6]['last_heartbeat']==beat['timestamp']


def test_cloud_safe_probe_health_only_no_token(monkeypatch):
    from app import node_inference
    monkeypatch.setattr(node_inference,'transport',lambda:('https://cloud.invalid','fixture-private','NOT_VERIFIED',''))
    calls=[]
    class Response:
        status_code=200
        def __init__(self,body):self.body=body
        def json(self):return self.body
    def get(session,url,**kw):
        assert session.trust_env is False and 'headers' not in kw and 'auth' not in kw and kw['allow_redirects'] is False
        calls.append(url)
        return Response({'ok':True,'service':'zar','version':'33.3.0'} if url.endswith('/health') and '/v1/' not in url else {'ok':True,'protocol':1})
    monkeypatch.setattr(integrations.requests.Session,'get',get)
    result=integrations.probe('cloud')
    assert result=={'state':'ONLINE','version':'33.3.0','protocol':1,'inference_performed':False}
    assert calls==['https://cloud.invalid/health','https://cloud.invalid/v1/nodes/health']


def test_cloud_native_cards_use_sanitized_node_reports(tmp_path,monkeypatch):
    coordinator=Coordinator(tmp_path/'cloud');worker=Worker();identity=worker.identity()
    coordinator.provision(identity['id'],identity['name'],token_hash('fixture-node-'+'x'*40))
    beat=worker.heartbeat()
    beat['optional_capabilities']={'coding-agent':{'state':'DISABLED','mode':'DISABLED','version':'0.160.0','installed':True,'auth':'fixture-private'},
                                   'conway-runtime':{'state':'DISABLED','mode':'OFF','version':'0.2.1','upstream_installed':True,'wallet':'fixture-private'}}
    coordinator.poll(identity['id'],{'heartbeat':beat})
    monkeypatch.setenv('RAILWAY_ENVIRONMENT','production')
    monkeypatch.setattr(media_company,'status',lambda:{'ready':False,'dramaclaw_direct_configured':False})
    data=integrations.inventory(coordinator)
    for i in [2,3]:
        assert data['cards'][i]['node']==identity['id'] and data['cards'][i]['state']=='DISABLED'
        assert data['cards'][i]['local_controls_allowed'] is False
    assert data['cards'][2]['version']=='0.2.1' and data['cards'][3]['version']=='0.160.0'
    with coordinator.connect() as con:body=con.execute('SELECT payload FROM distributed_nodes').fetchone()[0]
    assert 'fixture-private' not in body and 'wallet' not in body and 'auth' not in body


def test_missing_local_model_never_downloads_or_runs_cli(coding_repo,monkeypatch):
    class Response:
        status_code=200
        def json(self):return {'models':[]}
    monkeypatch.setattr(coding_runner.requests,'get',lambda *a,**k:Response())
    monkeypatch.setattr(sandbox,'run',lambda *a,**k:pytest.fail('CLI called'))
    with pytest.raises(PermissionError,match='already be installed'):coding_runner.run_task(spec())


@pytest.mark.parametrize('metadata',[{'remote_host':'https://remote.invalid','size':2000000,'details':{'format':'gguf'}},
                                   {'remote_model':'cloud-model','size':2000000,'details':{'format':'gguf'}},
                                   {'size':300,'details':{'format':'gguf'}},
                                   {'size':2000000,'details':{'format':'unknown'}}])
def test_ollama_remote_or_unverified_weights_blocked(coding_repo,monkeypatch,metadata):
    class Response:
        status_code=200
        def json(self):return {'models':[{'name':'fixture-local:latest',**metadata}]}
    monkeypatch.setattr(coding_runner.requests,'get',lambda *a,**k:Response())
    monkeypatch.setattr(sandbox,'run',lambda *a,**k:pytest.fail('CLI called'))
    with pytest.raises(PermissionError):coding_runner.run_task(spec())


def test_os_sandbox_blocks_secrets_writes_and_network(tmp_path):
    if not sandbox.available():
        with pytest.raises(PermissionError): sandbox.run(['/bin/echo','probe'],tmp_path,'')
        return
    allowed=tmp_path/'allowed';allowed.mkdir();(allowed/'.env').write_text('fixture-private')
    (allowed/'.git').mkdir();(allowed/'.git/config').write_text('fixture-private')
    (allowed/'write.txt').write_text('keep')
    private=tmp_path/'private.txt';private.write_text('fixture-private')
    python=Path(sys.executable).resolve()
    script="""import pathlib,socket,json
checks=[]
for p in ['.env','../private.txt','.git/config']:
 try:pathlib.Path(p).read_text();checks.append(False)
 except PermissionError:checks.append(True)
try:pathlib.Path('unexpected.txt').write_text('bad');checks.append(False)
except PermissionError:checks.append(True)
try:pathlib.Path('write.txt').unlink();checks.append(False)
except PermissionError:checks.append(True)
try:socket.create_connection(('127.0.0.1',9),timeout=1);checks.append(False)
except PermissionError:checks.append(True)
print(json.dumps(checks))
"""
    boundary=sandbox.profile([allowed,python,Path(sys.base_prefix)],[allowed/'write.txt'],executables=[python])
    result=sandbox.run([str(python),'-c',script],allowed,boundary,timeout=10)
    assert result['exit_code']==0, result
    assert json.loads(result['output'])==[True,True,True,True,True,True]
    assert not (allowed/'unexpected.txt').exists()


def test_os_sandbox_timeout_and_cancellation(tmp_path):
    if not sandbox.available():
        with pytest.raises(PermissionError): sandbox.run(['/bin/echo','probe'],tmp_path,'')
        return
    boundary=sandbox.profile(['/bin/sleep'],executables=['/bin/sleep'])
    with pytest.raises(TimeoutError): sandbox.run(['/bin/sleep','10'],tmp_path,boundary,timeout=.1)
    with pytest.raises(TimeoutError): sandbox.run(['/bin/sleep','10'],tmp_path,boundary,cancelled=lambda:True)


def test_official_conway_policy_engine_is_proposal_only(monkeypatch):
    if not sandbox.available() or not conway_adapter.status()['upstream_installed']:
        with pytest.raises(PermissionError): conway_adapter.observe()
        return
    control.configure({'conway_mode':'PROPOSE'})
    original=sandbox.run
    def checked(*args,**kwargs):
        outcome=original(*args,**kwargs)
        assert outcome['exit_code']==0,outcome
        return outcome
    monkeypatch.setattr(sandbox,'run',checked)
    result=conway_adapter.propose('read_file',{'path':'README.md'})
    assert result['action']=='quarantine' and result['requires_review'] and not result['executed']
    assert result['toolName']=='read_file' and len(result['argsHash'])==64
    assert not conway_adapter.status()['runtime_running']


def test_real_codex_version_only_no_model():
    if not sandbox.available() or not shutil.which('codex'):
        return
    result=integrations.probe('coding')
    assert result['cli_version_verified'],result
    assert result['state']=='DISABLED' and not result['model_execution_verified']


def test_real_offline_voice_sample_no_paid_provider(monkeypatch):
    from app import voice_pro
    monkeypatch.setattr(voice_pro,'_eleven_configured',lambda:False)
    if not sandbox.available() or not shutil.which('say'):
        assert media_narrator.sample() is None
        return
    audio,mime,provider=media_narrator.sample()
    assert audio.startswith(b'RIFF') and b'WAVE' in audio[:12]
    assert 1000<len(audio)<=2*1024*1024 and mime=='audio/wav' and provider=='external/macOS-say'


def test_coding_dirty_development_uses_only_clean_canonical_head(coding_repo,monkeypatch):
    repo,git=coding_repo;head=git('rev-parse','HEAD').strip()
    (repo/'a.py').write_text('LOCAL_PENDING = 99\n')
    (repo/'pending.txt').write_text('preserve untracked\n')
    before=git('status','--porcelain')
    payload=spec();payload.update(mode='READ_ONLY',tests=[])
    control.configure({'coding_mode':'READ_ONLY'})
    payload['approval_id']=control.approve_locally(coding_runner.validate(payload))
    def run(argv,cwd,boundary,**kw):
        tree=Path(argv[argv.index('--cd')+1])
        assert (tree/'a.py').read_text()=='VALUE = 1\n'
        assert not (tree/'pending.txt').exists()
        assert subprocess.check_output(['git','status','--porcelain'],cwd=tree,text=True)==''
        assert subprocess.check_output(['git','rev-parse','HEAD'],cwd=tree,text=True).strip()==head
        return {'exit_code':0,'output':'fixture only, no real model'}
    monkeypatch.setattr(sandbox,'run',run)
    result=coding_runner.run_task(payload)
    assert result['state']=='SUCCEEDED' and result['diff']=='' and result['source_head']==head
    assert result['snapshot_removed'] and result['worktree_removed'] and result['temporary_branch_removed']
    assert git('status','--porcelain')==before and git('rev-parse','HEAD').strip()==head
    assert (repo/'a.py').read_text()=='LOCAL_PENDING = 99\n'
    assert (repo/'pending.txt').read_text()=='preserve untracked\n'
    assert len(git('worktree','list').splitlines())==1 and git('branch','--list','zar-task/*')==''


def test_coding_snapshot_dirty_or_changed_head_rejected(coding_repo,monkeypatch,tmp_path):
    repo,git=coding_repo
    original=coding_runner._git
    def git_call(*args,**kw):
        if args==('status','--porcelain') and kw.get('cwd'):
            return ' M a.py\n'
        return original(*args,**kw)
    monkeypatch.setattr(coding_runner,'_git',git_call)
    with pytest.raises(PermissionError,match='clean and match'):
        with coding_runner.clean_snapshot(tmp_path):pytest.fail('Dirty snapshot accepted')
    assert not (tmp_path/'source').exists()
    assert git('status','--porcelain')==''


def test_coding_source_repository_not_selectable():
    with pytest.raises(ValueError,match='Exact coding task schema'):
        coding_runner.validate({**spec(),'repository':'/external/repo'})


def test_coding_snapshot_head_race_rejected(coding_repo,monkeypatch,tmp_path):
    original=coding_runner._git;reads=0
    def git_call(*args,**kw):
        nonlocal reads
        if args==('rev-parse','HEAD') and not kw.get('cwd'):
            reads+=1
            if reads>1:return '0'*40
        return original(*args,**kw)
    monkeypatch.setattr(coding_runner,'_git',git_call)
    with pytest.raises(PermissionError,match='clean and match'):
        with coding_runner.clean_snapshot(tmp_path):pytest.fail('Changed HEAD accepted')
    assert not (tmp_path/'source').exists()


def test_os_sandbox_ollama_only_and_scoped_files(tmp_path):
    import socket,threading
    assert sandbox.available(), 'Native sandbox required for this regression'
    listener=socket.socket();listener.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
    listener.bind(('127.0.0.1',11434));listener.listen();listener.settimeout(15)
    received=[]
    def accept():
        connection,_=listener.accept()
        with connection:received.append(connection.recv(32));connection.sendall(b'LOCAL PROBE OK')
    thread=threading.Thread(target=accept,daemon=True);thread.start()
    tree=tmp_path/'worktree';tree.mkdir()
    allowed=tree/'VERSION';allowed.write_text('probe-authorized')
    write=tmp_path/'temporary.txt';write.write_text('before')
    blocked=[tree/'.env',tree/'credentials.json',tree/'private.txt',tree/'.git/config',tmp_path/'host-home/.ssh/id_ed25519']
    for path in blocked:path.parent.mkdir(exist_ok=True,parents=True);path.write_text('fixture-private')
    python=Path(sys.executable).resolve()
    boundary=sandbox.profile([allowed,python,Path(sys.base_prefix)],[write],executables=[python],local_model=True)
    script='''import pathlib,socket,json,os
checks={}
assert os.environ['CODEX_OSS_BASE_URL']=='http://127.0.0.1:11434/v1'
assert 'OLLAMA_BASE_URL' not in os.environ
checks['authorized_read']=pathlib.Path(PATHS['allowed']).read_text()=='probe-authorized'
pathlib.Path(PATHS['write']).write_text('temporary-only');checks['temporary_write']=True
with socket.create_connection(('127.0.0.1',11434),timeout=3) as s:
 s.sendall(b'probe');checks['ollama_loopback']=s.recv(32)==b'LOCAL PROBE OK'
for host,port,name in [('198.51.100.1',443,'internet'),('127.0.0.1',11435,'other_local_port')]:
 try:socket.create_connection((host,port),timeout=1);checks[name]=False
 except PermissionError:checks[name]=True
for index,path in enumerate(PATHS['blocked']):
 try:pathlib.Path(path).read_text();checks['private_'+str(index)]=False
 except PermissionError:checks['private_'+str(index)]=True
try:pathlib.Path(PATHS['outside']).write_text('bad');checks['outside_write']=False
except PermissionError:checks['outside_write']=True
try:pathlib.Path(PATHS['allowed']).write_text('bad');checks['readonly_write']=False
except PermissionError:checks['readonly_write']=True
print(json.dumps(checks))
'''
    paths={'allowed':str(allowed),'write':str(write),'blocked':[str(p) for p in blocked],'outside':str(tmp_path/'outside.txt')}
    try:
        outcome=sandbox.run([str(python),'-c','PATHS='+repr(paths)+'\n'+script],tree,boundary,timeout=15)
        assert outcome['exit_code']==0,outcome
        checks=json.loads(outcome['output']);assert len(checks)==12 and all(checks.values()),checks
        thread.join(timeout=2);assert received==[b'probe']
        assert allowed.read_text()=='probe-authorized' and write.read_text()=='temporary-only'
        assert not (tmp_path/'outside.txt').exists()
    finally:listener.close()
