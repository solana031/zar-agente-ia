import json, os
from pathlib import Path

CONFIG_PATH = Path(os.environ.get('ZAR_CONFIG_PATH', str(Path(__file__).resolve().parent.parent / 'config.json')))

DEFAULT = {
    'provider': os.environ.get('ZAR_PROVIDER', 'api'),
    'api': {
        'base_url': os.environ.get('ZAR_API_BASE_URL', 'https://generativelanguage.googleapis.com/v1beta/openai'),
        'api_key': os.environ.get('GEMINI_API_KEY', ''),
        'model': os.environ.get('ZAR_API_MODEL', os.environ.get('ZAR_REASONING_MODEL', 'gemini-3.8-flash')),
    },
    'openrouter': {
        'base_url': os.environ.get('OPENROUTER_BASE_URL', 'https://openrouter.ai/api/v1'),
        'api_key': os.environ.get('OPENROUTER_API_KEY', ''),
        'model': os.environ.get('OPENROUTER_MODEL', 'openrouter/free'),
    },
    'local': {
        'base_url': os.environ.get('OLLAMA_BASE_URL', 'http://127.0.0.1:11434'),
        'model': os.environ.get('OLLAMA_MODEL', 'qwen3:8b'),
    },
    'maps': {
        'api_key': os.environ.get('ZAR_MAPS_API_KEY', ''),
    },
}

def load():
    data = {}
    if CONFIG_PATH.exists():
        try:
            data = json.loads(CONFIG_PATH.read_text(encoding='utf-8'))
        except Exception:
            data = {}
    merged = {k:(v.copy() if isinstance(v, dict) else v) for k,v in DEFAULT.items()}
    for section in ('api','openrouter','local','maps'):
        if isinstance(data.get(section), dict):
            merged[section].update(data[section])
    if data.get('provider'):
        merged['provider'] = data['provider']
    # Environment variables are authoritative in cloud deployments.
    for k, env in [('api_key','GEMINI_API_KEY'),('base_url','ZAR_API_BASE_URL'),('model','ZAR_API_MODEL')]:
        if os.environ.get(env): merged['api'][k] = os.environ[env]
    for k, env in [('api_key','OPENROUTER_API_KEY'),('base_url','OPENROUTER_BASE_URL'),('model','OPENROUTER_MODEL')]:
        if os.environ.get(env): merged['openrouter'][k] = os.environ[env]
    if os.environ.get('ZAR_PROVIDER'): merged['provider'] = os.environ['ZAR_PROVIDER']
    if os.environ.get('ZAR_MAPS_API_KEY'): merged['maps']['api_key'] = os.environ['ZAR_MAPS_API_KEY']
    return merged

def save(data):
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    # Never persist API secrets from the browser if env vars are present.
    clean = json.loads(json.dumps(data))
    if os.environ.get('GEMINI_API_KEY'): clean['api']['api_key'] = ''
    if os.environ.get('OPENROUTER_API_KEY'): clean['openrouter']['api_key'] = ''
    CONFIG_PATH.write_text(json.dumps(clean, ensure_ascii=False, indent=2), encoding='utf-8')
    return clean
