"""Optional local Codex task planner. No CLI execution or credential access.

Produces a bounded read-only invocation for a future locally authorized runner.
Remote worker does not have a coding handler or accept authorization from jobs.
"""
import hashlib
import os
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]


def status():
    installed = bool(shutil.which('codex'))
    enabled = os.environ.get('ZAR_CODEX_ENABLED') == '1'
    return {'capability': 'coding-agent', 'installed': installed, 'enabled': enabled,
            'state': 'AVAILABLE_FOR_LOCAL_APPROVAL' if installed and enabled else 'DISABLED',
            'remote_execution': False, 'sandbox': 'read-only', 'credentials_stored': False}


def prepare(task, workspace, authorized=False):
    if not status()['installed'] or not status()['enabled'] or authorized is not True:
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
