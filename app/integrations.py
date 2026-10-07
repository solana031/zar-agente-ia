"""Evidence-based integration inventory and administrator-only local controls."""
import json
import os
from pathlib import Path
import secrets
import shutil
import time
import re
import requests

from flask import Blueprint, abort, jsonify, request, session
from . import automation_control as control, automation_sandbox as sandbox
from . import coding_capability, conway_adapter, jev_decision, media_company, media_narrator

ROOT = Path(__file__).resolve().parents[1]


def inventory(store=None):
    version = (ROOT / 'VERSION').read_text().strip()
    p = control.policy()
    drama = media_company.status()
    jev = jev_decision.status()
    conway = conway_adapter.status()
    coding = coding_capability.status()
    host = os.environ.get('ZAR_NODE_NAME') or ('ZAR Cloud' if os.environ.get('RAILWAY_ENVIRONMENT') else 'local')

    def card(name, state, version=None, capabilities=(), missing=(), heartbeat=None, node=host, **extra):
        return {'name': name, 'state': state, 'version': version, 'node': node,
                'capabilities': list(capabilities), 'last_heartbeat': heartbeat,
                'estimated_cost_eur': None, 'missing': list(missing), **extra}

    cards = [
        card('DramaClaw', 'DEGRADED' if drama['ready'] else 'OFFLINE' if drama['dramaclaw_direct_configured'] else 'NOT_CONFIGURED',
             capabilities=['official REST pipeline', 'MP4 preview'], missing=['models/channels verified', 'bounded provider cost', 'complete generation not verified'],
             probe='dramaclaw', generation_verified=False, voice=media_narrator.status()),
        card('Jev', jev['state'], jev['model'], ['typed decisions', 'fallback', 'circuit breaker'],
             jev['missing'] + ['bounded provider cost'], jev['last_heartbeat'], probe='jev'),
        card('Conway Automaton', conway['state'], conway['version'], ['official policy engine', 'isolated version probe'],
             conway['missing'], mode=p['conway_mode'], probe='conway', local_controls_allowed=not bool(os.environ.get('RAILWAY_ENVIRONMENT'))),
        card('Coding Agent', coding['state'], coding['version'], capabilities=['real Codex CLI', 'isolated worktree', 'OSS only', 'diff'],
             missing=coding['missing'], mode=p['coding_mode'], probe='coding', model_execution_verified=False, local_controls_allowed=not bool(os.environ.get('RAILWAY_ENVIRONMENT'))),
    ]
    for card_data in cards:
        proof=control.last_probe(card_data['probe'])
        card_data['last_heartbeat']=card_data['last_heartbeat'] or proof.get('last_heartbeat')
        card_data['probe_verified']=bool(proof)
    drama_source=ROOT/'.local/upstream/dramaclaw/pyproject.toml'
    if drama_source.is_file() and not os.environ.get('RAILWAY_ENVIRONMENT'):
        import tomllib
        try:cards[0]['version']=tomllib.loads(drama_source.read_text())['project']['version']
        except (KeyError,ValueError):pass
    nodes = []
    if store:
        # Inventory does not expire jobs or change enrollments.
        with store.connect() as con:
            for row in con.execute('SELECT id,name,seen,paused,revoked,payload FROM distributed_nodes'):
                payload = json.loads(row['payload'])
                state = 'DISABLED' if row['paused'] or row['revoked'] else 'ONLINE' if 0 <= time.time()-row['seen'] < 30 else 'OFFLINE'
                nodes.append(card(row['name'], state, payload.get('version'), payload.get('capabilities', []),
                                  heartbeat=row['seen'] or None, node=row['id'], optional_capabilities=payload.get('optional_capabilities',{})))
    # The local persisted heartbeat is evidence, not an invented remote node.
    beat={}
    worker_db = Path(os.environ.get('ZAR_NODE_DIR', ROOT / '.local/node')) / 'worker.sqlite3'
    if worker_db.is_file() and not os.environ.get('RAILWAY_ENVIRONMENT'):
        import sqlite3
        try:
            with sqlite3.connect(f'file:{worker_db}?mode=ro', uri=True) as con:
                row = con.execute('SELECT payload FROM heartbeat WHERE id=1').fetchone()
            if row:
                beat = json.loads(row[0])
                if not any(n['node'] == beat.get('id') for n in nodes):
                    node_state='DISABLED' if beat.get('cloud_state') in {'PAUSED','AUTH_REJECTED'} else 'ONLINE' if 0 <= time.time()-beat.get('timestamp', 0) < 15 else 'OFFLINE'
                    nodes.append(card(beat.get('name', 'NODE-02'), node_state,
                                      beat.get('version'), beat.get('capabilities', []), heartbeat=beat.get('timestamp'), node=beat.get('id')))
        except (sqlite3.Error, ValueError):
            pass
    for suffix in ['NODE-01', 'NODE-02']:
        found = next((n for n in nodes if suffix in n['name'].upper()), None)
        cards.append({**found, 'name': suffix, 'probe':'node'} if found else card(suffix, 'NOT_CONFIGURED', missing=['verified enrollment/heartbeat'], node=None))
    local_cloud = bool(os.environ.get('RAILWAY_ENVIRONMENT'))
    remote=next((n for n in nodes if 'NODE-02' in n['name'].upper()),None)
    if local_cloud and remote:
        for position,name in [(2,'conway-runtime'),(3,'coding-agent')]:
            observation=remote.get('optional_capabilities',{}).get(name)
            if observation:
                cards[position].update(node=remote['node'],state=observation['state'] if remote['state']=='ONLINE' else remote['state'],
                                       version=observation['version'],last_heartbeat=remote['last_heartbeat'],
                                       mode=observation['mode'] or ('OFF' if position==2 else 'DISABLED'),probe='node',
                                       missing=['local task approval','runtime execution not verified'] if position==3 else ['free inference/tool mediation for EXECUTE'],
                                       local_controls_allowed=False,reported_by_node=True)
    proof=control.last_probe('cloud')
    fresh_poll=beat.get('cloud_state')=='ONLINE' and 0 <= time.time()-beat.get('timestamp',0) < 15
    fresh_probe=proof.get('state')=='ONLINE' and 0 <= time.time()-proof.get('last_heartbeat',0) < 60
    configured=bool(os.environ.get('ZAR_CLOUD_URL')) and bool(os.environ.get('ZAR_NODE_TOKEN'))
    cloud_state='ONLINE' if local_cloud and store or fresh_poll or fresh_probe else 'DEGRADED' if configured else 'NOT_CONFIGURED'
    cards.append(card('ZAR Cloud', cloud_state, version if local_cloud else proof.get('version'),
                      ['coordinator protocol 1', 'Bearer inference gateway'] if local_cloud else ['authenticated coordinator heartbeat'] if fresh_poll else ['health/protocol verified'] if fresh_probe else [],
                      [] if local_cloud else ['gateway inference not tested by this probe'], heartbeat=beat.get('timestamp') if fresh_poll else proof.get('last_heartbeat'),
                      node='energetic-charisma/production/web' if local_cloud else None, probe='cloud' if not local_cloud else None,
                      gateway_enabled=os.environ.get('ZAR_NODE_INFERENCE_ENABLED') == '1' if local_cloud else None))
    return {'cards': cards, 'policy': p, 'automatic_budget_eur': p['monthly_cents']/100,
            'unknown_costs_blocked': True, 'paid_generation_verified': False}


def probe(kind, store=None):
    """No model calls, jobs, generation, wallets or autonomous execution."""
    if kind == 'dramaclaw':
        media_company._HEALTH.clear()
        result = media_company.status()
        return {'state': 'DEGRADED' if result['ready'] else 'OFFLINE', 'api_accessible': result['ready'], 'generation_verified': False}
    if kind == 'jev':
        fallback = jev_decision._fallback('offline probe', {'review': {'type': 'noul'}})
        return {'state': jev_decision.status()['state'], 'fallback_verified': fallback['fallback'], 'external_call': False}
    if kind == 'node':
        node=next(c for c in inventory(store)['cards'] if c['name']=='NODE-02')
        return {k:node[k] for k in ['state','version','node','last_heartbeat']}
    if kind == 'cloud':
        from .node_inference import transport
        base,_,_,_=transport()
        if not base:
            raise PermissionError('Cloud/node configuration missing')
        # Public health only: no node token sent, no inference or poll/jobs.
        with requests.Session() as public:
            public.trust_env=False  # No ambient .netrc/proxy credentials.
            responses=[public.get(base+path,timeout=3,allow_redirects=False) for path in ['/health','/v1/nodes/health']]
            data=[r.json() if r.status_code==200 else {} for r in responses]
        health,coordinator=data
        if not isinstance(health,dict) or not isinstance(coordinator,dict) or health.get('ok') is not True or health.get('service')!='zar' or coordinator.get('ok') is not True or coordinator.get('protocol')!=1 or not re.fullmatch(r'\d+\.\d+\.\d+',str(health.get('version',''))):
            raise ValueError('Invalid Cloud health/protocol')
        return {'state':'ONLINE','version':health['version'],'protocol':1,'inference_performed':False}
    if kind == 'conway':
        return conway_adapter.observe()
    if kind == 'coding':
        cli = shutil.which('codex'); node = shutil.which('node')
        if not cli or not node or not sandbox.available():
            return {'state': 'NOT_CONFIGURED', 'cli_version_verified': False}
        executable = Path(cli).resolve(); package = executable.parent.parent
        packages = [package, *package.parent.glob('codex-*')]
        natives = [f for pkg in packages for f in pkg.rglob('codex') if f.is_file() and os.access(f, os.X_OK)]
        folder = Path(os.environ.get('ZAR_DATA_DIR', '/data')) / 'automation' / 'coding-probe'
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        result = sandbox.run([node, str(executable), '--version'], folder,
                             sandbox.profile([*packages, Path(node).resolve().parent], executables=[node, *natives]), timeout=15)
        version = re.search(r'codex-cli ([0-9]+(?:\.[0-9]+)+(?:[-+][A-Za-z0-9.-]+)?)',result['output'])
        return {'state': 'DISABLED' if control.policy()['coding_mode']=='DISABLED' else 'DEGRADED',
                'cli_version_verified': result['exit_code']==0 and bool(version), 'version': version.group(1) if result['exit_code']==0 and version else None,
                'model_execution_verified': False}
    raise ValueError('Unknown safe probe')


def register(app):
    from . import node_coordinator
    bp = Blueprint('integrations', __name__)

    def admin(write=False):
        if not node_coordinator.production_admin():
            abort(403)
        if write:
            if request.content_length and request.content_length > 8192:
                abort(413)
            token = request.headers.get('X-ZAR-Integrations-CSRF', '')
            if not token or not secrets.compare_digest(token, session.get('integrations_csrf', '')):
                abort(403)
            if request.headers.get('Origin') and request.headers['Origin'] != request.host_url.rstrip('/'):
                abort(403)

    @bp.get('/api/integrations')
    def state():
        admin()
        session.setdefault('integrations_csrf', secrets.token_urlsafe(24))
        return jsonify(ok=True, csrf=session['integrations_csrf'], **inventory(app.extensions.get('node_coordinator')))

    @bp.post('/api/integrations/probe/<kind>')
    def check(kind):
        admin(True)
        try:
            result=probe(kind,app.extensions.get('node_coordinator'))
            control.audit(kind,'SAFE_PROBE',result,{k:result[k] for k in ['state','version','protocol'] if k in result})
            return jsonify(ok=True, result=result)
        except (ValueError, OSError, TimeoutError) as exc:
            return jsonify(ok=False, error=type(exc).__name__, state='DEGRADED'), 409

    @bp.post('/api/integrations/policy')
    def configure():
        admin(True)
        body = request.get_json(silent=True)
        if not isinstance(body, dict) or set(body) != {'confirmed', 'changes'} or body['confirmed'] is not True or not isinstance(body['changes'],dict):
            abort(400)
        # Node modes must be enabled locally; never via a Cloud policy mirror.
        if os.environ.get('RAILWAY_ENVIRONMENT') and set(body['changes'] or {}) & {'coding_mode', 'conway_mode'}:
            abort(403)
        try:
            p=control.configure(body['changes'])
            store=app.extensions.get('node_coordinator')
            if p['kill_switch'] and store:
                with store.connect() as con:
                    for row in con.execute("SELECT id,body FROM distributed_jobs WHERE state IN ('QUEUED','ASSIGNED','RUNNING')").fetchall():
                        if json.loads(row['body']).get('kind')=='coding-task':
                            store.transition(con,row['id'],'CANCELLED')
            return jsonify(ok=True, policy=p)
        except ValueError:
            return jsonify(ok=False, error='Invalid/unsupported automation policy'), 400

    @bp.post('/api/integrations/conway/proposal')
    def proposal():
        admin(True)
        body = request.get_json(silent=True)
        if not isinstance(body, dict) or set(body) != {'tool', 'args'}:
            abort(400)
        try:
            return jsonify(ok=True, result=conway_adapter.propose(body['tool'], body['args']))
        except (ValueError, OSError, TimeoutError):
            return jsonify(ok=False, state='DEGRADED', error='Proposal blocked'), 409

    @bp.get('/api/integrations/coding/results/<task_id>')
    def coding_result(task_id):
        admin()
        result=control.coding_result(task_id)
        if result is None:
            abort(404)
        return jsonify(ok=True,result=result)

    @bp.post('/api/integrations/coding/results/<task_id>/cancel')
    def cancel(task_id):
        admin(True)
        try:
            control.cancel_coding(task_id)
            return jsonify(ok=True,cancel_requested=True)
        except ValueError:
            return jsonify(ok=False,error='Running local task required'),409

    app.register_blueprint(bp)
