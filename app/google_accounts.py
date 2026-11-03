"""Google accounts linked to one ZAR identity; encrypted tokens never enter views."""
import hashlib
import json
import os
import re
import uuid
from pathlib import Path
from . import holdings, oauth_vault
from .user_scope import safe_slug

def _base():
    from .cloud_auth import DATA_DIR
    return Path(os.environ.get('ZAR_DATA_DIR',str(DATA_DIR)))

def root(scope):
    return _base()/'users'/safe_slug(scope)

def read(scope):
    path=root(scope)/'google_accounts.json'
    if not path.exists():return {'accounts':{},'active':None}
    data=oauth_vault.decode(path.read_text(encoding='utf-8'),_base())
    if not isinstance(data.get('accounts'),dict):raise ValueError('GOOGLE_ACCOUNTS_INDEX_INVALID')
    return data

def _path(scope,key):
    if key=='legacy':return root(scope)/'google_token.json'
    if not re.fullmatch('[a-f0-9]{64}',key or ''):raise ValueError('GOOGLE_ACCOUNT_ID_INVALID')
    return root(scope)/'google_accounts'/(key+'.json')

def active_path(scope):
    data=read(scope)
    key=data.get('active')
    if key and key not in data['accounts']:raise ValueError('GOOGLE_ACCOUNT_NOT_LINKED')
    return _path(scope,key or 'legacy')

def view(scope):
    data=read(scope)
    return [{'id':key,'email':row.get('email'),'active':key==data.get('active'),'verified_at':row.get('verified_at')}
            for key,row in data['accounts'].items()]

def attach(scope,creds,email):
    email=str(email or '').strip().lower()
    if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',email):raise ValueError('GOOGLE_IDENTITY_NOT_VERIFIED')
    base=_base()
    key=hashlib.sha256(email.encode()).hexdigest()
    with holdings.transaction(scope):
        data=read(scope)
        legacy=_path(scope,'legacy')
        if legacy.exists() and not data['accounts']:
            known=holdings.read(scope).get('identity_center',{}).get('google',{}).get('email')
            if known!=email:data['accounts']['legacy']={'email':known,'verified_at':None}
        target=_path(scope,key)
        if target.exists():
            # Preserve the previous grant on explicit reauthorization, too.
            previous=oauth_vault.decode(target.read_text(encoding='utf-8'),base)
            archive=target.parent/'history'/(key+'-'+uuid.uuid4().hex+'.json')
            oauth_vault.persist(archive,json.dumps(previous),base)
            if not creds.refresh_token and previous.get('client_id')==creds.client_id and previous.get('refresh_token'):
                from google.oauth2.credentials import Credentials
                creds=Credentials(token=creds.token,refresh_token=previous['refresh_token'],token_uri=creds.token_uri,
                    client_id=creds.client_id,client_secret=creds.client_secret,scopes=creds.scopes,expiry=creds.expiry)
        oauth_vault.persist(target,creds.to_json(),base)
        data['accounts'][key]={'email':email,'verified_at':holdings._now()}
        data['active']=key
        oauth_vault.persist(root(scope)/'google_accounts.json',json.dumps(data),base)
    return key

def select(scope,key):
    with holdings.transaction(scope):
        data=read(scope)
        if key not in data['accounts'] or not _path(scope,key).exists():raise ValueError('GOOGLE_ACCOUNT_NOT_LINKED')
        data['active']=key
        oauth_vault.persist(root(scope)/'google_accounts.json',json.dumps(data),_base())
