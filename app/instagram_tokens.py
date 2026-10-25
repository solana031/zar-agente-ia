"""Official Instagram Login token lifecycle. No publishing, no browser credentials."""
import hashlib
import hmac
import json
import os
import re
import time
from datetime import datetime, timezone, timedelta
from . import holdings, reposnews as rn, oauth_vault
import requests
from cryptography.fernet import InvalidToken

DAY=86400
DOCS='https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-instagram-login/business-login'


class TokenError(ValueError):
    def __init__(self,code,detail=None):
        super().__init__(code);self.detail=detail or {}


def stamp(epoch=None):
    return datetime.fromtimestamp(time.time() if epoch is None else epoch,timezone.utc).isoformat()


def epoch(value):
    try:return datetime.fromisoformat(str(value).replace('Z','+00:00')).timestamp()
    except (ValueError,TypeError,OverflowError):return None


def path():return rn._path().parent/'instagram-oauth'
def state_path():return rn._path().parent/'instagram-token-lifecycle.json'


def canonical():
    try:return oauth_vault.decode(path().read_text(encoding='utf-8'),rn._path().parent)
    except (OSError,ValueError,InvalidToken):return {}


def _state():
    try:return json.loads(state_path().read_text(encoding='utf-8'))
    except (OSError,ValueError):return {}


def _write_state(value):
    p=state_path();p.parent.mkdir(parents=True,exist_ok=True)
    tmp=p.with_suffix('.tmp')
    with tmp.open('w',encoding='utf-8') as handle:
        handle.write(json.dumps(value));handle.flush();os.fsync(handle.fileno())
    tmp.chmod(0o600);tmp.replace(p)


def classify(detail):
    code=detail.get('code');sub=detail.get('subcode')
    named={463:'EXPIRED_TOKEN',467:'INVALID_TOKEN',458:'AUTHORIZATION_REMOVED',460:'PASSWORD_CHANGED'}
    if sub in named:return named[sub]
    if code==190 and re.search(r'session has expired|token has expired|access token.*expired',detail.get('message',''),re.I):return 'EXPIRED_TOKEN'
    return 'INVALID_TOKEN' if code==190 else 'PROVIDER_AUTH_ERROR_UNCLASSIFIED'


def reported_expiry(detail):
    match=re.search(r'Session has expired on (\w+, \d{1,2}-\w{3}-\d{2} \d{2}:\d{2}:\d{2}) (PDT|PST)',detail.get('message',''))
    if not match:return None
    try:
        value=datetime.strptime(match[1],'%A, %d-%b-%y %H:%M:%S')
        return value.replace(tzinfo=timezone(timedelta(hours=-7 if match[2]=='PDT' else -8))).astimezone(timezone.utc).isoformat()
    except ValueError:return None


def safe_metadata(record):
    keys=('issued_at','authorization_started_at','verified_at','identity_verified_at','expires_at','expires_in',
          'renew_after','refresh_not_before','token_type','token_class','renewable','acquired_by','expiry_evidence','requested_permissions','granted_permissions','username')
    return {k:record.get(k) for k in keys}|{'credential_source':'CANONICAL_OAUTH' if path().exists() else 'UNAVAILABLE',
        'user_id_present':bool(record.get('user_id'))}


def state_for(record,now=None):
    now=time.time() if now is None else now;expires=epoch(record.get('expires_at'));renew=epoch(record.get('renew_after'))
    if not record.get('access_token'):return 'REAUTH_REQUIRED'
    if expires is not None and expires<=now:return 'REAUTH_REQUIRED'
    if renew is not None and renew<=now:return 'TOKEN_EXPIRING_SOON'
    return 'CONNECTED'


def diagnostic(event,metadata,detail=None):
    # Safe allowlisted observations only. Never preserve old access tokens or hashes here.
    with holdings.transaction('reposnews-editorial'):
        d=rn.read();history=d.setdefault('instagram_token_history',[])
        history.append({'event':event,'at':holdings._now(),'metadata':safe_metadata(metadata),'detail':detail or {}})
        d['instagram_token_history']=history[-50:];rn.write(d)


def normalize_response(body):
    if isinstance(body,dict) and isinstance(body.get('data'),list):body=next(iter(body['data']),{})
    if not isinstance(body,dict) or not isinstance(body.get('access_token'),str) or not body['access_token']:
        raise TokenError('INSTAGRAM_TOKEN_RESPONSE_INVALID')
    return body


def _request(endpoint,params):
    from .reposnews_inbox import safe_meta_error
    try:r=requests.get('https://graph.instagram.com/'+endpoint,params=params,timeout=(5,25),allow_redirects=False)
    except requests.RequestException:raise TokenError('INSTAGRAM_TOKEN_PROVIDER_UNAVAILABLE') from None
    if not r.ok:
        detail=safe_meta_error(r,params.get('access_token',''))
        # This request includes an app secret only server-side; strip it even from malformed errors.
        from .secret_safety import redact_text
        detail['message']=redact_text(detail.get('message',''),[os.environ.get('INSTAGRAM_APP_SECRET','')])
        raise TokenError('INSTAGRAM_TOKEN_HTTP_'+str(r.status_code),detail)
    try:return normalize_response(r.json())
    except (ValueError,TypeError):raise TokenError('INSTAGRAM_TOKEN_RESPONSE_INVALID') from None


def _long_metadata(body,base,method):
    seconds=body.get('expires_in')
    if type(seconds) not in (int,float) or not DAY<seconds<=90*DAY:raise TokenError('INSTAGRAM_LONG_LIVED_LIFETIME_NOT_CONFIRMED')
    now=time.time();record=dict(base,access_token=body['access_token'],token_type=body.get('token_type','bearer'),
        token_class='LONG_LIVED',renewable=True,issued_at=stamp(now),expires_in=seconds,expires_at=stamp(now+seconds),
        refresh_not_before=stamp(now+DAY),renew_after=stamp(max(now+DAY,now+seconds-7*DAY)),acquired_by=method,expiry_evidence='META_EXPIRES_IN')
    return record


def exchange_short(token,authorization_started_at=None):
    short=normalize_response(token);secret=os.environ.get('INSTAGRAM_APP_SECRET','')
    if not secret:raise TokenError('INSTAGRAM_APP_SECRET_REQUIRED')
    body=_request('access_token',{'grant_type':'ig_exchange_token','client_secret':secret,'access_token':short['access_token']})
    permissions=short.get('permissions',[])
    if isinstance(permissions,str):permissions=[p.strip() for p in permissions.split(',') if p.strip()]
    return _long_metadata(body,{'authorization_started_at':authorization_started_at or stamp(),
        'granted_permissions':permissions if isinstance(permissions,list) else []},'IG_EXCHANGE_TOKEN')


def _identity(record):
    from .reposnews_inbox import safe_meta_error
    try:r=requests.get('https://graph.instagram.com/v26.0/me',params={'fields':'user_id,username'},
        headers={'Authorization':'Bearer '+record['access_token']},timeout=(5,20),allow_redirects=False)
    except requests.RequestException:raise TokenError('INSTAGRAM_IDENTITY_UNAVAILABLE') from None
    if not r.ok:raise TokenError('INSTAGRAM_IDENTITY_NOT_VERIFIED',safe_meta_error(r,record['access_token']))
    try:who=r.json()
    except ValueError:raise TokenError('INSTAGRAM_IDENTITY_RESPONSE_INVALID') from None
    if not isinstance(who,dict):raise TokenError('INSTAGRAM_IDENTITY_RESPONSE_INVALID')
    uid=str(who.get('user_id') or who.get('id') or '')
    if who.get('username')!='zaragente031' or not re.fullmatch(r'[0-9]+',uid) or record.get('user_id') and str(record['user_id'])!=uid:
        raise TokenError('INSTAGRAM_IDENTITY_MISMATCH')
    return uid


def promote(record,expected_token=None):
    record=dict(record)
    if record.get('token_class')!='LONG_LIVED' or record.get('acquired_by') not in {'IG_EXCHANGE_TOKEN','IG_REFRESH_TOKEN'} or epoch(record.get('expires_at')) is None:
        raise TokenError('INSTAGRAM_LONG_LIVED_EXCHANGE_REQUIRED')
    if state_for(record)=='REAUTH_REQUIRED':raise TokenError('INSTAGRAM_TOKEN_EXPIRED')
    # Provider I/O must never run while holding holdings/file locks.
    record.update(user_id=_identity(record),username='zaragente031',identity_verified_at=stamp(),verified_at=stamp())
    loaded=_persist_verified(record,expected_token)
    diagnostic('LONG_LIVED_CREDENTIAL_PERSISTED',record)
    return loaded


def _persist_verified(record,expected_token):
    proof={'NEW_TOKEN_PERSISTED':False,'NEW_TOKEN_READBACK':False,'STALE_SOURCE_SELECTED':False,
        'checked_at':stamp(),'credential_issued_at':record['issued_at'],'source':'CANONICAL_OAUTH'}
    try:return _replace_and_readback(record,expected_token,proof)
    finally:
        if proof['NEW_TOKEN_PERSISTED']:
            with holdings.transaction('reposnews-editorial'):
                d=rn.read();old=d.get('instagram_credential_diagnostic')
                if old and old.get('credential_issued_at','')>proof['credential_issued_at']:
                    d.setdefault('instagram_credential_diagnostic_history',[]).append(proof)
                else:
                    if old:d.setdefault('instagram_credential_diagnostic_history',[]).append(old)
                    d['instagram_credential_diagnostic']=proof
                d['instagram_credential_diagnostic_history']=d.get('instagram_credential_diagnostic_history',[])[-30:]
                rn.write(d)


def _replace_and_readback(record,expected_token,proof):
    with holdings.transaction('instagram-oauth'):
        previous=canonical()
        if expected_token is not None and not hmac.compare_digest(previous.get('access_token',''),expected_token):
            raise TokenError('INSTAGRAM_TOKEN_REFRESH_SUPERSEDED')
        before=previous.get('authorization_started_at') or previous.get('issued_at','')
        after=record.get('authorization_started_at') or record.get('issued_at','')
        if before>after:raise TokenError('OAUTH_CALLBACK_SUPERSEDED')
        oauth_vault.persist(path(),json.dumps(record),rn._path().parent)
        proof['NEW_TOKEN_PERSISTED']=True
        loaded=canonical()
        same=hmac.compare_digest(hashlib.sha256(record['access_token'].encode()).digest(),hashlib.sha256(loaded.get('access_token','').encode()).digest())
        proof['STALE_SOURCE_SELECTED']=not same
        if not same or loaded.get('user_id')!=record['user_id']:raise TokenError('PERSISTENT_CREDENTIAL_MISMATCH')
    # Verify the persisted credential through the provider, outside storage locks.
    _identity(loaded)
    with holdings.transaction('instagram-oauth'):
        if not hmac.compare_digest(canonical().get('access_token',''),loaded['access_token']):
            raise TokenError('INSTAGRAM_TOKEN_REFRESH_SUPERSEDED')
        (rn._path().parent/'instagram-oauth-pending').unlink(missing_ok=True)
        _write_state({'credential_issued_at':record['issued_at'],'status':'CONNECTED','next_daily_check':time.time()+DAY,
            'renew_after':record['renew_after'],'last_persisted_at':stamp()})
        proof['NEW_TOKEN_READBACK']=True
    return loaded


def adopt_legacy():
    d=rn.read();sync=d.get('instagram_conversation_sync',{});detail=sync.get('provider_error') or {}
    with holdings.transaction('instagram-oauth'):
        record=canonical()
        if not record or record.get('token_class') or not record.get('identity_verified_at'):return record
        # All historical writes used the authorization-code response directly, without exchange.
        record.update(token_class='SHORT_LIVED',renewable=False,acquired_by='LEGACY_CODE_EXCHANGE_WITHOUT_LONG_EXCHANGE',
            authorization_started_at=record.get('issued_at'))
        expiry=reported_expiry(detail);failed=epoch(sync.get('started_at'));issued=epoch(record.get('issued_at'))
        if detail.get('code')==190 and expiry and issued is not None and failed is not None and failed>=issued and epoch(expiry)>=issued:
            record.update(expires_at=expiry,expiry_evidence='META_EXPIRED_SESSION_ERROR')
        oauth_vault.persist(path(),json.dumps(record),rn._path().parent)
    diagnostic('LEGACY_TOKEN_FORENSICS',record,{'root_cause':'TOKEN_NOT_LONG_LIVED','observed_cause':classify(detail)})
    return record


def tick(scope):
    record=adopt_legacy()
    if not record:return
    now=time.time()
    with holdings.transaction('instagram-oauth'):
        latest=canonical()
        if not hmac.compare_digest(latest.get('access_token',''),record.get('access_token','')):return
        state=_state()
        if state.get('next_daily_check',0)>now or state.get('inflight_until',0)>now:return
        state.update(next_daily_check=now+DAY,inflight_until=now+120,status=state_for(record,now));_write_state(state)
    result=state_for(record,now)
    try:
        if result=='REAUTH_REQUIRED':raise TokenError('INSTAGRAM_TOKEN_EXPIRED')
        if record.get('token_class')=='SHORT_LIVED':
            upgraded=exchange_short({'access_token':record['access_token']},record.get('authorization_started_at'))
            upgraded.update(user_id=record.get('user_id'),username=record.get('username'),requested_permissions=record.get('requested_permissions',[]))
            promote(upgraded,expected_token=record['access_token']);result='CONNECTED';return
        if result!='TOKEN_EXPIRING_SOON':return
        if record.get('token_class')!='LONG_LIVED' or epoch(record.get('refresh_not_before')) is None or epoch(record['refresh_not_before'])>now:
            return
        body=_request('refresh_access_token',{'grant_type':'ig_refresh_token','access_token':record['access_token']})
        refreshed=_long_metadata(body,record,'IG_REFRESH_TOKEN')
        promote(refreshed,expected_token=record['access_token']);result='CONNECTED'
        diagnostic('TOKEN_RENEWED',refreshed)
    except TokenError as exc:
        cause=classify(exc.detail)
        result='REAUTH_REQUIRED' if str(exc)=='INSTAGRAM_TOKEN_EXPIRED' or cause in {'EXPIRED_TOKEN','INVALID_TOKEN','AUTHORIZATION_REMOVED','PASSWORD_CHANGED'} else 'TOKEN_EXPIRING_SOON'
        diagnostic('TOKEN_RENEWAL_PENDING' if result!='REAUTH_REQUIRED' else 'TOKEN_REAUTH_REQUIRED',record,
            {'error':str(exc),'cause':cause,'http':exc.detail.get('http')})
    finally:
        with holdings.transaction('instagram-oauth'):
            current=canonical()
            unchanged=current.get('issued_at')==record.get('issued_at') and hmac.compare_digest(current.get('access_token',''),record.get('access_token',''))
            if unchanged:
                state=_state();state.update(status=result,inflight_until=0);_write_state(state)
        if result=='REAUTH_REQUIRED' and unchanged:
            with holdings.transaction(scope):
                d=holdings.read(scope);item=d.setdefault('account_connections',{}).setdefault('instagram',{})
                item.update(status='REAUTH_REQUIRED',ready=False,connected=False,human_action='Reconectar Instagram @zaragente031: la autorización anterior ha caducado.')
                holdings.write(scope,d)
            from .account_connections import AccountConnectionRegistry
            AccountConnectionRegistry(scope).notification('instagram',item)


def resume_after_recovery(scope):
    with holdings.transaction('reposnews-editorial'):
        d=rn.read()
        if d.get('owner')!=scope:return
        sync=d.setdefault('instagram_conversation_sync',{})
        # Keep cursors, completed pages, and any outstanding provider rate-limit backoff.
        sync['requested']=True;rn.write(d)


def confirm_capabilities(permissions,expected_token):
    with holdings.transaction('instagram-oauth'):
        record=canonical()
        if record.get('token_class')!='LONG_LIVED' or not hmac.compare_digest(record.get('access_token',''),expected_token):return
        record.update(granted_permissions=sorted({p for p in permissions if isinstance(p,str) and p.startswith('instagram_business_')}),
            capabilities_verified_at=stamp())
        oauth_vault.persist(path(),json.dumps(record),rn._path().parent)
