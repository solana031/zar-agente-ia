"""Scoped, atomic music-project persistence. Audio is rendered in the browser."""
import json
import os
import re
import threading
from pathlib import Path
from datetime import datetime, timezone
from flask import jsonify, request, session
import secrets
from .user_scope import safe_slug

_lock = threading.RLock()

def directory():
    path = Path(os.environ.get('ZAR_DATA_DIR', '/data')) / 'users' / safe_slug() / 'music_projects'
    path.mkdir(parents=True, exist_ok=True)
    return path

def validate(project):
    if not isinstance(project, dict) or project.get('schema') != 'ZarMusicProject' or project.get('version') != 1:
        raise ValueError('Formato musical no compatible.')
    identifier = project.get('id', '')
    if not isinstance(identifier, str) or not re.fullmatch(r'[a-f0-9-]{36}', identifier):
        raise ValueError('ID inválido.')
    tracks = project.get('tracks')
    if not isinstance(tracks, list) or len(tracks) > 24:
        raise ValueError('Máximo 24 pistas.')
    encoded = json.dumps(project, ensure_ascii=False, allow_nan=False)
    if len(encoded.encode('utf-8')) > 20 * 1024 * 1024:
        raise ValueError('El proyecto supera 20 MB. Reduce assets o exporta tomas por separado.')
    return identifier, encoded

def register(app):
    @app.get('/api/studio/music/projects')
    def music_list():
        rows=[]
        with _lock:
            for path in directory().glob('*.json'):
                try:
                    p=json.loads(path.read_text(encoding='utf-8'))
                    rows.append({k:p.get(k) for k in ('id','name','updated_at','tempo','key','bars')})
                except (ValueError, OSError):
                    continue
        return jsonify(ok=True, projects=sorted(rows,key=lambda p:p.get('updated_at') or '',reverse=True),csrf=session.setdefault('business_csrf',secrets.token_urlsafe(32)))

    @app.route('/api/studio/music/projects/<identifier>', methods=['GET','PUT'])
    def music_project(identifier):
        if not re.fullmatch(r'[a-f0-9-]{36}', identifier):return jsonify(ok=False,error='ID inválido.'),400
        path=directory()/(identifier+'.json')
        if request.method=='GET':
            if not path.is_file():return jsonify(ok=False,error='Proyecto no encontrado.'),404
            return jsonify(ok=True,project=json.loads(path.read_text(encoding='utf-8')))
        token=session.get('business_csrf')
        if not token or not secrets.compare_digest(token,request.headers.get('X-ZAR-Business-CSRF','')):
            return jsonify(ok=False,error='Recarga Studio Audio.'),403
        if request.content_length and request.content_length>20*1024*1024:return jsonify(ok=False,error='Proyecto demasiado grande.'),413
        try:
            p=request.get_json();pid,_=validate(p)
            if pid!=identifier:raise ValueError('ID de proyecto no coincide.')
            p['updated_at']=datetime.now(timezone.utc).isoformat();_,encoded=validate(p)
            with _lock:
                temporary=path.with_suffix('.tmp');temporary.write_text(encoded,encoding='utf-8');temporary.replace(path)
            return jsonify(ok=True,updated_at=p['updated_at'])
        except (ValueError,TypeError):
            return jsonify(ok=False,error='Proyecto inválido o demasiado grande.'),400
