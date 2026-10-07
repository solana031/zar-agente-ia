"""Authenticated encryption for scoped OAuth payloads, server-only key material."""
import json
import os
import threading
from pathlib import Path
from cryptography.fernet import Fernet

_LOCK=threading.RLock()


def cipher(root):
    path=Path(root)/'oauth_vault.key'
    with _LOCK:
        path.parent.mkdir(parents=True,exist_ok=True)
        if not path.exists():
            try:
                fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
                with os.fdopen(fd,'wb') as handle:handle.write(Fernet.generate_key());handle.flush();os.fsync(handle.fileno())
            except FileExistsError:pass
        return Fernet(path.read_bytes())


def encode(payload,root):
    return json.dumps({'format':'ZAR_OAUTH_ENCRYPTED_V1','ciphertext':cipher(root).encrypt(payload.encode()).decode()})


def decode(raw,root):
    value=json.loads(raw)
    if value.get('format')=='ZAR_OAUTH_ENCRYPTED_V1':return json.loads(cipher(root).decrypt(value['ciphertext'].encode()).decode())
    return value


def persist(path,payload,root):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_suffix('.tmp')
    temporary.write_text(encode(payload,root),encoding='utf-8')
    temporary.chmod(0o600);temporary.replace(path)
