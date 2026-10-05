"""Official CE editor; loopback only, API proxy defaults to 127.0.0.1:8780."""
import os
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / '.local/upstream/dramaclaw/frontend'
os.chdir(FRONTEND)
os.environ['VITE_API_URL'] = 'http://127.0.0.1:8780'
node = shutil.which('node')
if not node:
    raise SystemExit('Node is required')
os.execv(node, [node, str(FRONTEND / 'node_modules/vite/bin/vite.js'),
               '--host', '127.0.0.1', '--port', '8781', '--strictPort', '--mode', 'ce'])
