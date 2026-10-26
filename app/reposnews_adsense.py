"""Readiness evidence and owner attestations; never submits to AdSense or serves ads."""
import hashlib
import json
import re
from datetime import datetime,timezone
from pathlib import Path
from flask import session
from . import holdings

LABELS=('SITE LIVE','CONTENT','NAVIGATION','PRIVACY','COOKIES','CMP','ADS.TXT','ADSENSE CODE','ROBOTS','SITEMAP','ACCOUNT INFO','TAX INFO')
ACCOUNT_FIELDS={
    'legal_name':'Nombre legal exacto', 'address':'Dirección postal', 'postcode':'Código postal',
    'country':'País', 'phone':'Teléfono', 'tax_details':'Datos fiscales aplicables',
    'payment_profile':'Perfil de pagos', 'payee':'Beneficiario',
    'w8ben':'W-8BEN, si corresponde', 'tax_id':'TIN/NIF, si corresponde',
    'bank_match':'Coincidencia con datos bancarios, cuando corresponda'}
MESSAGE='Los datos de la cuenta que ha introducido son imprecisos o están incompletos.'

def version():return Path(__file__).with_name('VERSION.txt').read_text(encoding='utf-8').strip()

def public_config(data):
    publisher=str(data.get('publisher') or '')
    return {'client':'ca-'+publisher if re.fullmatch(r'pub-\d{16}',publisher) else '',
            'ads_enabled':False,'cmp':'NOT_CONFIGURED'}

def fingerprint(data):
    public=[a.get('published_snapshot',a) for a in data.get('articles',[]) if a.get('published')]
    value={'version':version(),'articles':public,'publisher':data.get('publisher'),'legal':data.get('legal'),'reviewed':data.get('legal_reviewed')}
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()

def _owned(scope):
    from . import reposnews as rn
    data=rn.read()
    if data.get('owner')!=scope:raise ValueError('REPOSNEWS_OWNER_REQUIRED')
    return data

def view(scope,data=None):
    from . import reposnews as rn
    data=data if data is not None else rn.read()
    if not scope or data.get('owner')!=scope:return {'status':'UNKNOWN','checklist':{k:'UNKNOWN' for k in LABELS},'ready_for_resubmission':False}
    saved=holdings.read(scope).get('reposnews_adsense',{});audit=saved.get('site_audit',{})
    fresh=False
    try:fresh=0<=(datetime.now(timezone.utc)-datetime.fromisoformat(audit['checked_at'])).total_seconds()<3*86400
    except (KeyError,ValueError,TypeError):pass
    valid=fresh and audit.get('fingerprint')==fingerprint(data)
    checks={k:(audit.get('checks',{}).get(k,'UNKNOWN') if valid else 'UNKNOWN') for k in LABELS}
    checks['CMP']='ACTION_REQUIRED'  # No certified message is available on the blocked account.
    account=saved.get('account_review',{})
    confirmed=account.get('completed_by')==scope and all(account.get('checks',{}).get(k) is True for k in ACCOUNT_FIELDS)
    checks['ACCOUNT INFO']='READY' if confirmed else 'ACTION_REQUIRED'
    checks['TAX INFO']='READY' if confirmed else 'ACTION_REQUIRED'
    if valid and audit.get('summary',{}).get('privacy_legal_review_required'):checks['PRIVACY']='ACTION_REQUIRED'
    ready=all(v=='READY' for v in checks.values())
    return {'status':'ADSENSE_READY_FOR_RESUBMISSION' if ready else 'ACTION_REQUIRED','checklist':checks,
        'ready_for_resubmission':ready,'blockers':[k for k,v in checks.items() if v!='READY'],
        'checked_at':audit.get('checked_at'),'audit_current':valid,'account_message':saved.get('account_message',MESSAGE),
        'account_fields':ACCOUNT_FIELDS,'account_checks':account.get('checks',{}),'account_reviewed':confirmed,
        'cmp_note':'Configurar una CMP certificada TCF en la cuenta existente. Privacidad y mensajes no está disponible en el onboarding actual.',
        'ads':'DISABLED','submission':'NOT_RESUBMITTED','audit_summary':audit.get('summary',{}) if valid else {}}

def record_public_audit(scope,checks,summary):
    """Operator records the completed public crawl; no financial/personal account values."""
    data=_owned(scope)
    if set(checks)-set(LABELS) or any(v not in {'READY','ACTION_REQUIRED','UNKNOWN'} for v in checks.values()):raise ValueError('INVALID_AUDIT_CHECKS')
    allowed={'public_pages','articles','checked_urls','broken_internal','content_min_words','content_max_words','publisher_matches','mobile_verified','private_urls_excluded','privacy_legal_review_required'}
    with holdings.transaction(scope):
        saved=holdings.read(scope);state=saved.setdefault('reposnews_adsense',{})
        state.update(account_message=MESSAGE,account_observed_at=holdings._now())
        state['site_audit']={'checks':checks,'summary':{k:v for k,v in summary.items() if k in allowed},
            'checked_at':holdings._now(),'fingerprint':fingerprint(data),'version':version()}
        holdings.write(scope,saved)
    ensure_actions(scope)
    return view(scope)

def ensure_actions(scope):
    _owned(scope)
    from .notification_center import emit
    result=view(scope)
    if not result['account_reviewed']:
        emit(scope,'ACCOUNT_CONNECTION','reposnews-adsense-account-information',
            'Revisar información de cuenta AdSense',MESSAGE+' Revisa los datos en Google; no los copies en ZAR.',
            '/?zar_workspace=sites#reposnewsEditor',entity_id='adsense-account-review',entity_type='ADSENSE_ACCOUNT',
            details={'checklist':list(ACCOUNT_FIELDS.values()),'provider_url':'https://adsense.google.com/',
                'instructions':'Reutilizar la cuenta actual. Revisar cada dato y su aplicabilidad. No crear otra cuenta ni volver a enviar automáticamente.'})
    emit(scope,'ACCOUNT_CONNECTION','reposnews-adsense-certified-cmp','Configurar consentimiento certificado para ReposNews',
        result['cmp_note'],'https://adsense.google.com/',entity_id='adsense-cmp-review',entity_type='ADSENSE_ACCOUNT',
        details={'instructions':'Usar Privacidad y mensajes de Google cuando esté disponible: consentir, rechazar y gestionar opciones con visibilidad equivalente. Verificar TCF antes de activar anuncios.'})
    if result.get('audit_summary',{}).get('privacy_legal_review_required'):
        emit(scope,'ACCOUNT_CONNECTION','reposnews-adsense-public-legal-review','Revisar el aviso legal antes de monetizar',
            'Revisar las obligaciones de identificación del titular para la actividad económica. Los datos privados no se publican automáticamente.',
            '/?zar_workspace=sites#reposnewsEditor',entity_id='reposnews-legal-review',entity_type='ADSENSE_ACCOUNT',
            details={'instructions':'Confirmar qué información del titular debe hacerse pública y autorizar los datos exactos. No incluir documentos ni datos bancarios.',
                'source':'https://www.boe.es/buscar/act.php?id=BOE-A-2002-13758#a10'})

def confirm_account_review(scope,payload):
    _owned(scope)
    if session.get('zar_auth') is not True:raise ValueError('AUTHENTICATED_OWNER_CONFIRMATION_REQUIRED')
    if set(payload)-{'checks','confirmed'}:raise ValueError('PERSONAL_ACCOUNT_VALUES_NOT_ACCEPTED')
    checks=payload.get('checks',{})
    if payload.get('confirmed') is not True or set(checks)!=set(ACCOUNT_FIELDS) or any(v is not True for v in checks.values()):
        raise ValueError('Revisa todos los puntos en Google y confirma los que correspondan; no introduzcas valores personales aquí.')
    with holdings.transaction(scope):
        data=holdings.read(scope);data.setdefault('reposnews_adsense',{})['account_review']={
            'checks':dict(checks),'completed_by':scope,'completed_at':holdings._now(),'source':'OWNER_ATTESTATION_NOT_GOOGLE_APPROVAL'}
        from . import identity_center
        for item in identity_center.ensure(data)['human_actions']:
            if item.get('notification_key')=='reposnews-adsense-account-information':item.update(status='DONE',outcome='OWNER_REVIEWED_ACCOUNT_INFORMATION')
        holdings.write(scope,data)
    return view(scope)
