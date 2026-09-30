import os
from app import smart_router

CFG = {
    'api': {'base_url':'https://generativelanguage.googleapis.com/v1beta/openai','api_key':'x','model':'gemini-3.8-flash'},
    'openai': {'base_url':'https://api.openai.com/v1','api_key':'y','economy_model':'gpt-5.6-luna','strong_model':'gpt-5.6-terra','max_model':'gpt-5.6-sol'},
    'local': {'base_url':'http://127.0.0.1:1','model':'qwen3:8b'},
}

def test_economy_default(monkeypatch):
    monkeypatch.setattr(smart_router, 'local_available', lambda cfg: False)
    r = smart_router.choose_brain('Hola, ¿qué tal?', CFG)
    assert (r.tier, r.provider) == ('economy', 'gemini')

def test_balanced_tools(monkeypatch):
    monkeypatch.setattr(smart_router, 'local_available', lambda cfg: False)
    r = smart_router.choose_brain('Busca en Gmail mis últimos correos', CFG)
    assert (r.tier, r.provider) == ('balanced', 'gemini')

def test_strong_code(monkeypatch):
    monkeypatch.setattr(smart_router, 'local_available', lambda cfg: False)
    r = smart_router.choose_brain('Analiza este código Python y optimiza la API', CFG)
    assert (r.tier, r.provider) == ('strong', 'openai')

def test_local_lightweight(monkeypatch):
    monkeypatch.setattr(smart_router, 'local_available', lambda cfg: True)
    r = smart_router.choose_brain('Resume este texto brevemente', CFG)
    assert r.provider == 'local'
