"""Real Codex CLI tasks: one-use local approval, isolated worktree, OSS only.

The model has ZERO shell commands. Tests are selected from a host-owned list and
run under Seatbelt. FULL never grants commit, push, deployment or secret access.
"""
import ast
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import uuid
import requests

from . import automation_control as control, automation_sandbox as sandbox

ROOT = Path(__file__).resolve().parents[1]
SECRET = re.compile(r'-----BEGIN (?:OPENSSH|RSA|EC) PRIVATE KEY-----|\b(?:sk-proj-|ghp_|github_pat_)[A-Za-z0-9_-]{20,}|\bAKIA[A-Z0-9]{16}')
DISABLED_FEATURES = ('shell_tool','unified_exec','hooks','skill_mcp_dependency_install',
                     'code_mode_host','apps','plugins','remote_plugin','browser_use',
                     'browser_use_external','computer_use','image_generation',
                     'in_app_local_automation','daemon_auto_start','multi_agent',
                     'multi_agent_v2','workspace_dependencies','worktrees','shell_snapshot',
                     'skill_search','goals','unbounded_connection_retries')


def validate(payload):
    fields={'task','files','mode','tests','approval_id'}
    if not isinstance(payload,dict) or set(payload)!=fields:
        raise ValueError('Exact coding task schema required')
    if not isinstance(payload['mode'],str) or payload['mode'] not in {'READ_ONLY','PATCH','FULL'}:
        raise ValueError('Invalid coding mode')
    if not isinstance(payload['task'],str) or not 1<=len(payload['task'])<=6000 or SECRET.search(payload['task']):
        raise ValueError('Invalid or secret-bearing prompt')
    if not isinstance(payload['files'],list) or not 1<=len(payload['files'])<=20:
        raise ValueError('Explicit file scope required')
    for value in payload['files']:
        if not isinstance(value,str):raise ValueError('Invalid file scope')
        p=Path(value)
        if not p.parts or p.is_absolute() or '..' in p.parts or any(x.startswith('.') for x in p.parts) or p.suffix.lower() in {'.pem','.key','.db','.sqlite','.sqlite3'} or p.name.lower() in {'config.json','credentials.json','auth.json'}:
            raise ValueError('Private or escaping file scope')
    if not isinstance(payload['tests'],list) or len(payload['tests'])>2 or any(not isinstance(x,str) or x not in {'python-syntax','javascript-syntax'} for x in payload['tests']):
        raise ValueError('Only trusted offline test commands')
    if not isinstance(payload['approval_id'],str):raise ValueError('Local approval required')
    return {k:v for k,v in payload.items() if k!='approval_id'}


def _git(*args,cwd=None):
    return subprocess.check_output(['git','-c','core.hooksPath=/dev/null',*args],cwd=cwd or ROOT,text=True,stderr=subprocess.DEVNULL,timeout=15)


def _save(task_id, value):
    with control.connection() as con:
        con.execute('INSERT OR REPLACE INTO coding_results VALUES (?,?)',(task_id,json.dumps(value)))
    return value


@contextmanager
def clean_snapshot(base):
    """Only this installation's main HEAD; never user-selected repositories.

    Clone committed objects, not the working tree. Hooks are disabled and no
    checkout/worktree/branch is created in the development repository.
    """
    head = _git('rev-parse','HEAD').strip()
    if _git('symbolic-ref','--short','HEAD').strip() != 'main':
        raise PermissionError('Canonical main checkout required')
    source = base/'source'
    try:
        _git('clone','--no-hardlinks','--no-checkout','--',str(ROOT),str(source))
        _git('checkout','--detach',head,cwd=source)
        if (_git('rev-parse','HEAD',cwd=source).strip()!=head
                or _git('status','--porcelain',cwd=source).strip()
                or _git('rev-parse','HEAD').strip()!=head
                or _git('symbolic-ref','--short','HEAD').strip()!='main'):
            raise PermissionError('Source snapshot must be clean and match canonical HEAD')
        yield source,head
    finally:
        # Entire disposable clone owns its worktrees/branches; never main's .git.
        if source.exists():
            shutil.rmtree(source)


def run_task(payload, cancelled=lambda:False):
    spec=validate(payload);p=control.policy()
    if p['kill_switch'] or p['coding_mode']=='DISABLED' or p['coding_mode']!=spec['mode']:
        raise PermissionError('Coding task disabled or mode mismatch')
    if not sandbox.available() or not shutil.which('codex'):
        raise PermissionError('Real CLI and OS sandbox required')
    # Paid Codex providers are deliberately unavailable in this integration.
    model=os.environ.get('ZAR_CODING_LOCAL_MODEL','').strip()
    if not re.fullmatch(r'[a-zA-Z0-9_.:-]{1,100}',model) or 'cloud' in model.lower():
        raise PermissionError('Approved local Ollama model required; no paid fallback')
    try:
        tags=requests.get('http://127.0.0.1:11434/api/tags',timeout=2,allow_redirects=False)
        installed={entry['name'] for entry in tags.json()['models']
                   if not entry.get('remote_host') and not entry.get('remote_model')
                   and type(entry.get('size')) is int and entry['size']>1024*1024
                   and isinstance(entry.get('details'),dict) and entry['details'].get('format')=='gguf'} if tags.status_code==200 else set()
    except (requests.RequestException,ValueError,KeyError,TypeError):
        raise PermissionError('Local model inventory unavailable') from None
    if model not in installed:
        raise PermissionError('Model must already be installed; downloading is not authorized')
    task_id=str(uuid.uuid4());base=Path(os.environ.get('ZAR_DATA_DIR','/data'))/'automation'/'coding'/task_id
    base.mkdir(parents=True,mode=0o700)
    try:
        with clean_snapshot(base) as (source,head):
            control.consume_approval(payload['approval_id'],spec)
            result = _run_approved(spec,task_id,base,source,head,model,cancelled)
    finally:
        # No credentials/configuration survive even a failed native invocation.
        if (base/'codex-home').exists():
            shutil.rmtree(base/'codex-home')
    result['snapshot_removed'] = not (base/'source').exists()
    result['worktree_removed'] = not (base/'source/worktree').exists()
    result['temporary_branch_removed'] = result['snapshot_removed']
    result['codex_home_removed'] = not (base/'codex-home').exists()
    return _save(task_id,result)


def _run_approved(spec,task_id,base,source,head,model,cancelled):
    worktree=source/'worktree';branch='zar-task/'+task_id
    _git('worktree','add','-b',branch,'--',str(worktree),head,cwd=source)
    result={'id':task_id,'state':'RUNNING','branch':branch,'source_head':head,'mode':spec['mode'],'model_commands_limit':0,'host_commands_limit':5, 'spent_eur':0}
    _save(task_id,result)
    external_cancelled=cancelled
    cancelled=lambda:external_cancelled() or control.coding_cancelled(task_id)
    try:
        for path in worktree.rglob('*'):
            if path.is_symlink():raise PermissionError('Symlink checkout refused')
            if path.is_file() and path.name!='.git':
                if (path.name.startswith('.env') and not path.name.endswith('.example')) or path.name.lower() in {'credentials.json','auth.json','config.json'}:
                    raise PermissionError('Private file in checkout')
                with path.open('r', errors='ignore') as content:
                    carry = ''
                    while chunk := content.read(65536):
                        if SECRET.search(carry+chunk):raise PermissionError('Secret-bearing checkout')
                        carry = chunk[-256:]
        writable=[]
        if spec['mode']!='READ_ONLY':
            for f in spec['files']:
                target=worktree/f;target.parent.mkdir(parents=True,exist_ok=True);writable.append(target)
        executable=Path(shutil.which('codex')).resolve()
        # npm launcher invokes the bundled native CLI. Permit that package only,
        # never a shell or git; Codex shell/web/hooks features are disabled too.
        package=executable.parent.parent
        packages=[package,*package.parent.glob('codex-*')]
        native=[f for pkg in packages for f in pkg.rglob('codex') if f.is_file() and os.access(f,os.X_OK)]
        node=Path(shutil.which('node')).resolve()
        home=base/'codex-home';home.mkdir(mode=0o700)
        argv=[str(node),str(executable),'exec','--ignore-user-config','--ignore-rules','--ephemeral','--oss','--local-provider','ollama',
              '--model',model,'--sandbox','read-only' if spec['mode']=='READ_ONLY' else 'workspace-write',
              '--skip-git-repo-check','--json',
              *[item for feature in DISABLED_FEATURES for item in ['--disable',feature]],
              '-c','web_search="disabled"','-c','approval_policy="never"','--cd',str(worktree),'-']
        boundary=sandbox.profile([*(worktree/f for f in spec['files']),*packages,node.parent],writable,executables=[node,*native],local_model=True)
        boundary += '\n(allow file-read* (literal '+json.dumps(str(worktree))+'))'
        # Codex config/state may be written only to its fresh task-local home.
        boundary += '\n(allow file-read* file-write* (subpath '+json.dumps(str(home))+'))'
        outcome=sandbox.run(argv,base,boundary,timeout=300,stdin=spec['task'],cancelled=cancelled)
        if cancelled():raise TimeoutError('Task cancelled')
        changed=set(_git('diff','--name-only','HEAD',cwd=worktree).splitlines()) | set(_git('ls-files','--others','--exclude-standard',cwd=worktree).splitlines())
        if changed-set(spec['files']) or (spec['mode']=='READ_ONLY' and changed):
            raise PermissionError('File scope violated')
        patch=_git('diff','--no-ext-diff','HEAD',cwd=worktree)
        new_files={}
        for name in changed:
            f=worktree/name
            if f.is_symlink() or not f.resolve().is_relative_to(worktree.resolve()):raise PermissionError('Escaping result')
            if f.exists():
                text=f.read_text(errors='replace')
                if SECRET.search(text):raise PermissionError('Secret-bearing result blocked')
                if len(text)>512*1024:raise ValueError('Result limit')
                if name in _git('ls-files','--others','--exclude-standard',cwd=worktree).splitlines():new_files[name]=text
        if len(patch)>512*1024 or SECRET.search(patch):raise PermissionError('Unsafe diff')
        tests=[];commands=0
        for kind in spec['tests']:
            if cancelled():raise TimeoutError('Task cancelled')
            for f in spec['files']:
                target=worktree/f
                if target.exists() and kind=='python-syntax' and target.suffix=='.py':
                    ast.parse(target.read_text());tests.append({'file':f,'check':kind,'ok':True})
                elif target.exists() and kind=='javascript-syntax' and target.suffix in {'.js','.cjs','.mjs'}:
                    commands+=1
                    if commands>5:raise PermissionError('Host test command limit exceeded')
                    checked=sandbox.run([str(node),'--check',str(target)],base,sandbox.profile([worktree,node.parent],executables=[node]),timeout=15,cancelled=cancelled)
                    tests.append({'file':f,'check':kind,'ok':checked['exit_code']==0})
        result.update(state='SUCCEEDED' if outcome['exit_code']==0 and all(t['ok'] for t in tests) else 'FAILED',diff=patch,new_files=new_files,tests=tests,
                      log={'sha256':hashlib.sha256(outcome['output'].encode()).hexdigest(),'bytes':len(outcome['output'])},exit_code=outcome['exit_code'],
                      commit_push_deploy='HUMAN_ACTION_REQUIRED')
    except (OSError,ValueError,SyntaxError,PermissionError,TimeoutError,subprocess.SubprocessError) as exc:
        result.update(state='CANCELLED' if cancelled() else 'FAILED',error=type(exc).__name__)
    control.audit('coding','FINISHED',spec,{'state':result['state'],'mode':spec['mode']})
    return _save(task_id,result)
