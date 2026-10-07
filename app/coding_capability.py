"""Real CLI availability plus the legacy read-only invocation planner."""
import hashlib
import os
from pathlib import Path
import shutil
import json
from . import automation_control as control, automation_sandbox as sandbox

ROOT = Path(__file__).resolve().parents[1]


def status():
    installed = bool(shutil.which('codex'))
    enabled = os.environ.get('ZAR_CODEX_ENABLED') == '1'
    mode=control.policy()['coding_mode']
    version=None
    if installed:
        manifest=Path(shutil.which('codex')).resolve().parent.parent/'package.json'
        try:version=json.loads(manifest.read_text()).get('version')
        except (OSError,ValueError):pass
    return {'capability': 'coding-agent', 'installed': installed, 'enabled': mode!='DISABLED', 'legacy_planner_enabled':enabled, 'mode':mode,
            'state': 'DISABLED' if mode=='DISABLED' else 'DEGRADED',
            'remote_execution': mode!='DISABLED', 'sandbox': 'OS Seatbelt + file scope', 'credentials_stored': False,
            'sandbox_available':sandbox.available(),'task_runner':'real-codex-cli',
            'version':version,
            'local_model_configured':bool(os.environ.get('ZAR_CODING_LOCAL_MODEL')),
            'model_command_limit':0,'commit_push_deploy':'HUMAN_ACTION_REQUIRED',
            'missing':['local task approval', *([] if installed else ['Codex CLI']),
                       *([] if sandbox.available() else ['OS sandbox']),
                       *([] if os.environ.get('ZAR_CODING_LOCAL_MODEL') else ['local Ollama model'])]}


def prepare(task, workspace, authorized=False):
    if not status()['installed'] or not status()['legacy_planner_enabled'] or authorized is not True:
        raise PermissionError('Local explicit authorization and opt-in required')
    base = ROOT / '.local' / 'workspaces'
    path = Path(workspace).resolve()
    if not path.is_relative_to(base.resolve()) or not (path / '.git').is_dir():
        raise ValueError('Requires dedicated checkout under .local/workspaces')
    if not isinstance(task, str) or not task.strip() or len(task) > 8000:
        raise ValueError('Invalid task')
    return {'task_sha256': hashlib.sha256(task.encode()).hexdigest(), 'stdin': task,
            'argv': [shutil.which('codex'), 'exec', '--ignore-user-config', '--ephemeral',
                     '--sandbox', 'read-only', '-c', 'sandbox_read_only.network_access=false',
                     '--cd', str(path), '-'],
            'timeout_seconds': 300, 'output_limit_bytes': 1024 * 1024,
            'state': 'PREPARED_NOT_EXECUTED'}
