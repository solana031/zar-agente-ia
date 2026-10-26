"""Public readiness evidence and owner attestations. Never serves or submits ads."""
import hashlib
import json
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path
from flask import session
from . import holdings

LABELS=('SITE','CONTENT','ADS.TXT','VERIFICATION','PRIVACY','COOKIES','CMP','LEGAL IDENTITY','ACCOUNT INFO','TAX INFO')
ACCOUNT_FIELDS={
 'legal_name':'Nombre legal idéntico al documento fiscal', 'address':'Dirección completa y actual',
 'postcode':'Código postal correcto', 'country':'País correcto', 'phone':'Teléfono, solo si Google lo exige',
 'payment_profile':'Perfil de pagos correcto', 'payee':'Beneficiario correcto',
 'w8ben':'Formulario W-8BEN correcto y vigente, si corresponde', 'tax_id':'TIN extranjero/NIF correcto, si corresponde',
 'tax_residence':'Residencia fiscal: comprobar España o el país real acreditado; no darlo por supuesto',
 'treaty':'Tratado fiscal según el formulario presentado, sin presumir beneficios',
 'no_duplicates':'No existe otra cuenta AdSense duplicada',
 'consistency':'Nombre del beneficiario, perfil de pagos, formulario fiscal y dirección coherentes entre sí'}
TAX_STATUSES={'UNKNOWN','ACCEPTED','IN_REVIEW','PENDING','REJECTED','NOT_APPLICABLE'}
FINDINGS={'PAYEE_NAME_MISMATCH':'Nombre y apellidos del perfil distintos del formulario fiscal',
 'POSTAL_STREET_MISSING':'Calle no visible en el perfil; comprobar Dirección, línea 1',
 'GOOGLE_PROFILE_SAVE_ERROR':'Google devuelve un error al guardar el perfil; corrección no confirmada'}
MESSAGE='Los datos de la cuenta que ha introducido son imprecisos o están incompletos.'
PUBLIC_FIELDS={'controller':'Titular / denominación social','email':'Correo de contacto público','activity':'Actividad',
 'address':'Domicilio o establecimiento exigible','tax_id':'Identificación fiscal exigible',
 'registration':'Registro público, si corresponde','regulated':'Autorización o profesión regulada, si corresponde'}
CMP_STEPS=[
 'Abrir la cuenta AdSense existente. En el onboarding observado no aparece Privacidad y mensajes: resolver primero el aviso de datos de cuenta; no crear otra cuenta.',
 'Cuando esté disponible: Privacidad y mensajes → Normativas europeas → Crear mensaje. Seleccionar reposnews.com y la CMP de Google; configurar consentir, rechazar y gestionar opciones.',
 'Guardar y publicar el mensaje. Activar la compatibilidad con Consent Mode en sus ajustes si está disponible.',
 'Con la etiqueta publicitaria inactiva, hace falta la etiqueta CMP independiente oficial. Si Google facilita esa etiqueta, guardar abajo únicamente su URL pública de Funding Choices para este publisher. No pegar HTML ni habilitar Auto Ads. Si no la facilita, mantener pendiente: publicar un mensaje por sí solo no carga una etiqueta inactiva.',
 'Volver a ZAR y pulsar REVERIFICAR ADSENSE / CMP. Debe detectar TCF cargado, estado legible, cadena presente y CMP Google 300; rechazar también es una decisión válida.']
KEYS=('reposnews-adsense-account-information','reposnews-adsense-certified-cmp','reposnews-adsense-public-legal-review')

def version():return Path(__file__).with_name('VERSION.txt').read_text(encoding='utf-8').strip()
def _owned(scope):
 from . import reposnews as rn
 data=rn.read()
 if not scope or data.get('owner')!=scope:raise ValueError('REPOSNEWS_OWNER_REQUIRED')
 return data

def _auth(scope):
 data=_owned(scope)
 if session.get('zar_auth') is not True:raise ValueError('AUTHENTICATED_OWNER_CONFIRMATION_REQUIRED')
 return data

def fingerprint(data,release=None):
 public=[a.get('published_snapshot',a) for a in data.get('articles',[]) if a.get('published')]
 value={'version':release or version(),'articles':public,'publisher':data.get('publisher'),'legal':data.get('legal'),'reviewed':data.get('legal_reviewed')}
 return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()

def _fresh(value,seconds=3*86400):
 try:return 0<=(datetime.now(timezone.utc)-datetime.fromisoformat(value)).total_seconds()<seconds
 except (ValueError,TypeError):return False

def _audit_valid(audit,data):
 # Carry forward the actual 121 crawl only while fresh and its public inputs match.
 return _fresh(audit.get('checked_at')) and audit.get('fingerprint')==fingerprint(data,audit.get('version'))

def _state(scope):return holdings.read(scope).get('reposnews_adsense',{})
def _store(scope,key,value):
 with holdings.transaction(scope):
  d=holdings.read(scope);d.setdefault('reposnews_adsense',{})[key]=value;holdings.write(scope,d)

def public_config(data):
 publisher=str(data.get('publisher') or '')
 saved=_state(data['owner']) if data.get('owner') else {}
 url=saved.get('cmp_loader','')
 valid=bool(re.fullmatch(r'pub-\d{16}',publisher))
 if url!='https://fundingchoicesmessages.google.com/i/'+publisher+'?ers=1':url=''
 return {'client':'ca-'+publisher if valid else '', 'ads_enabled':False,'cmp_loader':url if valid else ''}

def public_identity(data):
 approved=_state(data['owner']).get('legal_review',{}) if data.get('owner') else {}
 if approved.get('completed_by')!=data.get('owner') or not approved.get('confirmed'):return {}
 return {k:v for k,v in approved.get('PUBLIC_REQUIRED',{}).items() if k in PUBLIC_FIELDS and isinstance(v,str) and v}

def view(scope,data=None):
 from . import reposnews as rn
 data=data if data is not None else rn.read()
 if not scope or data.get('owner')!=scope:return {'status':'UNKNOWN','checklist':{k:'UNKNOWN' for k in LABELS},'ready_for_resubmission':False}
 saved=_state(scope);audit=saved.get('site_audit',{});valid=_audit_valid(audit,data)
 old=audit.get('checks',{})
 aliases={'SITE':'SITE LIVE','VERIFICATION':'ADSENSE CODE'}
 checks={k:old.get(k,old.get(aliases.get(k),'UNKNOWN')) if valid else 'UNKNOWN' for k in LABELS}
 # In 121 this flag described legal identification, not a broken privacy page.
 if valid and checks['PRIVACY']=='ACTION_REQUIRED' and audit.get('summary',{}).get('privacy_legal_review_required'):checks['PRIVACY']='READY'
 proof=saved.get('public_probe',{})
 if proof.get('fingerprint')==fingerprint(data) and _fresh(proof.get('checked_at')):
  checks.update(proof.get('checks',{}))
 cmp=saved.get('cmp_probe',{})
 cmp_current=_fresh(cmp.get('checked_at')) and cmp.get('publisher')==data.get('publisher') and cmp.get('loader')==public_config(data)['cmp_loader']
 cmp_status=cmp.get('status','MISSING') if cmp_current else 'UNKNOWN' if cmp else 'MISSING'
 availability=saved.get('provider_availability',{})
 cmp_waiting=availability.get('cmp')=='WAITING_FOR_ADSENSE_AVAILABILITY' and availability.get('observed_by')==scope and availability.get('publisher')==data.get('publisher') and _fresh(availability.get('checked_at'))
 checks['CMP']='READY' if cmp_status=='READY' else 'WAITING_FOR_ADSENSE_AVAILABILITY' if cmp_waiting else 'ACTION_REQUIRED'
 account=saved.get('account_review',{})
 confirmed=account.get('completed_by')==scope and all(account.get('checks',{}).get(k) is True for k in ACCOUNT_FIELDS)
 observation=saved.get('provider_observation',{})
 latest_observation=bool(observation) and str(observation.get('checked_at',''))>str(account.get('completed_at',''))
 findings=[k for k in observation.get('findings',[]) if k in FINDINGS] if latest_observation else []
 if findings:confirmed=False
 checks['ACCOUNT INFO']='READY' if confirmed else 'ACTION_REQUIRED'
 tax=account.get('tax_status','UNKNOWN') if confirmed else 'UNKNOWN'
 tax_source=account.get('source','NO_CURRENT_W8_ACCEPTANCE_EVIDENCE')
 if latest_observation:
  tax=observation.get('tax_status','UNKNOWN') if observation.get('observed_by')==scope and observation.get('publisher')==data.get('publisher') and _fresh(observation.get('checked_at')) else 'UNKNOWN'
  tax_source=observation.get('source','UNKNOWN')
 checks['TAX INFO']='READY' if tax=='ACCEPTED' else 'NOT_APPLICABLE' if tax=='NOT_APPLICABLE' else 'IN_REVIEW' if tax=='IN_REVIEW' else 'ACTION_REQUIRED' if tax in {'PENDING','REJECTED'} else 'UNKNOWN'
 legal=saved.get('legal_review',{})
 legal_ready=bool(public_identity(data)) and legal.get('economic')=='YES' and (not proof or proof.get('legal_page_present') is True)
 checks['LEGAL IDENTITY']='READY' if legal_ready else 'REVIEW_REQUIRED' if legal else 'ACTION_REQUIRED'
 site_ready=all(checks[k]=='READY' for k in LABELS[:6])
 ready=site_ready and (checks['CMP']=='READY' or cmp_waiting) and legal_ready and confirmed and tax in {'ACCEPTED','NOT_APPLICABLE'}
 return {'status':'READY_FOR_RESUBMISSION' if ready else 'SITE_READY_FOR_ADSENSE' if site_ready else 'ACTION_REQUIRED',
 'site_ready_for_adsense':site_ready,'checklist':checks,'ready_for_resubmission':ready,
 'blockers':[k for k,v in checks.items() if v not in {'READY','NOT_APPLICABLE','WAITING_FOR_ADSENSE_AVAILABILITY'}],
 'checked_at':proof.get('checked_at') or audit.get('checked_at'),'audit_current':valid,
 'account_message':saved.get('account_message',MESSAGE),'account_fields':ACCOUNT_FIELDS,'account_checks':account.get('checks',{}),
 'account_reviewed':confirmed,'account_confirmation':'CONFIRMED_BY_USER' if confirmed else 'ACTION_REQUIRED',
 'tax_status':tax,'tax_evidence':tax_source,'provider_observation_at':observation.get('checked_at'),
 'account_findings':{k:FINDINGS[k] for k in findings},'finding_options':FINDINGS,
 'cmp_note':CMP_STEPS[0],'cmp_steps':CMP_STEPS,'cmp_status':cmp_status,
 'cmp_configuration_status':checks['CMP'],'cmp_availability':availability.get('cmp','UNKNOWN') if cmp_waiting else 'UNKNOWN',
 'cmp_required_for_ad_serving':True,'cmp_required_for_resubmission':False if cmp_waiting else None,
 'cmp_review_policy_source':'https://support.google.com/adsense/answer/7584263','cmp_probe':{k:cmp.get(k) for k in ('api','loaded','readable','cmp_id','event_status','has_tc_string','checked_at')},
 'public_fields':PUBLIC_FIELDS,'legal_review':legal,'cmp_loader':public_config(data)['cmp_loader'],
 'ads':'DISABLED','account_approval':'NOT_VERIFIED','site_approval':'NOT_VERIFIED','submission':'NOT_RESUBMITTED',
 'audit_summary':audit.get('summary',{}) if valid else {}}

def record_public_audit(scope,checks,summary):
 data=_owned(scope)
 allowed_labels=set(LABELS)|{'SITE LIVE','NAVIGATION','ADSENSE CODE','ROBOTS','SITEMAP'}
 if set(checks)-allowed_labels or any(v not in {'READY','ACTION_REQUIRED','UNKNOWN'} for v in checks.values()):raise ValueError('INVALID_AUDIT_CHECKS')
 allowed={'public_pages','articles','checked_urls','broken_internal','content_min_words','content_max_words','publisher_matches','mobile_verified','private_urls_excluded','privacy_legal_review_required'}
 _store(scope,'site_audit',{'checks':checks,'summary':{k:v for k,v in summary.items() if k in allowed},'checked_at':holdings._now(),'fingerprint':fingerprint(data),'version':version()})
 ensure_actions(scope);return view(scope)

def ensure_actions(scope):
 _owned(scope)
 from .notification_center import emit
 result=view(scope)
 account_title='Corregir nombre y comprobar línea 1 de dirección AdSense' if {'PAYEE_NAME_MISMATCH','POSTAL_STREET_MISSING'}<=set(result['account_findings']) else 'Comprobar línea 1 de dirección del perfil AdSense' if 'POSTAL_STREET_MISSING' in result['account_findings'] else 'REVISAR DATOS DE CUENTA ADSENSE'
 descriptions=[(account_title,' · '.join(result['account_findings'].values()) or MESSAGE,{'findings':list(result['account_findings'].values()),'tax_status':result['tax_status'],'checklist':list(ACCOUNT_FIELDS.values()),'instructions':'Revisar en Google, resolver las diferencias entre beneficiario, pagos, formulario y dirección. Aquí solo se registran comprobaciones; no valores privados. No crear otra cuenta ni reenviar.'}),
 ('CONFIGURAR CMP ADSENSE',result['cmp_note'],{'steps':CMP_STEPS}),
 ('CONFIRMAR IDENTIFICACIÓN LEGAL PARA MONETIZACIÓN','Confirmar persona física o sociedad, actividad económica y la identificación pública legalmente exigible.',
 {'PUBLIC_REQUIRED':PUBLIC_FIELDS,'PRIVATE_ADMINISTRATIVE':['documentos fiscales','datos bancarios','perfil de pagos','contactos privados'],
 'instructions':'LSSI art. 10 para actividad económica: titular, domicilio/establecimiento, contacto y NIF; registro/autorización/profesión regulada cuando proceda. Revisar aplicabilidad y autorizar expresamente cada dato público. No importar datos privados.',
 'source':'https://www.boe.es/buscar/act.php?id=BOE-A-2002-13758#a10'})]
 for key,(title,message,details) in zip(KEYS,descriptions):
  emit(scope,'ACCOUNT_CONNECTION',key,title,message,'/?zar_workspace=sites#zarAdsenseReadiness',entity_type='ADSENSE_ACCOUNT',details=details)
 complete=(result['account_reviewed'] and result['tax_status'] in {'ACCEPTED','NOT_APPLICABLE'},result['checklist']['CMP']=='READY',result['checklist']['LEGAL IDENTITY']=='READY')
 from . import identity_center
 with holdings.transaction(scope):
  d=holdings.read(scope);seen=set()
  for row in identity_center.ensure(d)['human_actions']:
   key=row.get('notification_key')
   if key not in KEYS:continue
   if key in seen:row.update(status='DONE',outcome='DUPLICATE');continue
   seen.add(key);i=KEYS.index(key);title,message,details=descriptions[i]
   row.update(title=title,message=message,details=details,priority='CRITICAL' if i==0 else 'P1',deep_link='/?zar_workspace=sites#zarAdsenseReadiness',
    actions=[{'label':'REVISAR','url':'/?zar_workspace=sites#zarAdsenseReadiness'}],status='DONE' if complete[i] else 'WAITING_PROVIDER' if i==1 and result['checklist']['CMP']=='WAITING_FOR_ADSENSE_AVAILABILITY' else 'ACTION_REQUIRED',
    outcome='EVIDENCE_CONFIRMED' if complete[i] else None)
  holdings.write(scope,d)

def confirm_account_review(scope,payload):
 _auth(scope)
 if set(payload)-{'checks','confirmed','tax_status'}:raise ValueError('PERSONAL_ACCOUNT_VALUES_NOT_ACCEPTED')
 checks=payload.get('checks',{});tax=payload.get('tax_status','UNKNOWN')
 if payload.get('confirmed') is not True or set(checks)!=set(ACCOUNT_FIELDS) or any(v is not True for v in checks.values()):raise ValueError('Revisa todos los puntos en Google; no introduzcas valores personales aquí.')
 if tax not in TAX_STATUSES:raise ValueError('INVALID_TAX_STATUS')
 _store(scope,'account_review',{'checks':dict(checks),'tax_status':tax,'completed_by':scope,'completed_at':holdings._now(),'source':'OWNER_ATTESTATION_NOT_GOOGLE_APPROVAL'})
 ensure_actions(scope);return view(scope)

def record_provider_availability(scope,payload):
 data=_auth(scope)
 if set(payload)!={'cmp','account_not_approved','confirmed'} or payload.get('confirmed') is not True:raise ValueError('PROVIDER_AVAILABILITY_CONFIRMATION_REQUIRED')
 if payload.get('cmp') not in {'AVAILABLE','UNKNOWN','WAITING_FOR_ADSENSE_AVAILABILITY'} or type(payload.get('account_not_approved')) is not bool:raise ValueError('INVALID_PROVIDER_AVAILABILITY')
 if payload['cmp']=='WAITING_FOR_ADSENSE_AVAILABILITY' and payload['account_not_approved'] is not True:raise ValueError('ONBOARDING_STATE_REQUIRED')
 _store(scope,'provider_availability',{'cmp':payload['cmp'],'account_not_approved':payload['account_not_approved'],
  'publisher':data.get('publisher'),'observed_by':scope,'checked_at':holdings._now(),'source':'OBSERVED_ADSENSE_ONBOARDING'})
 ensure_actions(scope);return view(scope)


def record_provider_observation(scope,payload):
 data=_auth(scope)
 if set(payload)!={'tax_status','findings','confirmed'} or payload.get('confirmed') is not True:raise ValueError('PROVIDER_OBSERVATION_CONFIRMATION_REQUIRED')
 tax=payload.get('tax_status');findings=payload.get('findings')
 if not isinstance(tax,str) or tax not in TAX_STATUSES or not isinstance(findings,list) or len(findings)>len(FINDINGS) or any(not isinstance(k,str) or k not in FINDINGS for k in findings):raise ValueError('ONLY_STATUS_AND_FINDING_CODES_ACCEPTED')
 _store(scope,'provider_observation',{'tax_status':tax,'findings':list(dict.fromkeys(findings)),
  'publisher':data.get('publisher'),'observed_by':scope,'checked_at':holdings._now(),'source':'OPERATOR_OBSERVATION_OF_GOOGLE_PAYMENTS_NOT_ACCOUNT_APPROVAL'})
 ensure_actions(scope);return view(scope)


def confirm_legal_review(scope,payload):
 _auth(scope)
 if set(payload)-{'entity_type','economic','public','confirmed','applicability_reviewed'}:raise ValueError('PRIVATE_ADMINISTRATIVE_VALUES_NOT_ACCEPTED')
 fields=payload.get('public',{})
 if not isinstance(fields,dict) or set(fields)-set(PUBLIC_FIELDS):raise ValueError('INVALID_PUBLIC_FIELDS')
 if payload.get('entity_type') not in {'PERSON','COMPANY'} or payload.get('economic') not in {'YES','NO'}:raise ValueError('CONFIRM_ENTITY_AND_ECONOMIC_ACTIVITY')
 if payload.get('confirmed') is not True or payload.get('applicability_reviewed') is not True:raise ValueError('PUBLIC_DISCLOSURE_EXPLICIT_CONFIRMATION_REQUIRED')
 clean={}
 for k,v in fields.items():
  if not isinstance(v,str) or len(v)>500 or re.search(r'[<>\x00-\x1f]',v):raise ValueError('INVALID_PUBLIC_VALUE')
  if v.strip():clean[k]=v.strip()
 required={'controller','email','activity'}|({'address','tax_id'} if payload['economic']=='YES' else set())
 if not required<=set(clean) or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',clean.get('email','')):raise ValueError('MISSING_REQUIRED_PUBLIC_IDENTITY')
 if any(v.lower() in {'pendiente','nif aquí','dirección aquí','test','placeholder'} for v in clean.values()):raise ValueError('PLACEHOLDERS_NOT_ACCEPTED')
 _store(scope,'legal_review',{'entity_type':payload['entity_type'],'economic':payload['economic'],'PUBLIC_REQUIRED':clean,
 'PRIVATE_ADMINISTRATIVE':'NOT_IMPORTED','confirmed':True,'completed_by':scope,'completed_at':holdings._now()})
 ensure_actions(scope);return view(scope)

def configure_cmp(scope,payload):
 data=_auth(scope)
 url=payload.get('official_url','')
 expected='https://fundingchoicesmessages.google.com/i/'+str(data.get('publisher',''))+'?ers=1'
 if set(payload)!={'official_url','confirmed'} or payload.get('confirmed') is not True or url not in {'',expected}:raise ValueError('ONLY_OFFICIAL_GOOGLE_CMP_LOADER_FOR_CURRENT_PUBLISHER')
 _store(scope,'cmp_loader',url);ensure_actions(scope);return view(scope)

def start_probe(scope):
 _auth(scope);nonce=secrets.token_urlsafe(32)
 session['adsense_probe']={'nonce':nonce,'scope':scope,'created_at':holdings._now()}
 return {'nonce':nonce,'url':'https://www.reposnews.com/es/#zar-cmp-probe='+nonce}

def _check_public(data):
 """Fixed public origin only. No Google private/tax requests and no redirects."""
 import requests
 from .reposnews import ORIGIN
 checks={};errors=[]
 for path,key in (('/es/','SITE'),('/ads.txt','ADS.TXT'),('/es/legal/','LEGAL_PAGE')):
  try:
   with requests.get(ORIGIN+path,timeout=(4,8),allow_redirects=False,stream=True) as response:
    raw=bytearray()
    for chunk in response.iter_content(16384):
     raw.extend(chunk)
     if len(raw)>1_000_000:raise ValueError('PUBLIC_RESPONSE_TOO_LARGE')
    text=raw.decode('utf-8',errors='replace');ok=response.status_code==200
   if key=='ADS.TXT':ok=ok and text.strip()=='google.com, '+data.get('publisher','')+', DIRECT, f08c47fec0942fa0'
   checks[key]='READY' if ok else 'ACTION_REQUIRED'
   if key=='SITE':
    checks['VERIFICATION']='READY' if ok and re.search(r'<meta\s+name="google-adsense-account"\s+content="'+re.escape('ca-'+str(data.get('publisher','')))+'"',text) else 'ACTION_REQUIRED'
  except (requests.RequestException,ValueError):checks[key]='UNKNOWN';errors.append(key)
 return checks,errors

def finish_probe(scope,payload):
 data=_auth(scope);challenge=session.pop('adsense_probe',{})
 if challenge.get('scope')!=scope or not _fresh(challenge.get('created_at'),180) or not secrets.compare_digest(str(payload.get('nonce','')),challenge.get('nonce','!')):raise ValueError('CMP_PROBE_EXPIRED_OR_INVALID')
 fields={'api','loaded','readable','cmp_id','event_status','has_tc_string','cmp_status'}
 probe=payload.get('probe',{})
 if set(payload)!={'nonce','probe'} or not isinstance(probe,dict) or set(probe)!=fields:raise ValueError('ONLY_SANITIZED_CMP_METADATA_ACCEPTED')
 if any(type(probe[k]) is not bool for k in ('api','loaded','readable','has_tc_string')) or type(probe['cmp_id']) is not int or not 0<=probe['cmp_id']<=65535:raise ValueError('INVALID_CMP_METADATA')
 if probe['event_status'] not in {'','tcloaded','cmpuishown','useractioncomplete'} or probe['cmp_status'] not in {'','stub','loading','loaded','error'}:raise ValueError('INVALID_TCF_STATE')
 ready=all(probe[k] for k in ('api','loaded','readable','has_tc_string')) and probe['cmp_id']==300 and probe['cmp_status']=='loaded' and probe['event_status'] in {'tcloaded','useractioncomplete'}
 checks,errors=_check_public(data);legal_present=checks.pop('LEGAL_PAGE')=='READY'
 _store(scope,'public_probe',{'checks':checks,'legal_page_present':legal_present,'errors':errors,'checked_at':holdings._now(),'fingerprint':fingerprint(data)})
 _store(scope,'cmp_probe',{**probe,'status':'READY' if ready else 'MISSING' if not probe['api'] else 'REVIEW_REQUIRED',
 'publisher':data.get('publisher'),'loader':public_config(data)['cmp_loader'],'checked_at':holdings._now(),'source':'PUBLIC_BROWSER_TCF_PROBE'})
 ensure_actions(scope);return view(scope)
