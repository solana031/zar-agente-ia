"""Create/preserve a local secret; output only the public enrollment descriptor."""
import argparse
import json
import os
from contextlib import redirect_stdout
from pathlib import Path
import secrets
import sys
from urllib.parse import urlparse
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
if __name__=='__main__':
    os.environ['ZAR_DATA_DIR'] = str(ROOT/'.local/data')
    os.environ.pop('RAILWAY_ENVIRONMENT',None)
    os.environ.pop('RAILWAY_VOLUME_MOUNT_PATH',None)
with redirect_stdout(sys.stderr):
    from app.node_worker import Worker
    from app.node_coordinator import token_hash


def configure(root, url):
    parsed = urlparse(url)
    if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in {'','/'}:
        raise ValueError('Use the verified Cloud HTTPS origin without credentials or path')
    path = root / '.env.local'
    values = {}; lines = path.read_text().splitlines() if path.exists() else []
    for line in lines:
        if '=' in line and not line.lstrip().startswith('#'):
            key,value = line.split('=',1); values[key.strip()] = value.strip()
    token = values.get('ZAR_NODE_TOKEN') or secrets.token_urlsafe(32)
    digest = token_hash(token)
    updates = {'ZAR_CLOUD_URL':url.rstrip('/'),'ZAR_NODE_TOKEN':token}
    seen = set(); result = []
    for line in lines:
        key = line.split('=',1)[0].strip()
        if key in updates:
            if key not in seen: result.append(key+'='+updates[key]); seen.add(key)
        else: result.append(line)
    result += [key+'='+value for key,value in updates.items() if key not in seen]
    tmp = root / ('.env.local.'+secrets.token_hex(8))
    try:
        fd = os.open(tmp,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'w') as out: out.write('\n'.join(result)+'\n'); out.flush(); os.fsync(out.fileno())
        os.replace(tmp,path)
    finally:
        if tmp.exists(): tmp.unlink()
    identity = Worker(root / '.local/node').identity()
    return {'node_id':identity['id'],'name':identity['name'],'token_hash':digest}


if __name__=='__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--cloud-url',required=True)
    args = parser.parse_args()
    print(json.dumps(configure(ROOT,args.cloud_url)))
