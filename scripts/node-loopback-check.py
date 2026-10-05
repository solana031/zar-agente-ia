"""Real outgoing HTTP integration with isolated storage and ephemeral test keys."""
import json
import os
from pathlib import Path
import secrets
import sys
import tempfile
import threading
from urllib.parse import urlparse
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
os.environ['ZAR_DATA_DIR'] = str(ROOT/'.local/data')
from app.node_worker import Worker
from app.node_coordinator import create_app
from werkzeug.serving import make_server, WSGIRequestHandler
import requests

class QuietHandler(WSGIRequestHandler):
    def log(self,*args,**kwargs): pass

with tempfile.TemporaryDirectory(prefix='zar-node-protocol-') as directory:
    root = Path(directory)
    worker = Worker(root/'worker'); identity = worker.identity()
    node_key,admin_key = secrets.token_urlsafe(32),secrets.token_urlsafe(32)
    app = create_app(root/'cloud',identity['id'],node_key,admin_key)
    server = make_server('127.0.0.1',0,app,request_handler=QuietHandler)
    thread = threading.Thread(target=server.serve_forever,daemon=True); thread.start()
    base = 'http://127.0.0.1:'+str(server.server_port)
    os.environ.update(ZAR_CLOUD_URL=base,ZAR_NODE_TOKEN=node_key)
    admin = requests.Session(); admin.headers.update(Authorization='Bearer '+admin_key)
    try:
        response = admin.get(base+'/api/nodes',timeout=5); response.raise_for_status()
        admin.headers['X-ZAR-Nodes-CSRF'] = response.json()['csrf']
        assert worker.sync()['state']=='ONLINE'
        job = admin.post(base+'/api/node-jobs',json={'kind':'node-info'},timeout=5).json()
        worker.sync()
        assert admin.get(base+'/api/nodes',timeout=5).json()['nodes'][0]['state']=='BUSY'
        assert worker.run_one(); worker.sync()
        stored = admin.get(base+'/api/node-jobs/'+job['id'],timeout=5).json()
        assert stored['state']=='SUCCEEDED'
        result = stored['report']['result']
        assert set(result)=={'hostname','architecture','python','node','timestamp'}
        restarted = Worker(root/'worker'); restarted.recover(); restarted.sync()
        assert restarted.identity()==identity and restarted.get(job['id'])['state']=='SUCCEEDED'
        paused = base+'/api/nodes/'+identity['id']+'/pause'
        admin.post(paused,timeout=5).raise_for_status(); assert restarted.sync()['state']=='PAUSED'
        admin.post(paused.removesuffix('pause')+'resume',timeout=5).raise_for_status(); restarted.sync()
        cancel = admin.post(base+'/api/node-jobs',json={'kind':'diagnostics'},timeout=5).json()
        restarted.sync(); admin.post(base+'/api/node-jobs/'+cancel['id']+'/cancel',timeout=5).raise_for_status()
        restarted.sync(); assert restarted.get(cancel['id'])['state']=='CANCELLED'
        admin.post(paused.removesuffix('pause')+'revoke',timeout=5).raise_for_status()
        assert restarted.sync()['state']=='AUTH_REJECTED'
        output = {'test':'isolated-real-loopback-http','ok':True,'result':result,
                  'checks':['heartbeat','claim','BUSY','progress','result','ONLINE','restart','pause','resume','cancel','revocation']}
        report = ROOT/'.local/test-results'; report.mkdir(parents=True,exist_ok=True)
        (report/'node-loopback.json').write_text(json.dumps(output,indent=2)+'\n')
        print(json.dumps(output))
    finally:
        server.shutdown(); thread.join(timeout=5); admin.close()
