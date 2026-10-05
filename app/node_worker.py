"""Independent pull worker. Only bounded, read-only handlers accept cloud jobs."""
from contextlib import contextmanager
import argparse
from datetime import datetime, timezone
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import sqlite3
import subprocess
import time
import threading
import uuid
from urllib.parse import urlparse

import requests
from .scoped_http import BearerAuth

ROOT = Path(__file__).resolve().parents[1]
WORKER_VERSION = '1.0.0'
HANDLERS = {'node-info': 'python', 'diagnostics': 'python', 'file-sha256': 'filesystem', 'workspace-summary': 'workspace-processing'}


@lru_cache(maxsize=1)
def capabilities():
    caps = ['python', 'filesystem', 'workspace-processing']
    for command, name in [('node', 'node'), ('git', 'git')]:
        if shutil.which(command):
            caps.append(name)
    browser = ROOT / '.local/browser/browsers/chromium-1140/chrome-mac/Chromium.app/Contents/MacOS/Chromium'
    if browser.is_file() and os.access(browser, os.X_OK):
        caps.append('browser')
    try:
        import imageio_ffmpeg
        proc = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), '-version'], capture_output=True, timeout=5)
        if proc.returncode == 0:
            caps.append('media-processing')
    except (ImportError, OSError, subprocess.SubprocessError):
        pass
    # Installed CLI is reported separately; execution remains opt-in and local.
    return caps


def resources():
    ram = None
    if platform.system() == 'Darwin':
        try:
            ram = int(subprocess.check_output(['/usr/sbin/sysctl', '-n', 'hw.memsize'], text=True,
                                              stderr=subprocess.DEVNULL, timeout=3))
        except (OSError, subprocess.SubprocessError, ValueError):
            pass
    if platform.system() == 'Linux':
        try:
            ram = os.sysconf('SC_PAGE_SIZE') * os.sysconf('SC_PHYS_PAGES')
        except (ValueError, OSError):
            pass
    elif platform.system() == 'Windows':
        import ctypes
        class MemoryStatus(ctypes.Structure):
            _fields_ = [('length',ctypes.c_ulong),('load',ctypes.c_ulong)] + [(name,ctypes.c_ulonglong) for name in ('total','available','page_total','page_available','virtual_total','virtual_available','extended')]
        status = MemoryStatus()
        status.length = ctypes.sizeof(status)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            ram = status.total
    return {'os': platform.system(), 'architecture': platform.machine(), 'cpu_count': os.cpu_count() or 1,
            'ram_bytes': ram, 'load': list(os.getloadavg()) if hasattr(os, 'getloadavg') else [0],
            'codex_installed': bool(shutil.which('codex')), 'coding_agent_enabled': False}


class Worker:
    def __init__(self, directory=None):
        self.sync_lock = threading.RLock()
        self.started = time.monotonic()
        self.paused = False
        self.revoked = False
        self.cloud_state = 'NOT_CONFIGURED'
        self.directory = Path(directory or os.environ.get('ZAR_NODE_DIR', ROOT / '.local' / 'node'))
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.db = self.directory / 'worker.sqlite3'
        with self.connect() as con:
            con.executescript('''CREATE TABLE IF NOT EXISTS identity (id TEXT PRIMARY KEY, name TEXT);
                CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, kind TEXT, payload TEXT,
                state TEXT, progress INTEGER DEFAULT 0, result TEXT, priority INTEGER DEFAULT 0,
                reported INTEGER DEFAULT 0);
                CREATE TABLE IF NOT EXISTS heartbeat (id INTEGER PRIMARY KEY, payload TEXT);''')
            if not con.execute('SELECT id FROM identity').fetchone():
                con.execute('INSERT INTO identity VALUES (?,?)',
                            (str(uuid.uuid4()), os.environ.get('ZAR_NODE_NAME', 'ZAR-NODE-02-MAC')))
        with self.connect() as con:
            columns = {r['name'] for r in con.execute('PRAGMA table_info(jobs)')}
            for name, sql in [('remote', 'INTEGER DEFAULT 0'), ('claimed', 'INTEGER DEFAULT 0'), ('deadline','REAL')]:
                if name not in columns:
                    con.execute(f'ALTER TABLE jobs ADD COLUMN {name} {sql}')
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

    def identity(self):
        with self.connect() as con:
            return dict(con.execute('SELECT * FROM identity').fetchone())

    def recover(self):
        # Record interruption; never silently repeat work after a process restart.
        with self.connect() as con:
            con.execute("UPDATE jobs SET state='INTERRUPTED', reported=0, result=? WHERE state='RUNNING' OR (state='QUEUED' AND remote=1 AND claimed=1)", (json.dumps({"error":"Worker restarted during execution"}),))

    def heartbeat(self):
        with self.connect() as con:
            active = con.execute("SELECT COUNT(*) FROM jobs WHERE state IN ('QUEUED','RUNNING')").fetchone()[0]
        detected = list(capabilities())
        drama = os.environ.get('DRAMACLAW_API_URL','').rstrip('/')
        parsed = urlparse(drama)
        if parsed.hostname in {'127.0.0.1','localhost'} and parsed.scheme=='http':
            try:
                if requests.get(drama+'/api/v1/config',timeout=(1,2),allow_redirects=False).status_code==200:
                    detected.append('dramaclaw-local')
            except requests.RequestException:
                pass
        row = {**self.identity(), 'timestamp': time.time(), 'capabilities': detected,
               'resources': resources(), 'active_jobs': active, 'max_concurrency': 1,
               'cost': {'currency': 'EUR', 'per_job': None}, 'handlers': HANDLERS}
        row.update(version=(ROOT / 'VERSION').read_text().strip(), worker_version=WORKER_VERSION,
                   uptime=round(time.monotonic()-self.started, 1), cloud_state=self.cloud_state)
        # Preserve local read-only status adapters without making them Cloud dependencies.
        optional = {}
        try:
            from .coding_capability import status as coding_status
            optional['coding-agent'] = coding_status()
        except ImportError:
            optional['coding-agent'] = {'state':'NOT_CONFIGURED','remote_execution':False}
        try:
            from .conway_adapter import status as conway_status
            optional['conway-runtime'] = conway_status()  # No runtime probe or execution.
        except ImportError:
            optional['conway-runtime'] = {'state':'NOT_CONFIGURED','runtime_running':False}
        row['optional_capabilities'] = optional
        with self.connect() as con:
            con.execute('INSERT OR REPLACE INTO heartbeat VALUES (1,?)', (json.dumps(row),))
        return row

    def enqueue(self, job, remote=False):
        kind = job.get('kind')
        if kind not in HANDLERS:
            raise ValueError('Job kind forbidden by node policy')
        jid = str(job.get('id') or uuid.uuid4())
        payload = job.get('payload', {})
        if len(jid) > 128 or not isinstance(payload, dict) or len(json.dumps(payload)) > 8192:
            raise ValueError('Invalid job')
        if kind in {'node-info', 'diagnostics'} and payload:
            raise ValueError('This action accepts no arguments')
        if kind in {'file-sha256','workspace-summary'} and (set(payload) != {'path'} or not isinstance(payload['path'],str)):
            raise ValueError('Only an input file path is accepted')
        deadline = job.get('deadline')
        if remote and (isinstance(deadline,bool) or not isinstance(deadline,(int,float)) or not 0 < deadline <= time.time()+630):
            raise ValueError('Remote job requires a bounded deadline')
        priority = int(job.get('priority', 0))
        with self.connect() as con:
            existing = con.execute('SELECT kind,payload FROM jobs WHERE id=?', (jid,)).fetchone()
            if existing and (existing['kind'] != kind or json.loads(existing['payload']) != payload):
                raise ValueError('Job ID reused with different content')
            con.execute('INSERT OR IGNORE INTO jobs (id,kind,payload,state,priority,remote,deadline) VALUES (?,?,?,?,?,?,?)',
                        (jid, kind, json.dumps(payload), 'QUEUED', priority, int(remote), deadline))
        return jid

    def get(self, jid):
        with self.connect() as con:
            row = con.execute('SELECT * FROM jobs WHERE id=?', (jid,)).fetchone()
        if row is None:
            return None
        result = dict(row)
        for key in ('payload', 'result'):
            result[key] = json.loads(result[key]) if result[key] else None
        return result

    def cancel(self, jid):
        with self.connect() as con:
            con.execute("UPDATE jobs SET state='CANCELLED', reported=0 WHERE id=? AND state IN ('RUNNING','QUEUED')", (jid,))

    def safe_file(self, value):
        # Dedicated input directory; no code, credentials, .git or node DB access.
        base = self.directory / 'inputs'
        base.mkdir(exist_ok=True, mode=0o700)
        path = (base / str(value)).resolve()
        if not path.is_relative_to(base.resolve()) or not path.is_file():
            raise ValueError('Input must be a file inside node inputs')
        if path.stat().st_size > 64 * 1024 * 1024:
            raise ValueError('Input too large')
        return path

    def run_one(self):
        if self.paused or self.revoked:
            return False
        with self.connect() as con:
            con.execute('BEGIN IMMEDIATE')
            row = con.execute("SELECT id,remote,claimed,deadline FROM jobs WHERE state='QUEUED' ORDER BY priority DESC, rowid LIMIT 1").fetchone()
            if not row:
                return False
            jid = row['id']
            if row['remote'] and not row['claimed']:
                return False
            if row['deadline'] and time.time() >= row['deadline']:
                con.execute("UPDATE jobs SET state='TIMED_OUT',reported=0 WHERE id=?",(jid,))
                return True
            con.execute("UPDATE jobs SET state='RUNNING', progress=1 WHERE id=?", (jid,))
        job = self.get(jid)
        try:
            if job['remote']:
                self.sync()  # Report BUSY/progress before even a short handler runs.
                if self.get(jid)['state'] != 'RUNNING' or self.revoked:
                    return True
            if job['kind'] == 'node-info':
                node = shutil.which('node')
                result = {'hostname': platform.node(), 'architecture': platform.machine(),
                          'python': platform.python_version(), 'node': subprocess.check_output([node,'--version'],text=True,timeout=5).strip() if node else None,
                          'timestamp': datetime.now(timezone.utc).isoformat()}
            elif job['kind'] == 'diagnostics':
                result = {'resources': resources(), 'capabilities': capabilities()}
            else:
                path = self.safe_file(job['payload'].get('path', ''))
                digest = hashlib.sha256()
                total = path.stat().st_size
                count = 0
                with path.open('rb') as source:
                    while chunk := source.read(65536):
                        if self.get(jid)['state'] in {'CANCELLED','TIMED_OUT','INTERRUPTED'}:
                            return True
                        if job['deadline'] and time.time() >= job['deadline']:
                            with self.connect() as con:
                                con.execute("UPDATE jobs SET state='TIMED_OUT',reported=0 WHERE id=?",(jid,))
                            return True
                        digest.update(chunk)
                        count += len(chunk)
                        with self.connect() as con:
                            con.execute('UPDATE jobs SET progress=? WHERE id=? AND state=?',
                                        (min(99, int(count * 100 / max(1, total))), jid, 'RUNNING'))
                result = {'sha256': digest.hexdigest(), 'bytes': count}
                if job['kind'] == 'workspace-summary':
                    with path.open('rb') as source:
                        result['lines'] = sum(1 for _ in source)
            state = 'SUCCEEDED'
        except (ValueError, OSError, subprocess.SubprocessError, requests.RequestException) as exc:
            result, state = {'error': type(exc).__name__}, 'FAILED'
        if job['deadline'] and time.time()>=job['deadline']:
            state, result = 'TIMED_OUT', {'error':'Job deadline exceeded'}
        with self.connect() as con:
            con.execute('UPDATE jobs SET state=?, progress=100, result=?, reported=0 WHERE id=? AND state=?',
                        (state, json.dumps(result), jid, 'RUNNING'))
        return True

    def sync(self):
        with self.sync_lock:
            return self._sync()

    def _sync(self):
        base = os.environ.get('ZAR_CLOUD_URL', '').rstrip('/')
        token = os.environ.get('ZAR_NODE_TOKEN', '')
        if not base or not token:
            return {'state': 'NOT_CONFIGURED'}
        url = urlparse(base)
        if url.scheme != 'https' and not (url.scheme == 'http' and url.hostname in {'127.0.0.1', 'localhost'}):
            raise ValueError('Cloud requires HTTPS; HTTP allowed only on loopback')
        if url.username or url.password or url.query or url.fragment or url.path not in {'','/'}:
            raise ValueError('Cloud URL must be an origin without credentials')
        with self.connect() as con:
            pending = [r['id'] for r in con.execute('SELECT id FROM jobs WHERE reported=0 AND remote=1 ORDER BY rowid DESC LIMIT 100')]
        reports = [{key:self.get(jid)[key] for key in ('id','state','progress','result')} for jid in pending]
        response = requests.post(base + '/v1/nodes/poll',
                                 headers={'Authorization': 'Bearer ' + token},auth=BearerAuth(token),
                                 json={'heartbeat': self.heartbeat(), 'reports': reports},
                                 timeout=(5, 15), allow_redirects=False)
        if response.status_code in {401,403}:
            self.revoked = True
            self.cloud_state = 'AUTH_REJECTED'
            with self.connect() as con:
                con.execute("UPDATE jobs SET state='CANCELLED',reported=0 WHERE remote=1 AND state IN ('QUEUED','RUNNING')")
            return {'state':self.cloud_state}
        response.raise_for_status()
        if response.status_code != 200:
            raise ValueError('Unexpected coordinator response')
        data = response.json()
        self.paused = bool(data.get('paused'))
        self.revoked = False
        self.cloud_state = 'PAUSED' if self.paused else 'ONLINE'
        for jid in data.get('cancel', []):
            self.cancel(jid)
        for job in data.get('jobs', []):
            jid = self.enqueue(job, remote=True)
            if not self.paused and self.get(jid)['state']=='QUEUED':
                claim = requests.post(base + '/v1/jobs/'+jid+'/claim',
                                      headers={'Authorization':'Bearer '+token},auth=BearerAuth(token),
                                      json={'heartbeat':{'id':self.identity()['id']}},
                                      timeout=(5,15),allow_redirects=False)
                if claim.status_code==200:
                    with self.connect() as con:
                        con.execute('UPDATE jobs SET claimed=1 WHERE id=?',(jid,))
                elif claim.status_code!=409:
                    claim.raise_for_status()
        with self.connect() as con:
            for jid in data.get('ack', []):
                if jid in pending and self.get(jid)['state'] in {'SUCCEEDED', 'FAILED', 'CANCELLED', 'TIMED_OUT','INTERRUPTED'}:
                    con.execute('UPDATE jobs SET reported=1 WHERE id=?', (jid,))
        return {'state': self.cloud_state}


def main(args=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['run', 'status', 'enqueue', 'get', 'cancel'])
    parser.add_argument('value', nargs='?')
    ns = parser.parse_args(args)
    worker = Worker()
    if ns.command == 'status':
        print(json.dumps(worker.heartbeat(), indent=2))
    elif ns.command == 'enqueue':
        print(worker.enqueue(json.loads(ns.value)))
    elif ns.command == 'get':
        print(json.dumps(worker.get(ns.value), indent=2))
    elif ns.command == 'cancel':
        worker.cancel(ns.value)
    else:
        import threading
        with (worker.directory / 'worker.lock').open('w') as lock:
            if os.name=='nt':
                import msvcrt
                lock.write('0'); lock.flush(); lock.seek(0)
                msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            worker.recover()
            def poll_cloud():
                while True:
                    worker.heartbeat()
                    try:
                        worker.sync()
                    except (requests.RequestException, ValueError, KeyError, TypeError):
                        worker.cloud_state = 'DEGRADED'
                        print('Cloud DEGRADED; local worker continues', flush=True)
                    time.sleep(5)
            threading.Thread(target=poll_cloud, daemon=True).start()
            while True:
                worker.run_one()
                time.sleep(0.5)


if __name__ == '__main__':
    main()
