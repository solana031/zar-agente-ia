"""Local liveness, independent of sessions, editorial storage and connector work."""
import os
import threading
from pathlib import Path
from flask import jsonify, request


def install(app):
    payload = {'status': 'ok', 'version': (Path(__file__).parent / 'VERSION.txt').read_text().strip()}
    commit = os.environ.get('RAILWAY_GIT_COMMIT_SHA', '')
    if commit:
        payload['commit'] = commit

    @app.before_request
    def local_liveness():
        if request.path == '/health':
            response=jsonify(payload)
            response.headers['Cache-Control']='no-store'
            return response


def start_background(target):
    thread = threading.Thread(target=target, name='reposnews-startup', daemon=True)
    thread.start()
    return thread
