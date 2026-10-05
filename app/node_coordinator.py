"""Persistent outbound-poll coordinator. Provision only through trusted Cloud CLI."""
from contextlib import contextmanager
import hashlib
import json
import math
import os
from pathlib import Path
import secrets
import sqlite3
import time
import uuid

from flask import Blueprint, Flask, abort, jsonify, request, session
from .node_worker import HANDLERS
from .node_scheduling import choose_node

TERMINAL = {'SUCCEEDED', 'FAILED', 'CANCELLED', 'TIMED_OUT', 'INTERRUPTED'}
CAPABILITIES = {'python', 'node', 'git', 'filesystem', 'browser', 'workspace-processing',
                'media-processing', 'dramaclaw-local'}


def token_hash(token):
    if not isinstance(token, str) or not 32 <= len(token) <= 256:
        raise ValueError('Node token must contain at least 256 bits of generated entropy')
    return hashlib.sha256(token.encode()).hexdigest()


class Coordinator:
    def __init__(self, directory=None):
        root = Path(directory or Path(os.environ.get('ZAR_DATA_DIR', '/data')) / 'coordinator')
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.db = root / 'coordinator.sqlite3'
        with self.connect() as con:
            con.executescript('''
                CREATE TABLE IF NOT EXISTS distributed_nodes (
                    id TEXT PRIMARY KEY, name TEXT, token_hash TEXT UNIQUE,
                    revoked INTEGER DEFAULT 0, paused INTEGER DEFAULT 0,
                    seen REAL DEFAULT 0, payload TEXT DEFAULT '{}');
                CREATE TABLE IF NOT EXISTS distributed_jobs (
                    id TEXT PRIMARY KEY, node TEXT, body TEXT, state TEXT,
                    report TEXT, priority INTEGER, created REAL, deadline REAL,
                    assigned REAL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS distributed_events (
                    id INTEGER PRIMARY KEY, job TEXT, state TEXT, timestamp REAL);
            ''')
        from .inference_gateway import schema
        with self.connect() as con:
            schema(con)
        os.chmod(self.db, 0o600)

    @contextmanager
    def connect(self):
        con = sqlite3.connect(self.db, timeout=10)
        con.row_factory = sqlite3.Row
        try:
            with con:
                yield con
        finally:
            con.close()

    def provision(self, nid, name, digest):
        uuid.UUID(nid)
        if len(name) > 80 or len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
            raise ValueError('Invalid enrollment descriptor')
        with self.connect() as con:
            row = con.execute('SELECT * FROM distributed_nodes WHERE id=?', (nid,)).fetchone()
            if row:
                if row['revoked'] or not secrets.compare_digest(row['token_hash'], digest):
                    raise ValueError('Existing node cannot be silently re-enrolled or rotated')
            else:
                con.execute('INSERT INTO distributed_nodes (id,name,token_hash) VALUES (?,?,?)', (nid, name, digest))

    def authenticate(self, nid, token):
        try:
            if not isinstance(nid,str) or str(uuid.UUID(nid))!=nid:
                raise ValueError('Invalid node identity')
            digest = token_hash(token)
        except ValueError:
            abort(401)
        with self.connect() as con:
            row = con.execute('SELECT * FROM distributed_nodes WHERE id=?', (nid,)).fetchone()
        if not row or not secrets.compare_digest(row['token_hash'], digest):
            abort(401)
        if row['revoked']:
            abort(403)
        return row

    def expire(self, con, now):
        rows = con.execute("SELECT id FROM distributed_jobs WHERE state IN ('QUEUED','ASSIGNED','RUNNING') AND deadline<=?", (now,)).fetchall()
        for row in rows:
            self.transition(con, row['id'], 'TIMED_OUT')
        # After a long disconnection, record interruption instead of repeating an action.
        for row in con.execute("SELECT j.id FROM distributed_jobs j JOIN distributed_nodes n ON n.id=j.node WHERE j.state IN ('ASSIGNED','RUNNING') AND n.seen>0 AND n.seen<?", (now-60,)).fetchall():
            self.transition(con, row['id'], 'INTERRUPTED')

    def transition(self, con, jid, state, report=None):
        con.execute('UPDATE distributed_jobs SET state=?,report=COALESCE(?,report) WHERE id=?',
                    (state, json.dumps(report) if report is not None else None, jid))
        con.execute('INSERT INTO distributed_events (job,state,timestamp) VALUES (?,?,?)', (jid, state, time.time()))

    def public_nodes(self, con):
        now = time.time()
        self.expire(con, now)
        nodes = []
        for row in con.execute('SELECT * FROM distributed_nodes ORDER BY name'):
            running = con.execute("SELECT * FROM distributed_jobs WHERE node=? AND state IN ('ASSIGNED','RUNNING') ORDER BY created DESC LIMIT 1", (row['id'],)).fetchone()
            history = con.execute("SELECT state,report FROM distributed_jobs WHERE node=? AND state IN ('SUCCEEDED','FAILED','INTERRUPTED','TIMED_OUT') ORDER BY created DESC LIMIT 10", (row['id'],)).fetchall()
            payload = json.loads(row['payload'])
            state = ('REVOKED' if row['revoked'] else 'OFFLINE' if now-row['seen'] >= 30 else
                     'PAUSED' if row['paused'] else 'BUSY' if running else 'ONLINE')
            last_result = next((json.loads(r['report'] or '{}').get('result') for r in history if r['state']=='SUCCEEDED'), None)
            last_error = next(((json.loads(r['report'] or '{}').get('result') or {}).get('error', r['state']) for r in history if r['state']!='SUCCEEDED'), None)
            current = None if not running else {'id': running['id'], 'kind': json.loads(running['body'])['kind'], 'state': running['state'], 'progress': json.loads(running['report'] or '{}').get('progress', 0)}
            nodes.append({**payload, 'id': row['id'], 'name': row['name'], 'state': state,
                          'last_seen': row['seen'], 'active_jobs': int(bool(running)),
                          'jobs': con.execute('SELECT COUNT(*) FROM distributed_jobs WHERE node=?', (row['id'],)).fetchone()[0],
                          'current_job': current, 'last_result': last_result, 'last_error': last_error})
        return nodes

    def submit(self, body):
        if not isinstance(body, dict) or body.get('kind') not in HANDLERS or not isinstance(body.get('payload', {}), dict):
            raise ValueError('Job not allowed')
        if len(json.dumps(body)) > 8192 or set(body) - {'kind','payload','priority','timeout','max_cost_per_job'}:
            raise ValueError('Invalid job schema')
        kind, payload = body['kind'], body.get('payload', {})
        if kind in {'node-info', 'diagnostics'} and payload:
            raise ValueError('This action has no arguments')
        if kind in {'file-sha256', 'workspace-summary'} and (set(payload) != {'path'} or not isinstance(payload['path'], str)):
            raise ValueError('Only an input file path is accepted')
        cost = body.get('max_cost_per_job')
        if cost is not None and (isinstance(cost, bool) or not isinstance(cost, (int,float)) or not math.isfinite(cost) or cost<0):
            raise ValueError('Invalid cost limit')
        job = {'id': str(uuid.uuid4()), 'kind': kind, 'payload': payload,
               'priority': max(-100,min(100,int(body.get('priority',0)))), 'max_cost_per_job': cost}
        timeout = max(5,min(600,int(body.get('timeout',120))))
        now = time.time()
        job['deadline'] = now + timeout
        with self.connect() as con:
            con.execute('INSERT INTO distributed_jobs VALUES (?,NULL,?,?,NULL,?,?,?,0)',
                        (job['id'],json.dumps(job),'QUEUED',job['priority'],now,job['deadline']))
        return job

    def control(self, nid, action):
        if action not in {'pause','resume','revoke'}:
            abort(400)
        with self.connect() as con:
            row = con.execute('SELECT revoked FROM distributed_nodes WHERE id=?', (nid,)).fetchone()
            if not row:
                abort(404)
            if row['revoked'] and action != 'revoke':
                abort(409)
            if action == 'revoke':
                con.execute('UPDATE distributed_nodes SET revoked=1,paused=1 WHERE id=?', (nid,))
                for job in con.execute("SELECT id FROM distributed_jobs WHERE node=? AND state IN ('ASSIGNED','RUNNING')", (nid,)).fetchall():
                    self.transition(con, job['id'], 'CANCELLED')
            else:
                con.execute('UPDATE distributed_nodes SET paused=? WHERE id=?', (int(action=='pause'),nid))

    def poll(self, nid, body, enroll=False):
        heartbeat = body.get('heartbeat', {})
        if not isinstance(heartbeat,dict) or not isinstance(heartbeat.get('capabilities',[]),list):
            abort(400)
        resource = heartbeat.get('resources') or {}
        cpu = resource.get('cpu_count',1)
        ram = resource.get('ram_bytes')
        if not isinstance(cpu,int) or not 1<=cpu<=4096 or (ram is not None and (not isinstance(ram,int) or ram<0)):
            abort(400)
        load = resource.get('load',[0])
        if not isinstance(load,list) or len(load)>3 or any(not isinstance(x,(int,float)) or not math.isfinite(x) or x<0 for x in load):
            abort(400)
        caps = sorted(set(c for c in heartbeat.get('capabilities',[]) if isinstance(c,str) and c in CAPABILITIES))
        payload = {'capabilities': caps, 'resources': {'os':str(resource.get('os',''))[:64], 'architecture':str(resource.get('architecture',''))[:64], 'cpu_count':cpu,'ram_bytes':ram,'load':load},
                   'version': str(heartbeat.get('version',''))[:32], 'worker_version':str(heartbeat.get('worker_version',''))[:32],
                   'uptime':max(0,min(315360000,float(heartbeat.get('uptime',0)))), 'max_concurrency':1,
                   'cost': {'currency':'EUR','per_job':None}}
        ack, cancel, jobs = [], [], []
        with self.connect() as con:
            con.execute('BEGIN IMMEDIATE')
            enrolled = con.execute('SELECT revoked FROM distributed_nodes WHERE id=?',(nid,)).fetchone()
            if not enrolled or enrolled['revoked']:
                abort(403)
            self.expire(con,time.time())
            con.execute('UPDATE distributed_nodes SET seen=?,payload=? WHERE id=?', (time.time(),json.dumps(payload),nid))
            self.expire(con,time.time())
            reports = body.get('reports',[])
            if not isinstance(reports,list) or len(reports)>100:
                abort(400)
            for report in reports:
                if not isinstance(report,dict):
                    abort(400)
                jid, state = report.get('id'), report.get('state')
                row = con.execute('SELECT * FROM distributed_jobs WHERE id=? AND node=?', (jid,nid)).fetchone()
                if not row:
                    continue
                if row['state'] in {'CANCELLED','TIMED_OUT','INTERRUPTED'}:
                    cancel.append(jid)
                elif row['state'] == 'RUNNING' and state in {'RUNNING'} | TERMINAL:
                    progress = report.get('progress',0)
                    if not isinstance(progress,int) or not 0<=progress<=100:
                        abort(400)
                    result = report.get('result')
                    if result is not None and (not isinstance(result,dict) or len(json.dumps(result))>16384):
                        abort(400)
                    clean = {'id':jid,'state':state,'progress':progress,'result':result}
                    self.transition(con,jid,state,clean)
                if state in TERMINAL:
                    ack.append(jid)
            cancel.extend(r['id'] for r in con.execute("SELECT id FROM distributed_jobs WHERE node=? AND state IN ('CANCELLED','TIMED_OUT','INTERRUPTED')", (nid,)))
            nodes = self.public_nodes(con)
            node = next(n for n in nodes if n['id']==nid)
            if not enroll and node['state']=='ONLINE':
                candidates = [n for n in nodes if n['state']=='ONLINE']
                for row in con.execute("SELECT * FROM distributed_jobs WHERE state='QUEUED' ORDER BY priority DESC,created LIMIT 100").fetchall():
                    job = json.loads(row['body'])
                    if choose_node(candidates,HANDLERS[job['kind']],time.time(),job.get('max_cost_per_job'))==nid:
                        con.execute("UPDATE distributed_jobs SET node=?,state='ASSIGNED',assigned=? WHERE id=?", (nid,time.time(),row['id']))
                        break
            if node['state'] != 'PAUSED':
                jobs = [json.loads(r['body']) for r in con.execute("SELECT body FROM distributed_jobs WHERE node=? AND state='ASSIGNED'", (nid,))]
        return {'ack':ack,'cancel':sorted(set(cancel)),'jobs':jobs,'paused':node['state']=='PAUSED','state':node['state']}


def blueprint(store, admin_check):
    bp = Blueprint('distributed_nodes',__name__)

    @bp.before_request
    def limit_request():
        if request.content_length and request.content_length>256*1024:
            abort(413)

    def admin(write=False):
        if not admin_check():
            abort(403)
        if write:
            supplied = request.headers.get('X-ZAR-Nodes-CSRF','')
            if not secrets.compare_digest(supplied,session.get('nodes_csrf','')) or not supplied:
                abort(403)
            origin = request.headers.get('Origin')
            if origin and origin != request.host_url.rstrip('/'):
                abort(403)

    def node_auth(body):
        if not isinstance(body,dict) or not isinstance(body.get('heartbeat'),dict):
            abort(400)
        nid = body['heartbeat'].get('id')
        header = request.headers.get('Authorization','')
        if not header.startswith('Bearer '):
            abort(401)
        token = header[7:]
        store.authenticate(nid,token)
        return nid

    @bp.get('/v1/nodes/health')
    def health():
        return jsonify(ok=True,service='zar-node-coordinator',protocol=1)

    @bp.post('/v1/nodes/enroll')
    @bp.post('/v1/nodes/poll')
    def poll():
        if request.content_length is None or request.content_length>256*1024:
            abort(413)
        body = request.get_json()
        nid = node_auth(body)
        try:
            return jsonify(store.poll(nid,body,enroll=request.path.endswith('/enroll')))
        except (TypeError,ValueError,OverflowError):
            abort(400)

    @bp.post('/v1/nodes/inference')
    def inference():
        body = request.get_json()
        nid = node_auth(body)
        from .inference_gateway import infer
        return infer(store,nid,body,request.headers['Authorization'][7:])

    @bp.get('/api/node-inference/status')
    def local_inference_status():
        from . import node_inference
        if not node_inference.enabled():
            abort(404)
        admin()
        return jsonify(node=node_inference.context(),inference=node_inference.status())

    @bp.post('/v1/jobs/<jid>/claim')
    def claim(jid):
        body = request.get_json()
        nid = node_auth(body)
        with store.connect() as con:
            con.execute('BEGIN IMMEDIATE')
            store.expire(con,time.time())
            node = con.execute('SELECT paused FROM distributed_nodes WHERE id=?',(nid,)).fetchone()
            row = con.execute('SELECT state FROM distributed_jobs WHERE id=? AND node=?',(jid,nid)).fetchone()
            if not row or row['state'] not in {'ASSIGNED','RUNNING'} or node['paused']:
                abort(409)
            if row['state']=='ASSIGNED':
                store.transition(con,jid,'RUNNING',{'progress':1})
        return jsonify(ok=True)

    @bp.get('/api/nodes')
    def nodes():
        admin()
        session.setdefault('nodes_csrf',secrets.token_urlsafe(24))
        with store.connect() as con:
            result = store.public_nodes(con)
        return jsonify(nodes=result,csrf=session['nodes_csrf'])

    @bp.post('/api/nodes/<nid>/<action>')
    def control(nid,action):
        admin(True)
        store.control(nid,action)
        return jsonify(ok=True)

    @bp.post('/api/node-jobs')
    def submit():
        admin(True)
        try:
            job = store.submit(request.get_json())
        except (ValueError,TypeError,OverflowError):
            abort(400)
        return jsonify(job),201

    @bp.get('/api/node-jobs/<jid>')
    def get(jid):
        admin()
        with store.connect() as con:
            store.expire(con,time.time())
            row = con.execute('SELECT * FROM distributed_jobs WHERE id=?',(jid,)).fetchone()
        if not row:
            abort(404)
        result = dict(row)
        for key in ('body','report'):
            result[key] = json.loads(result[key]) if result[key] else None
        return jsonify(result)

    @bp.post('/api/node-jobs/<jid>/cancel')
    def cancel(jid):
        admin(True)
        with store.connect() as con:
            row = con.execute('SELECT state FROM distributed_jobs WHERE id=?',(jid,)).fetchone()
            if not row:
                abort(404)
            if row['state'] not in TERMINAL:
                store.transition(con,jid,'CANCELLED')
        return jsonify(ok=True)
    return bp


def production_admin():
    # Explicit verified Google-email allowlist; never use a password or a Railway credential.
    allowed = {email.strip().lower() for email in os.environ.get('ZAR_NODES_ADMIN_EMAILS','').split(',') if email.strip()}
    email = str(session.get('google_account_email','')).lower()
    local = (os.environ.get('ZAR_NODES_LOCAL_ADMIN')=='1' and not os.environ.get('RAILWAY_ENVIRONMENT')
             and request.remote_addr in {'127.0.0.1','::1'}
             and request.host.split(':')[0] in {'127.0.0.1','localhost'})
    return local or bool(email and email in allowed)


def register(app):
    store = Coordinator()
    app.extensions['node_coordinator'] = store
    app.register_blueprint(blueprint(store,production_admin))
    return store


def create_app(directory=None,node_id=None,node_token=None,admin_token=None,enrollment=None):
    """Isolated harness only. Production has no shared administrator bearer key."""
    app = Flask(__name__)
    app.secret_key = secrets.token_hex(32)
    app.config['MAX_CONTENT_LENGTH'] = 256*1024
    store = Coordinator(directory)
    registry = enrollment or ({node_id:node_token} if node_id and node_token else {})
    if not admin_token or any(token==admin_token for token in registry.values()) or len(set(registry.values()))!=len(registry):
        raise ValueError('Distinct node and harness admin credentials required')
    for nid,token in registry.items():
        store.provision(nid,'ZAR-'+nid[:8],token_hash(token))
    app.extensions['node_coordinator'] = store
    app.register_blueprint(blueprint(store,lambda: secrets.compare_digest(request.headers.get('Authorization',''),'Bearer '+admin_token)))
    return app
