"""Portable local node runner. Reads only node settings, never provider keys."""
import os
from contextlib import redirect_stdout
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
allowed = {'ZAR_CLOUD_URL','ZAR_NODE_TOKEN','ZAR_NODE_NAME','DRAMACLAW_API_URL','ZAR_CODING_LOCAL_MODEL'}
for key in allowed:
    os.environ.pop(key,None)
env = ROOT / '.env.local'
if env.exists():
    for line in env.read_text().splitlines():
        if '=' in line and not line.lstrip().startswith('#'):
            key,value = line.split('=',1)
            if key.strip() in allowed:
                os.environ[key.strip()] = value.strip()
os.environ['ZAR_NODE_DIR'] = str(ROOT / '.local/node')
os.environ['PATH'] = str(ROOT / '.local/bin') + os.pathsep + os.environ.get('PATH','')
os.environ['ZAR_DATA_DIR'] = str(ROOT/'.local/data')
os.environ.pop('RAILWAY_ENVIRONMENT',None)
os.environ.pop('RAILWAY_VOLUME_MOUNT_PATH',None)
with redirect_stdout(sys.stderr):
    from app.node_worker import main
try:
    main(sys.argv[1:])
except KeyboardInterrupt:
    pass
