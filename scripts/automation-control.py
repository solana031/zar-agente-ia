"""Local human policy/approval tool. Never executes Codex or Conway."""
import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('ZAR_DATA_DIR', str(ROOT / '.local/data'))
from app import automation_control as control
from app.coding_runner import validate

parser = argparse.ArgumentParser()
sub = parser.add_subparsers(dest='command', required=True)
sub.add_parser('status')
kill = sub.add_parser('kill'); kill.add_argument('--enabled', choices=['yes', 'no'], required=True)
approve = sub.add_parser('approve-coding'); approve.add_argument('spec_file')
args = parser.parse_args()
if args.command == 'status':
    print(json.dumps(control.policy(), indent=2))
elif args.command == 'kill':
    print(json.dumps(control.configure({'kill_switch': args.enabled == 'yes'})))
else:
    spec = json.loads(Path(args.spec_file).read_text())
    spec = validate({**spec, 'approval_id': ''})
    if input('Approve this scoped local task for 5 minutes? Type APPROVE: ') != 'APPROVE':
        raise SystemExit('Not approved')
    print(json.dumps({'approval_id': control.approve_locally(spec), 'expires_seconds': 300}))
