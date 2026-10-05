"""Read-only adapter for the real Conway runtime, separate from Stonks.

No setup, provisioning, funding or --run command. Enabling execution later needs
an isolated service with enforced tool/network/spending policy, not a Python loop.
"""
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / '.local' / 'upstream' / 'automaton'


def status(probe=False):
    entry = SOURCE / 'dist' / 'index.js'
    built = entry.is_file() and bool(shutil.which('node'))
    result = {'provider': 'Conway-Research/automaton', 'state': 'NOT_CONFIGURED',
              'upstream_installed': built, 'runtime_running': False,
              'execution_authority': False, 'paid_operations': False,
              'reason': 'Runtime built; isolated service and authorized credentials required' if built else 'Official runtime not built'}
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
