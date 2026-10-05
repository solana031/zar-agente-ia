"""Trusted Cloud CLI only. Reads a hash descriptor through stdin, never a token."""
import argparse
from contextlib import redirect_stdout
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
with redirect_stdout(sys.stderr):
    from app.node_coordinator import Coordinator

parser = argparse.ArgumentParser()
parser.add_argument('command', choices=['enroll','revoke','test-job','inference-enable','inference-disable'])
parser.add_argument('--node-id')
args = parser.parse_args()
store = Coordinator()
if args.command=='enroll':
    body = json.loads(sys.stdin.read(4096))
    store.provision(body['node_id'],body['name'],body['token_hash'])
    print(json.dumps({'ok':True,'node_id':body['node_id']}))
elif args.command in {'inference-enable','inference-disable'}:
    if not args.node_id: parser.error('--node-id required')
    with store.connect() as con:
        row = con.execute('SELECT revoked FROM distributed_nodes WHERE id=?',(args.node_id,)).fetchone()
        if not row or row['revoked']: raise SystemExit('Node missing or revoked')
        con.execute('UPDATE distributed_nodes SET inference_allowed=? WHERE id=?',(int(args.command=='inference-enable'),args.node_id))
    print(json.dumps({'ok':True,'node_id':args.node_id,'inference_allowed':args.command=='inference-enable'}))
elif args.command=='revoke':
    if not args.node_id: parser.error('--node-id required')
    store.control(args.node_id,'revoke')
    print(json.dumps({'ok':True,'node_id':args.node_id}))
else:
    print(json.dumps(store.submit({'kind':'node-info','timeout':120})))
