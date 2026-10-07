"""Read-only adapter for the real Conway runtime, separate from Stonks.

No setup, provisioning, funding or --run command. Enabling execution later needs
an isolated service with enforced tool/network/spending policy, not a Python loop.
"""
from pathlib import Path
import shutil
import subprocess
import json
import os
import uuid
from . import automation_control as control, automation_sandbox as sandbox

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / '.local' / 'upstream' / 'automaton'


def status(probe=False):
    entry = SOURCE / 'dist' / 'index.js'
    built = entry.is_file() and bool(shutil.which('node'))
    result = {'provider': 'Conway-Research/automaton', 'state': 'NOT_CONFIGURED',
              'upstream_installed': built, 'runtime_running': False,
              'execution_authority': False, 'paid_operations': False,
              'reason': 'Runtime built; isolated service and authorized credentials required' if built else 'Official runtime not built'}
    p=control.policy()
    result.update(mode=p['conway_mode'],sandbox_available=sandbox.available(),
                  state='DISABLED' if built and p['conway_mode']=='OFF' else 'NOT_CONFIGURED',
                  missing=['zero-cost inference','mediated tool execution','explicit task approval'],
                  version=json.loads((SOURCE/'package.json').read_text()).get('version') if built else None,
                  allowlist=['read_file'],denylist=['exec','transfer','purchase','deploy','publish','delete','wallet','secrets'],
                  network='DENY_ALL',spend_limit_eur=0,kill_switch=p['kill_switch'])
    if probe and built:
        try:
            proc = subprocess.run([shutil.which('node'), str(entry), '--version'],
                                  capture_output=True, text=True, timeout=15, cwd=SOURCE)
            result['version_probe_ok'] = proc.returncode == 0 and 'Conway Automaton' in proc.stdout
            if not result['version_probe_ok']:
                result['state'] = 'DEGRADED'
        except (OSError, subprocess.SubprocessError):
            result.update(state='DEGRADED', version_probe_ok=False)
    return result


def observe():
    if control.policy()['kill_switch'] or control.policy()['conway_mode'] not in {'OBSERVE','PROPOSE'}:
        raise PermissionError('Automaton is OFF or killed')
    node=shutil.which('node')
    if not node or not (SOURCE/'dist/index.js').is_file():
        raise PermissionError('Official runtime missing')
    folder=Path(os.environ.get('ZAR_DATA_DIR','/data'))/'automation'/'conway'
    folder.mkdir(parents=True,exist_ok=True,mode=0o700)
    profile=sandbox.profile([SOURCE,Path(node).resolve().parent],executables=[node])
    result=sandbox.run([node,str(SOURCE/'dist/index.js'),'--version'],folder,profile,timeout=15)
    ok=result['exit_code']==0 and 'Conway Automaton' in result['output']
    control.audit('conway','OBSERVED',{'ok':ok},{'exit_code':result['exit_code'],'mode':'OBSERVE'})
    return {'state':'ONLINE' if ok else 'DEGRADED','probe_only':True,'runtime_running':False,'version':status()['version']}


def propose(tool, args):
    """Official PolicyEngine evaluates a proposal; no tool/LLM is executed."""
    if control.policy()['kill_switch'] or control.policy()['conway_mode']!='PROPOSE':
        raise PermissionError('PROPOSE mode and local opt-in required')
    if tool!='read_file' or not isinstance(args,dict) or set(args)!={'path'}:
        control.audit('conway','DENIED',{'tool':tool,'args':args})
        return {'action':'deny','reasonCode':'ZAR_DENYLIST','executed':False}
    if not isinstance(args['path'],str):
        raise ValueError('Invalid proposal path')
    path=Path(args['path'])
    if path.is_absolute() or '..' in path.parts or any(part.startswith('.') for part in path.parts):
        raise ValueError('Only non-private relative proposal paths')
    node=shutil.which('node')
    if not node or not (SOURCE/'dist/index.js').is_file():
        raise PermissionError('Official runtime missing')
    folder=Path(os.environ.get('ZAR_DATA_DIR','/data'))/'automation'/'conway'/str(uuid.uuid4())
    folder.mkdir(parents=True,mode=0o700)
    script=ROOT/'scripts/conway-policy.mjs'
    write=[folder/('policy.sqlite3'+suffix) for suffix in ['','-wal','-shm','-journal']]
    profile=sandbox.profile([SOURCE,script,*write,Path(node).resolve().parent],write,executables=[node],temporary_delete_paths=write[1:])
    profile+='\n(allow file-read* (literal '+json.dumps(str(folder))+'))'
    result=sandbox.run([node,str(script),str(SOURCE)],folder,profile,stdin=json.dumps({'tool':tool,'args':args}),timeout=15)
    if result['exit_code']!=0:raise PermissionError('Official policy engine failed; proposal blocked')
    answer=json.loads(result['output'])
    control.audit('conway','PROPOSAL',answer,{'mode':'PROPOSE'})
    return {**answer,'executed':False,'requires_review':True}
