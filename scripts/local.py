"""Local launcher: isolated data, loopback only, no inherited provider secrets."""
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
# Avoid accidentally using connected accounts from a parent shell.
for key in list(os.environ):
    if any(word in key for word in ('API_KEY', 'SECRET', 'TOKEN', 'CREDENTIAL', 'CLIENT_CONFIG')) or key in {
        'ZAR_DATA_DIR', 'ZAR_CONFIG_PATH', 'ZAR_SESSION_SECRET', 'ZAR_ACCESS_PASSWORD',
        'ZAR_CLOUD_URL', 'ZAR_NODE_TOKEN', 'ZAR_CODEX_ENABLED', 'PUBLIC_BASE_URL',
        'DRAMACLAW_API_URL', 'DRAMACLAW_WEB_URL', 'JEV_API_BASE', 'TYPESAFE_API_KEY',
        'ZAR_NODE_CREDENTIALS_JSON', 'RAILWAY_ENVIRONMENT', 'RAILWAY_VOLUME_MOUNT_PATH'}:
        os.environ.pop(key, None)
envfile = ROOT / '.env.local'
if envfile.exists():
    for line in envfile.read_text().splitlines():
        if line.strip() and not line.lstrip().startswith('#'):
            key, value = line.split('=', 1)
            os.environ[key.strip()] = value.strip()
data = ROOT / '.local' / 'data'
data.mkdir(parents=True, exist_ok=True, mode=0o700)
os.environ.update(ZAR_DATA_DIR=str(data), ZAR_CONFIG_PATH=str(data / 'config.json'),
                  ZAR_JOB_DIR=str(data / 'jobs'), ZAR_NODE_DIR=str(ROOT / '.local/node'),
                  PUBLIC_BASE_URL='http://127.0.0.1:8765')
os.environ['PATH'] = str(ROOT / '.local/bin') + os.pathsep + os.environ.get('PATH', '')
mode = sys.argv[1] if len(sys.argv) > 1 else 'web'
if mode == 'web':
    from app.main import app
    from flask import render_template
    # Offline local frontend access. Google status stays disconnected and its
    # actions retain their existing credential/confirmation checks.
    os.environ['ZAR_NODE_CHAT'] = '1'
    os.environ['ZAR_NODES_LOCAL_ADMIN'] = '1'
    app.config['SESSION_COOKIE_SECURE'] = False
    app.view_functions['home'] = lambda: render_template('index.html')
    app.run(host='127.0.0.1', port=int(os.environ.get('PORT', '8765')), use_reloader=False)
elif mode == 'worker':
    from app.node_worker import main
    try:
        main(sys.argv[2:])
    except KeyboardInterrupt:
        pass
elif mode == 'integrations':
    import json
    from app import media_company, jev_decision, conway_adapter, coding_capability
    print(json.dumps({'dramaclaw': media_company.status(), 'jev': jev_decision.status(),
                      'conway': conway_adapter.status(probe=True),
                      'coding-agent': coding_capability.status()}, indent=2))
elif mode == 'coordinator':
    from app.node_coordinator import create_app
    create_app().run(host='127.0.0.1', port=8766, use_reloader=False)
else:
    raise SystemExit('Use web, worker, integrations or coordinator')
