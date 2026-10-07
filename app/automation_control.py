"""Persistent automation policy, reservations and metadata-only audit.

This budget covers integration automation, not the existing interactive chat or
Stonks risk engine. Unknown upstream charges are refused, even with a budget.
"""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import time
import uuid

DEFAULT = {'kill_switch': False, 'conway_mode': 'OFF', 'coding_mode': 'DISABLED',
           'per_task_cents': 0, 'daily_cents': 0, 'monthly_cents': 0, 'providers': {}}


@contextmanager
def connection():
    root = Path(os.environ.get('ZAR_DATA_DIR', '/data')) / 'automation'
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    db = root / 'control.sqlite3'
    con = sqlite3.connect(db, timeout=10)
    con.row_factory = sqlite3.Row
    con.executescript('''CREATE TABLE IF NOT EXISTS policy (id INTEGER PRIMARY KEY, body TEXT);
        CREATE TABLE IF NOT EXISTS reservations (id TEXT PRIMARY KEY, provider TEXT, task TEXT, cents INTEGER, created REAL);
        CREATE TABLE IF NOT EXISTS audit (id INTEGER PRIMARY KEY, component TEXT, event TEXT, digest TEXT, details TEXT, created REAL);
        CREATE TABLE IF NOT EXISTS approvals (id TEXT PRIMARY KEY, digest TEXT, expires REAL, consumed INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS circuits (id TEXT PRIMARY KEY, failures INTEGER, opened REAL, success REAL);
        CREATE TABLE IF NOT EXISTS coding_results (id TEXT PRIMARY KEY, body TEXT);
        CREATE TABLE IF NOT EXISTS coding_cancellations (id TEXT PRIMARY KEY, created REAL);''')
    os.chmod(db, 0o600)
    try:
        with con:
            yield con
    finally:
        con.close()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def policy():
    with connection() as con:
        row = con.execute('SELECT body FROM policy WHERE id=1').fetchone()
    return {**DEFAULT, **(json.loads(row['body']) if row else {})}


def last_probe(component):
    with connection() as con:
        row=con.execute("SELECT details,created FROM audit WHERE component=? AND event='SAFE_PROBE' ORDER BY id DESC LIMIT 1",(component,)).fetchone()
    return {'last_heartbeat':row['created'], **json.loads(row['details'])} if row else {}


def configure(changes):
    if not isinstance(changes, dict) or set(changes) - set(DEFAULT):
        raise ValueError('Unknown policy fields')
    p = {**policy(), **changes}
    if type(p['kill_switch']) is not bool:
        raise ValueError('Invalid kill switch')
    if not isinstance(p['conway_mode'],str) or not isinstance(p['coding_mode'],str) or p['conway_mode'] not in {'OFF', 'OBSERVE', 'PROPOSE', 'EXECUTE'} or p['coding_mode'] not in {'DISABLED', 'READ_ONLY', 'PATCH', 'FULL'}:
        raise ValueError('Invalid mode')
    for key in ['per_task_cents', 'daily_cents', 'monthly_cents']:
        if type(p[key]) is not int or not 0 <= p[key] <= 1000000:
            raise ValueError('Invalid budget')
    if not isinstance(p['providers'], dict) or any(k not in {'jev', 'dramaclaw', 'elevenlabs', 'codex', 'conway'} or type(v) is not int or v < 0 for k, v in p['providers'].items()):
        raise ValueError('Invalid provider budget')
    # EXECUTE is not a renamed unrestricted upstream --run.
    if p['conway_mode'] == 'EXECUTE':
        raise ValueError('Conway EXECUTE unavailable: zero-cost inference and tool mediation not verified')
    with connection() as con:
        con.execute('INSERT OR REPLACE INTO policy VALUES (1,?)', (json.dumps(p),))
    audit('policy', 'CONFIGURED', p)
    return p


def audit(component, event, value, details=None):
    # State/prompts/provider errors are hashed, never copied into the audit log.
    allowed = {'state', 'tier', 'fallback', 'reason', 'cents', 'mode', 'exit_code', 'bytes', 'version', 'protocol'}
    meta = {k:v for k,v in (details or {}).items() if k in allowed and isinstance(v, (str, bool, int, float, type(None)))}
    with connection() as con:
        con.execute('INSERT INTO audit(component,event,digest,details,created) VALUES (?,?,?,?,?)',
                    (component, event, digest(value), json.dumps(meta), time.time()))


def reserve(provider, task, cents=None):
    """Require a trusted fixed upper bound; reservations never auto-refund errors.

    Callers must not supply a guessed estimate for an unbounded provider job.
    Uncertain/failed calls retain their reservation to prevent retry overspend.
    """
    if type(cents) is not int or cents <= 0:
        raise PermissionError('Unknown or unbounded upstream cost')
    with connection() as con:
        con.execute('BEGIN IMMEDIATE')
        row = con.execute('SELECT body FROM policy WHERE id=1').fetchone()
        p = {**DEFAULT, **(json.loads(row['body']) if row else {})}
        now = time.time(); day = now - now % 86400
        import datetime
        month = datetime.datetime.now(datetime.timezone.utc).replace(day=1,hour=0,minute=0,second=0,microsecond=0).timestamp()
        totals = [con.execute('SELECT COALESCE(SUM(cents),0) FROM reservations WHERE created>=?', (t,)).fetchone()[0] for t in [day, month]]
        used = con.execute('SELECT COALESCE(SUM(cents),0) FROM reservations WHERE provider=? AND created>=?', (provider,month)).fetchone()[0]
        task_used = con.execute('SELECT COALESCE(SUM(cents),0) FROM reservations WHERE task=?', (digest(task),)).fetchone()[0]
        if p['kill_switch'] or task_used+cents > p['per_task_cents'] or totals[0]+cents > p['daily_cents'] or totals[1]+cents > p['monthly_cents'] or used+cents > p['providers'].get(provider, 0):
            raise PermissionError('AI/Automation Budget blocked')
        rid = str(uuid.uuid4())
        con.execute('INSERT INTO reservations VALUES (?,?,?,?,?)', (rid,provider,digest(task),cents,now))
    audit(provider, 'RESERVED', task, {'cents': cents})
    return rid


def paid_call(provider, task):
    # Installed providers do not yet expose a verifiable EUR quote/hard cap.
    # A positive UI budget alone must never authorize an unknown charge.
    return reserve(provider, task, cents=None)


def approve_locally(spec, ttl=300):
    """Local CLI only; never exposed as a coordinator or HTTP approval endpoint."""
    rid = str(uuid.uuid4())
    with connection() as con:
        con.execute('INSERT INTO approvals VALUES (?,?,?,0)', (rid,digest(spec),time.time()+min(300,max(1,ttl))))
    audit('coding', 'LOCAL_APPROVAL', spec)
    return rid


def consume_approval(rid, spec):
    with connection() as con:
        con.execute('BEGIN IMMEDIATE')
        count = con.execute('UPDATE approvals SET consumed=1 WHERE id=? AND digest=? AND expires>? AND consumed=0',
                            (rid,digest(spec),time.time())).rowcount
        if not count:
            raise PermissionError('Matching unexpired local approval required')


def coding_result(task_id):
    with connection() as con:
        row=con.execute('SELECT body FROM coding_results WHERE id=?',(task_id,)).fetchone()
    return json.loads(row['body']) if row else None


def cancel_coding(task_id):
    with connection() as con:
        row=con.execute('SELECT body FROM coding_results WHERE id=?',(task_id,)).fetchone()
        if not row or json.loads(row['body']).get('state')!='RUNNING':
            raise ValueError('Running local task required')
        con.execute('INSERT OR IGNORE INTO coding_cancellations VALUES (?,?)',(task_id,time.time()))
    audit('coding','CANCEL_REQUESTED',task_id)


def coding_cancelled(task_id):
    with connection() as con:
        return bool(con.execute('SELECT id FROM coding_cancellations WHERE id=?',(task_id,)).fetchone())
