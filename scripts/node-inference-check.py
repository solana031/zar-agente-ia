"""Real localhost chat smoke check. No mocked responses or provider credentials."""
import json
from pathlib import Path
import time
import requests

base='http://127.0.0.1:8765'
session=requests.Session()
health=session.get(base+'/health',timeout=5); health.raise_for_status()
response=session.post(base+'/api/chat',json={'message':'¿En qué nodo te estás ejecutando y qué capacidades locales tienes?'},timeout=5)
assert response.status_code==202, 'Local chat did not accept the request'
job_id=response.json()['job_id']
for _ in range(120):
    response=session.get(base+'/api/jobs/'+job_id,timeout=5); response.raise_for_status()
    job=response.json()
    if job['status'] in {'done','error'}: break
    time.sleep(.25)
else: raise RuntimeError('Local chat did not finish within the check window')
assert job['status']=='done', 'Local chat returned an error'
reply=job.get('reply','')
assert 'ZAR-NODE-02-MAC' in reply and 'python' in reply
assert 'Error de Zar:' not in reply and 'Smart Router no encuentra' not in reply
response=session.get(base+'/api/node-inference/status',timeout=5); response.raise_for_status()
status=response.json()
assert status['node']['id']=='d8ee5a76-2a0b-43f8-aca5-a09b1d840b14'
assert status['inference']['state'] in {'ONLINE','DEGRADED','OFFLINE'}
output={'test':'real-localhost-chat-no-mocks','ok':True,'reply':reply,
        'node_id':status['node']['id'],'capabilities':status['node']['capabilities'],
        'inference':status['inference'],'version':health.json()['version']}
if status['inference']['state']!='ONLINE':
    engine=session.post(base+'/api/test',json={},timeout=5); engine.raise_for_status()
    engine_status=engine.json()
    assert engine_status['ok'] is False and engine_status['state'] in {'DEGRADED','OFFLINE'}
    assert 'Smart Router no encuentra' not in engine_status['reply']
    output['engine_test']={'ok':engine_status['ok'],'state':engine_status['state'],'model':engine_status['model']}
directory=Path(__file__).resolve().parents[1]/'.local/test-results'
directory.mkdir(parents=True,exist_ok=True)
(directory/'node-inference-real.json').write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(output,ensure_ascii=False))
session.close()
