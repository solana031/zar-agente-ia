"""Persisted Meta restriction evidence and bounded identity-only recovery checks.

An expired token is not evidence that a developer restriction was lifted.
No OAuth, credential writes, subscription changes or publishing occurs here.
"""
import threading
import time
from datetime import datetime, timezone
import requests
from . import holdings

DAY=86400
DEVELOPERS='https://developers.facebook.com/apps/'
SUPPORT='https://developers.facebook.com/support/'
MESSAGE='Meta requiere confirmar la cuenta de desarrollador, pero su flujo de confirmación está fallando.'
_started=False


def api_blocked(error):
    return isinstance(error,dict) and error.get('code')==200 and 'api access blocked' in str(error.get('message','')).lower()


def current(scope):
    from . import reposnews as rn
    if rn.read().get('owner')!=scope:return {}
    saved=holdings.read(scope).get('meta_provider_diagnostic',{})
    cb=rn.read().get('instagram_callback',{})
    # Older callbacks already contain sanitized provider evidence. Never infer
    # developer restrictions from an expired-token response or missing scopes.
    if api_blocked(cb.get('detail',{})) and (not saved.get('resolved_at') or cb.get('checked_at','')>saved['resolved_at']):
        saved={**saved,'api_access_blocked':True,'detected_at':saved.get('detected_at') or cb.get('checked_at')}
    return saved


def observation(scope, evidence):
    """Record operator-observed official UI facts, excluding credentials/PII."""
    from . import reposnews as rn
    if rn.read().get('owner')!=scope:raise ValueError('OWNER_REQUIRED')
    allowed={'account_confirmation_required','confirmation_ui_error','confirmation_flow','app_status','account_status','support_case_status','oauth_recovery_authorized'}
    safe={k:v for k,v in evidence.items() if k in allowed and isinstance(v,(bool,str))}
    if any(isinstance(v,str) and (len(v)>100 or not all(c.isalnum() or c in '_ -.' for c in v)) for v in safe.values()):raise ValueError('UNSAFE_DIAGNOSTIC')
    with holdings.transaction(scope):
        data=holdings.read(scope);diag=current(scope);diag.update(safe,observed_at=holdings._now())
        data['meta_provider_diagnostic']=diag;holdings.write(scope,data)
    return diag


def oauth_recovery(scope, consume=False):
    """One explicitly authorized OAuth attempt; never claims API recovery."""
    with holdings.transaction(scope):
        diag=current(scope)
        available=(diag.get('oauth_recovery_authorized') is True
                   and diag.get('account_confirmation_required') is False
                   and diag.get('confirmation_flow')=='COMPLETED'
                   and not diag.get('oauth_recovery_started_at'))
        if available and consume:
            data=holdings.read(scope)
            from . import reposnews as rn
            previous=rn.read().get('instagram_callback',{})
            if api_blocked(previous.get('detail',{})):
                diag['oauth_recovery_prior_block']={'checked_at':previous.get('checked_at'),'http':400,'code':200,'message':'API access blocked.'}
            diag.update(oauth_recovery_started_at=holdings._now(),oauth_recovery_authorized=False)
            data['meta_provider_diagnostic']=diag;holdings.write(scope,data)
        return available


def identity_recovered(scope):
    """Called only after canonical token persistence and identity readback."""
    with holdings.transaction(scope):
        data=holdings.read(scope);diag=current(scope)
        diag.update(api_access_blocked=False,resolved_at=holdings._now(),
                    probe_result='IDENTITY_VERIFIED',account_confirmation_required=False,confirmation_ui_error=False)
        data['meta_provider_diagnostic']=diag;holdings.write(scope,data)


def mark_blocked(scope):
    with holdings.transaction(scope):
        data=holdings.read(scope);diag=current(scope)
        diag.update(api_access_blocked=True,detected_at=diag.get('detected_at') or holdings._now())
        data['meta_provider_diagnostic']=diag;holdings.write(scope,data)


def blocked_view(scope):
    diag=current(scope)
    if not diag.get('api_access_blocked'):return {}
    reason='DEVELOPER_ACCOUNT_CONFIRMATION_REQUIRED' if diag.get('account_confirmation_required') else 'META_API_ACCESS_BLOCKED'
    message=MESSAGE if diag.get('confirmation_ui_error') else 'Meta requiere confirmar personalmente la cuenta de desarrollador para recuperar el acceso a la API.' if diag.get('account_confirmation_required') else 'Meta bloquea el acceso a su API. Revisa el estado de la cuenta de desarrollador.'
    public={k:diag.get(k) for k in ('account_confirmation_required','api_access_blocked','confirmation_ui_error','confirmation_flow','last_checked','app_status','account_status','support_case_status','probe_http','probe_result')}
    recovery=oauth_recovery(scope)
    if recovery:message='Confirmación de Developers completada. Hay un intento de reconexión autorizado; la API sigue pendiente de verificar.'
    return {'status':'PROVIDER_BLOCKED','provider_blocked':True,'oauth_recovery_available':recovery,'provider':'META','reason':reason,
            'detected_at':diag.get('detected_at'),'retry_after':diag.get('retry_after'),
            'human_action':message,'support_url':SUPPORT,'provider_url':DEVELOPERS,
            'account':'zaragente031','account_identity':'@zaragente031','connected':False,'ready':False,
            'publish_capability':'BLOCKED','capabilities':{'messaging':'PROVIDER_BLOCKED','reel_discovery':'PROVIDER_BLOCKED','publishing':'PROVIDER_BLOCKED'},
            'diagnostic':public}


def probe(scope,manual=False,now=None):
    """One read at most daily, or two manual reads per five-minute window.

    Reserve the attempt under the persistent lock before network I/O, so worker
    restarts and concurrent requests cannot bypass the schedule.
    """
    now=time.time() if now is None else now
    with holdings.transaction(scope):
        data=holdings.read(scope);diag=current(scope)
        if not diag.get('api_access_blocked'):return diag
        attempts=[t for t in diag.get('manual_attempts',[]) if isinstance(t,(int,float)) and t>now-300]
        if diag.get('probe_inflight_until',0)>now:return diag
        if manual and (diag.get('manual_cooldown_until',0)>now or len(attempts)>=2):return diag
        if not manual and diag.get('next_check',0)>now:return diag
        if manual:
            attempts.append(now);diag['manual_attempts']=attempts
            if len(attempts)>=2:diag['manual_cooldown_until']=now+DAY
        diag.update(next_check=now+DAY,probe_inflight_until=now+45,
                    retry_after=datetime.fromtimestamp(now+DAY,timezone.utc).isoformat(),last_checked=holdings._now())
        data['meta_provider_diagnostic']=diag;holdings.write(scope,data)
    from . import reposnews_inbox as inbox
    auth=inbox.credentials();token=auth.get('access_token');http=None;result='NO_VALID_PROBE_CREDENTIAL'
    recovered=False
    if token:
        try:
            response=requests.get('https://graph.instagram.com/v26.0/me',params={'fields':'user_id,username'},headers={'Authorization':'Bearer '+token},timeout=20,allow_redirects=False)
            http=response.status_code;body=response.json()
            recovered=response.ok and body.get('username')=='zaragente031' and str(body.get('user_id') or body.get('id') or '')==str(auth.get('user_id'))
            result='IDENTITY_VERIFIED' if recovered else 'API_ACCESS_BLOCKED' if api_blocked(body.get('error',{})) else 'TOKEN_INVALID_PROVIDER_STATE_UNKNOWN' if http==401 or (body.get('error') or {}).get('code')==190 else 'PROVIDER_STATE_UNKNOWN'
        except (requests.RequestException,ValueError,TypeError,AttributeError):result='PROVIDER_STATE_UNKNOWN'
    with holdings.transaction(scope):
        data=holdings.read(scope);diag=data.get('meta_provider_diagnostic',{})
        diag.update(probe_http=http,probe_result=result,probe_inflight_until=0)
        if recovered:diag.update(api_access_blocked=False,resolved_at=holdings._now(),account_confirmation_required=False,confirmation_ui_error=False)
        data['meta_provider_diagnostic']=diag;holdings.write(scope,data)
    return diag


def daily_check(scope):
    if not blocked_view(scope):return
    diag=probe(scope)
    from .account_connections import AccountConnectionRegistry
    registry=AccountConnectionRegistry(scope)
    item=blocked_view(scope) or {'status':'AUTH_REQUIRED','provider_blocked':False,'provider':'META','account':'zaragente031','human_action':'Meta vuelve a permitir la lectura de identidad. Comprueba o autoriza la conexión.','capabilities':{}}
    item.update(last_verified=diag.get('last_checked'),account_identity='@zaragente031')
    with holdings.transaction(scope):
        data=holdings.read(scope);data.setdefault('account_connections',{})['instagram']=item;holdings.write(scope,data)
    registry.notification('instagram',item)


def start_worker(scope):
    global _started
    if _started:return
    _started=True
    def loop():
        while True:
            try:daily_check(scope)
            except Exception:pass  # No exception text: SDK errors may contain URLs.
            time.sleep(3600)
    threading.Thread(target=loop,name='meta-provider-readonly',daemon=True).start()
