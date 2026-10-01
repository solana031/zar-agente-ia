"""Offline tests: isolate persistence and forbid real HTTP/socket connections."""
import atexit
import os
import tempfile
import socket
import pytest
import requests

_runtime = tempfile.TemporaryDirectory(prefix='zar-tests-')
os.environ['ZAR_DATA_DIR'] = _runtime.name
atexit.register(_runtime.cleanup)

@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('Real network forbidden in automated tests')
    monkeypatch.setattr(requests.sessions.Session, 'send', forbidden)
    monkeypatch.setattr(socket.socket, 'connect', forbidden)
