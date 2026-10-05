"""Run the official API on loopback. No model requests or credential migration."""
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / '.local/upstream/dramaclaw'
sys.path.insert(0, str(SOURCE / 'src'))
os.chdir(SOURCE)
for key in list(os.environ):
    if any(word in key for word in ('API_KEY', 'SECRET', 'TOKEN', 'CREDENTIAL', 'CLIENT_CONFIG')):
        os.environ.pop(key, None)
os.environ.update(ST_EDITION='ce', NEWAPI_PROVISIONER_ENABLED='false',
                  NOVELVIDEO_DATA_ROOT=str(ROOT / '.local/dramaclaw-data'),
                  LITELLM_LOCAL_MODEL_COST_MAP='True', HF_HUB_OFFLINE='1')
os.environ['PATH'] = str(ROOT / '.local/bin') + os.pathsep + os.environ.get('PATH', '')
import uvicorn
uvicorn.run('novelvideo.api.app:app', host='127.0.0.1', port=8780)
