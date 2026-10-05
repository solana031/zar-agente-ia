import json
import secrets
import time
import uuid

import pytest
import requests
from app import node_inference
from app.node_coordinator import create_app
from app.node_worker import Worker


@pytest.fixture
def local(tmp_path,monkeypatch):
    monkeypatch.setenv('ZAR_NODE_DIR',str(tmp_path/'node'))
    monkeypatch.setenv('ZAR_NODE_CHAT','1')
    monkeypatch.delenv('RAILWAY_ENVIRONMENT',raising=False)
    monkeypatch.delenv('ZAR_CLOUD_URL',raising=False)
    monkeypatch.delenv('ZAR_NODE_TOKEN',raising=False)
    monkeypatch.delenv('ZAR_NODE_LOCAL_FALLBACK',raising=False)
    monkeypatch.setattr(node_inference,'_LAST',{})
    worker = Worker()
    return worker


def test_local_identity_uses_real_hardware_without_model(local):
    answer = node_inference.respond('Hola ZAR, dime en qué nodo estás ejecutándote y qué capacidades locales tienes disponibles.',{})
    assert local.identity()['id'] in answer
    assert 'ZAR-NODE-02-MAC' in answer and 'python' in answer and 'DEGRADED' in answer
    assert 'no generados por un modelo' in answer
    assert 'Smart Router no encuentra' not in node_inference.respond('Hola, razona sobre una tarea.',{})


def test_transport_validation_and_no_raw_error(local,monkeypatch):
    token=secrets.token_urlsafe(32)
    monkeypatch.setenv('ZAR_NODE_TOKEN',token)
    for url in ['http://127.0.0.1:9999','http://cloud.example','https://secret@cloud.example','https://cloud.example/x','https://cloud.example/?secret=bad']:
        monkeypatch.setenv('ZAR_CLOUD_URL',url)
        assert node_inference.transport()[2]=='DEGRADED'
    monkeypatch.setenv('ZAR_CLOUD_URL','https://cloud.example')
    def failure(*args,**kwargs): raise requests.ConnectionError('private exception '+token)
    monkeypatch.setattr(node_inference.requests,'post',failure)
    answer = node_inference.respond('¿En qué nodo te estás ejecutando y qué capacidades locales tienes?',{})
    assert 'OFFLINE' in answer and token not in answer and 'private exception' not in answer
    assert node_inference.status()['model'] is None


def test_node_success_uses_outbound_tls_and_actual_model(local,monkeypatch):
    token=secrets.token_urlsafe(32); monkeypatch.setenv('ZAR_NODE_TOKEN',token)
    monkeypatch.setenv('ZAR_CLOUD_URL','https://cloud.example')
    class Response:
        status_code=200
        def json(self):return {'state':'ONLINE','text':'Respuesta del proveedor '+token,'model':'server-selected-model','provider':'gemini'}
    def send(url,**kwargs):
        assert url=='https://cloud.example/v1/nodes/inference'
        assert kwargs['allow_redirects'] is False and 'verify' not in kwargs
        assert kwargs['headers']['Authorization']=='Bearer '+token
        assert set(kwargs['json'])=={'request_id','heartbeat','prompt'}
        assert kwargs['json']['heartbeat']['id']==local.identity()['id']
        return Response()
    monkeypatch.setattr(node_inference.requests,'post',send)
    answer = node_inference.respond('¿En qué nodo estás ejecutándote?',{})
    assert 'server-selected-model' in answer and token not in answer and '[REDACTED]' in answer
    assert node_inference.status()['state']=='ONLINE'


@pytest.fixture
def gateway(tmp_path,monkeypatch):
    nid,token = str(uuid.uuid4()),secrets.token_urlsafe(32)
    app=create_app(tmp_path/'cloud',nid,token,'harness-admin')
    store=app.extensions['node_coordinator']
    with store.connect() as con:
        con.execute('UPDATE distributed_nodes SET inference_allowed=1,payload=? WHERE id=?',(json.dumps({'capabilities':['python'],'resources':{'os':'Darwin','architecture':'x86_64'}}),nid))
    monkeypatch.setenv('ZAR_NODE_INFERENCE_ENABLED','1')
    from app import agent,smart_router
    monkeypatch.setattr(smart_router,'choose_brain',lambda *args:smart_router.BrainRoute('economy','gemini','configured-model','test'))
    monkeypatch.setattr(smart_router,'brain_models',lambda:{'economy':{'model':'configured-model'},'balanced':{'model':'configured-balanced'}})
    monkeypatch.setattr(agent,'_api_profiles',lambda *args:[('https://provider.example/v1','private-test-provider-key','configured-model','Gemini Smart Router')])
    return app,store,app.test_client(),nid,token


def call(client,nid,token,**extras):
    body={'request_id':str(uuid.uuid4()),'heartbeat':{'id':nid},'prompt':'Una pregunta inocua.'}
    body.update(extras)
    return client.post('/v1/nodes/inference',headers={'Authorization':'Bearer '+token},json=body)


def test_gateway_auth_permission_revocation_no_provider_call(gateway,monkeypatch):
    app,store,client,nid,token=gateway
    assert call(client,nid,'x'*43).status_code==401
    with store.connect() as con: con.execute('UPDATE distributed_nodes SET inference_allowed=0 WHERE id=?',(nid,))
    assert call(client,nid,token).status_code==403
    with store.connect() as con: con.execute('UPDATE distributed_nodes SET inference_allowed=1 WHERE id=?',(nid,))
    monkeypatch.setenv('ZAR_NODE_INFERENCE_ENABLED','0')
    assert call(client,nid,token).status_code==503
    store.control(nid,'revoke')
    assert call(client,nid,token).status_code==403


def test_gateway_real_dispatch_contract_scrubbing_cache_rate_limit(gateway,monkeypatch):
    app,store,client,nid,token=gateway
    calls=[]
    class Response:
        status_code=200
        def json(self):return {'choices':[{'message':{'content':'Answer private-test-provider-key '+token}}]}
    def send(url,**kwargs):
        calls.append(kwargs)
        assert url=='https://provider.example/v1/chat/completions'
        payload=kwargs['json']
        assert payload['model']=='configured-model' and payload['max_tokens']==512
        assert 'tools' not in payload and 'tool_choice' not in payload
        assert 'usuario se ejecuta en el nodo' in payload['messages'][0]['content']
        assert kwargs['allow_redirects'] is False and 'verify' not in kwargs
        return Response()
    monkeypatch.setattr('app.inference_gateway.requests.post',send)
    request_id=str(uuid.uuid4())
    response=call(client,nid,token,request_id=request_id)
    assert response.status_code==200 and response.json['model']=='configured-model'
    assert 'private-test-provider-key' not in response.get_data(as_text=True) and token not in response.get_data(as_text=True)
    assert call(client,nid,token,request_id=request_id).json==response.json and len(calls)==1
    assert call(client,nid,token,request_id=request_id,prompt='Changed').status_code==409
    for _ in range(4): assert call(client,nid,token).status_code==200
    assert call(client,nid,token).status_code==429
    with store.connect() as con:
        saved=con.execute('SELECT result FROM node_inference_calls WHERE id=?',(request_id,)).fetchone()[0]
    assert token not in saved and 'private-test-provider-key' not in saved


def test_gateway_schema_provider_failure_and_no_tools(gateway,monkeypatch):
    app,store,client,nid,token=gateway
    for fields in ({'model':'arbitrary-model'},{'tools':[]},{'prompt':'x'*6001},{'prompt':token}):
        assert call(client,nid,token,**fields).status_code==400
    class Response:
        status_code=200
        def json(self):return {'choices':[{'message':{'tool_calls':[{'name':'danger'}],'content':'ignore'}}]}
    monkeypatch.setattr('app.inference_gateway.requests.post',lambda *args,**kwargs:Response())
    assert call(client,nid,token).json=={'state':'DEGRADED','code':'PROVIDER_UNAVAILABLE'}


def test_production_semantic_routing_is_preserved(monkeypatch):
    from app import agent
    monkeypatch.delenv('ZAR_NODE_CHAT',raising=False)
    monkeypatch.setattr(agent,'load',lambda:{'provider':'auto'})
    monkeypatch.setattr(agent,'smart_agent',lambda message,cfg:'existing production route')
    assert agent.semantic_respond('Hello')=='existing production route'


def test_gateway_preserves_manual_cloud_openrouter(gateway,monkeypatch):
    app,store,client,nid,token=gateway
    from app import agent,config
    monkeypatch.setattr(config,'load',lambda:{'provider':'openrouter'})
    def profiles(cfg,route=None):
        assert cfg['provider']=='openrouter' and route is None
        return [('https://openrouter.example/api/v1','test-private-openrouter-key','operator-selected-model','OpenRouter')]
    monkeypatch.setattr(agent,'_api_profiles',profiles)
    class Response:
        status_code=200
        def json(self):return {'choices':[{'message':{'content':'A safe answer'}}]}
    monkeypatch.setattr('app.inference_gateway.requests.post',lambda *args,**kwargs:Response())
    response=call(client,nid,token)
    assert response.status_code==200 and response.json['provider']=='openrouter'
    assert response.json['model']=='operator-selected-model'


def test_gateway_revocation_while_provider_runs(gateway,monkeypatch):
    app,store,client,nid,token=gateway
    class Response:
        status_code=200
        def json(self):return {'choices':[{'message':{'content':'This must not be delivered'}}]}
    def send(*args,**kwargs):
        store.control(nid,'revoke')
        return Response()
    monkeypatch.setattr('app.inference_gateway.requests.post',send)
    response=call(client,nid,token)
    assert response.status_code==503 and 'This must not be delivered' not in response.get_data(as_text=True)
    with store.connect() as con:
        assert con.execute('SELECT state,result FROM node_inference_calls').fetchone()['result'] is None


def test_standard_respond_also_uses_node_gateway(local):
    from app import agent
    answer=agent.respond('¿En qué nodo estás ejecutándote?')
    assert local.identity()['id'] in answer and 'DEGRADED' in answer


def test_production_respond_is_preserved(monkeypatch):
    from app import agent
    monkeypatch.delenv('ZAR_NODE_CHAT',raising=False)
    monkeypatch.setattr(agent,'load',lambda:{'provider':'auto'})
    monkeypatch.setattr(agent,'smart_agent',lambda message,cfg:'existing production route')
    assert agent.respond('Di únicamente conexión correcta.')=='existing production route'


def test_node_engine_test_does_not_claim_success_when_degraded(local,monkeypatch):
    monkeypatch.setattr('app.smart_router.local_available',lambda cfg:False)
    from app.main import app
    client=app.test_client()
    response=client.post('/api/test')
    assert response.status_code==200
    assert response.json['ok'] is False and response.json['state']=='DEGRADED'
    assert response.json['model'] is None and 'DEGRADED' in response.json['reply']
    router=client.get('/api/ai/router').json
    assert router['gateway']['state']=='DEGRADED'


def test_production_engine_test_response_is_preserved(monkeypatch):
    from app.main import app
    monkeypatch.delenv('ZAR_NODE_CHAT',raising=False)
    monkeypatch.setattr('app.main.respond',lambda *args:'Conexión correcta.')
    response=app.test_client().post('/api/test')
    assert response.json=={'ok':True,'reply':'Conexión correcta.'}


def test_bearer_auth_never_borrows_netrc_credentials(monkeypatch):
    from app.scoped_http import BearerAuth
    monkeypatch.setattr('requests.sessions.get_netrc_auth',lambda *args:pytest.fail('Ambient credentials must not be read'))
    session=requests.Session()
    request=session.prepare_request(requests.Request('POST','https://cloud.example',auth=BearerAuth('isolated-test-token')))
    assert request.headers['Authorization']=='Bearer isolated-test-token'
    assert 'isolated-test-token' not in repr(BearerAuth('isolated-test-token'))
    session.close()
