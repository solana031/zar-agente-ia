"""Existing ZAR identity, verified capabilities and durable human provisioning queue."""
import re
import secrets
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlencode
import requests
from . import holdings

PREFIX='https://www.googleapis.com/auth/'
PROBES={
 'GMAIL':('gmail.modify','https://gmail.googleapis.com/gmail/v1/users/me/profile',{}),
 'DRIVE':('drive.readonly','https://www.googleapis.com/drive/v3/files',{'pageSize':1,'fields':'files(id)'}),
 'CALENDAR':('calendar','https://www.googleapis.com/calendar/v3/users/me/calendarList',{'maxResults':1}),
 'CONTACTS':('contacts','https://people.googleapis.com/v1/people/me/connections',{'personFields':'names','pageSize':1}),
 'TASKS':('tasks.readonly','https://tasks.googleapis.com/tasks/v1/users/@me/lists',{'maxResults':1}),
 'YOUTUBE':('youtube.readonly','https://www.googleapis.com/youtube/v3/channels',{'mine':'true','part':'id,snippet,statistics'}),
 'ADSENSE':('adsense.readonly','https://adsense.googleapis.com/v2/accounts',{'pageSize':20})}
EXTRA={'DOCS':'documents','SHEETS':'spreadsheets','SLIDES':'presentations'}
SERVICES=['GOOGLE','GMAIL','DRIVE','DOCS','SHEETS','SLIDES','CALENDAR','CONTACTS','TASKS','YOUTUBE','ADSENSE',
 'SHOPIFY','STRIPE','INSTAGRAM','TIKTOK','VERCEL','DOMAIN','SUPPLIER','MEDIA','PHONE']

def ensure(d):
    return d.setdefault('identity_center',{'google':{'status':'CREATED','account_exists':True,'email':None,'display_name':'ZAR',
        'last_verified':None,'capabilities':[]},'capabilities':{},'plans':[],'human_actions':[],'mail_audit':[]})

def email(value):
    value=str(value or '').strip().lower()
    if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',value):raise ValueError('Email real de ZAR requerido; nunca contraseña.')
    return value

def queue(state,service,action,reason,url,instructions,plan_id=None):
    old=next((a for a in state['human_actions'] if a['service']==service and a['action']==action and a.get('plan_id')==plan_id and a['status']!='DONE'),None)
    if old:return old
    row={'id':secrets.token_hex(12),'service':service,'action':action,'reason':reason,'url':url,
         'instructions':instructions,'title':service+' · '+action,'status':'ACTION_REQUIRED','plan_id':plan_id,'created_at':holdings._now()}
    state['human_actions'].append(row);return row

def connect_url(address,service='core'):
    return '/connect/google?'+urlencode({'force':1,'purpose':'zar','service':service,'email':address})

def link_identity(old_scope,new_scope,address):
    """Carry only this selected identity's public plans after the scoped OAuth login."""
    if old_scope==new_scope:return
    old=holdings.read(old_scope);source=old.get('identity_center',{})
    if source.get('google',{}).get('email')!=address:return
    with holdings.transaction(new_scope):
        d=holdings.read(new_scope);target=ensure(d)
        from .business_orchestration import ensure as agents
        control=agents(d)
        for plan in source.get('plans',[]):
            if plan['identity']!=address or any(p['service']==plan['service'] and p['identity']==address for p in target['plans']):continue
            target['plans'].append(deepcopy(plan))
            aid='AccountProvisioningAgent:'+plan['service']
            if aid in old.get('orchestration',{}).get('agents',{}):control['agents'].setdefault(aid,deepcopy(old['orchestration']['agents'][aid]))
        known={a['id'] for a in target['human_actions']}
        plan_ids={p['id'] for p in target['plans']}
        for action in source.get('human_actions',[]):
            if action['id'] not in known and action.get('plan_id') in plan_ids:target['human_actions'].append(deepcopy(action))
        holdings.write(new_scope,d)

def register_google(scope,address):
    address=email(address)
    from .business_orchestration import ensure as account_store
    with holdings.transaction(scope):
        d=holdings.read(scope);s=ensure(d)
        previous=s['google'].get('email')
        if previous and previous!=address and s['google']['status']=='ACTIVE':raise ValueError('Desconecta la identidad activa antes de cambiarla.')
        if previous!=address:s['capabilities']={}
        s['google'].update(provider='GOOGLE',email=address,identity=address,display_name='ZAR',account_exists=True,
            status='ACTIVE' if previous==address and s['google']['status']=='ACTIVE' else 'NEEDS_OAUTH')
        accounts=account_store(d)['accounts'];record=next((a for a in accounts if a.get('provider')=='GOOGLE' and a.get('identity')==address),None)
        fields={**s['google'],'id':record['id'] if record else secrets.token_hex(12),'type':'GOOGLE','secret_ref':'GOOGLE_OAUTH_SCOPED','state':'LISTO' if s['google']['status']=='ACTIVE' else 'POR CONFIGURAR'}
        if record:record.update(fields)
        else:accounts.append(fields)
        if s['google']['status']!='ACTIVE':queue(s,'GOOGLE','OAUTH','Cuenta ya creada; falta autorización OAuth',connect_url(address),
              ['Seleccionar '+address,'Autorizar Gmail, Drive, Calendar y Contacts','Volver a ZAR y pulsar VERIFICAR'])
        # Old signup plans must not tell Pablo to create Google again.
        legacy=d.get('identity_provisioning',{})
        for p in legacy.get('plans',[]):
            if p.get('service')=='GOOGLE' and p.get('status')!='ACTIVE':p.update(identity=address,status='VERIFYING',human_step='Cuenta creada: conectar OAuth',steps=['Conectar OAuth de '+address,'Verificar identidad real'])
        holdings.write(scope,d);return deepcopy(s['google'])

def _probe(name,creds):
    scope,url,params=PROBES[name];granted=set(creds.scopes or [])
    alternatives={PREFIX+scope}
    if name=='GMAIL':alternatives|={PREFIX+'gmail.readonly'}
    if name=='DRIVE':alternatives|={PREFIX+'drive',PREFIX+'drive.file'}
    if not granted.intersection(alternatives):return {'status':'NOT_CONNECTED','reason':'Autorizar scope específico','last_verified':None}
    try:
        r=requests.get(url,params=params,headers={'Authorization':'Bearer '+creds.token},timeout=(4,10),allow_redirects=False)
        if not r.ok:return {'status':'NOT_CONNECTED' if r.status_code==401 else 'ERROR','reason':'Proveedor HTTP '+str(r.status_code),'last_verified':holdings._now()}
        data=r.json();result={'status':'CONNECTED','last_verified':holdings._now(),'evidence':'API '+name+' respondió correctamente'}
        if name=='GMAIL':
            result['email']=data.get('emailAddress');result['permissions']=[s[len(PREFIX):] for s in granted if s.startswith(PREFIX+'gmail.')]
            if not result['email']:result.update(status='ERROR',reason='Gmail no confirmó identidad')
        if name=='YOUTUBE':
            rows=data.get('items',[]);result.update(status='CONNECTED' if rows else 'NOT_ELIGIBLE',channel_ids=[r['id'] for r in rows],reason=None if rows else 'No existe canal; crearlo personalmente en YouTube')
            result.update(channels=[{'id':r['id'],'title':r.get('snippet',{}).get('title'),'handle':r.get('snippet',{}).get('customUrl')} for r in rows],
                upload_capability=bool(rows and PREFIX+'youtube.upload' in granted),
                publish_capability='AUTHORIZED_NOT_TESTED' if rows and PREFIX+'youtube.upload' in granted else 'BLOCKED')
        if name=='ADSENSE':
            rows=data.get('accounts',[]);states=[a.get('state','UNKNOWN') for a in rows]
            result.update(status='CONNECTED' if rows else 'NOT_ELIGIBLE',account_state='NO_ACCOUNT' if not rows else 'ACTIVE' if all(x=='READY' for x in states) else 'REJECTED' if any(x in {'REJECTED','DISAPPROVED'} for x in states) else 'PENDING_APPROVAL',accounts=[{'name':a.get('name'),'state':a.get('state')} for a in rows])
        return result
    except Exception:return {'status':'ERROR','reason':'La API no confirmó acceso; no se han realizado escrituras','last_verified':holdings._now()}

def verify_google(scope,services=None):
    from . import cloud_auth
    s=ensure(holdings.read(scope));expected=s['google'].get('email')
    if not expected:raise ValueError('Registra el email de la cuenta Google ya creada.')
    creds=cloud_auth.get_credentials(user_id=scope)
    if not creds:return register_google(scope,expected)
    actual=cloud_auth.get_account_email(creds)
    if actual!=expected:raise ValueError('OAuth pertenece a otra identidad; selecciona el correo real de ZAR.')
    names=[x for x in (services or PROBES) if x in PROBES]
    youtube_creds=cloud_auth.get_credentials(user_id=cloud_auth.youtube_user_id(scope)) if 'YOUTUBE' in names else None
    with ThreadPoolExecutor(max_workers=4) as pool:results=dict(zip(names,pool.map(lambda n:_probe(n,youtube_creds or creds) if n=='YOUTUBE' else _probe(n,creds),names)))
    granted=set(creds.scopes or [])
    for name,permission in EXTRA.items():
        # Scope is available, but these APIs need a document ID or a write to prove operation.
        results[name]={'status':'AVAILABLE' if PREFIX+permission in granted or PREFIX+'drive.file' in granted else 'NOT_CONNECTED',
                       'reason':'Comprobar con un documento autorizado; todavía no se ha creado ninguno','last_verified':None}
    with holdings.transaction(scope):
        d=holdings.read(scope);s=ensure(d);s['capabilities'].update(results)
        if 'ADSENSE' in results:
            cap=results['ADSENSE'];s['adsense_onboarding']={'state':'SIGNUP_REQUIRED' if cap.get('account_state')=='NO_ACCOUNT' else cap.get('account_state','ERROR'),
                'account_state':cap.get('account_state','ERROR'),'email':expected,'url':'https://www.google.com/adsense/start/','last_verified':cap.get('last_verified')}
        s['google'].update(status='ACTIVE',last_verified=holdings._now(),capabilities=[n for n,r in s['capabilities'].items() if r['status']=='CONNECTED'])
        for plan in s['plans']:
            capability=results.get(plan['service'])
            if not capability:continue
            for action in s['human_actions']:
                if action.get('plan_id')!=plan['id'] or action['status']=='DONE':continue
                action['last_checked']=holdings._now()
                if plan['service']=='YOUTUBE' and capability['status']=='NOT_ELIGIBLE':
                    action.update(reason=capability['reason'],instructions=['Abrir YouTube con '+expected,'Crear un canal de ZAR con un nombre permitido; aceptar los términos personalmente o mediante confirmación explícita','CONTINUAR comprobará el canal por API antes de activar el plan'])
                elif plan['service']=='ADSENSE' and capability.get('account_state')=='NO_ACCOUNT':
                    action.update(reason='OAuth y API verificados; Google confirma NO_ACCOUNT',instructions=['Abrir AdSense con '+expected,'Completar alta, sitio real, país y términos con datos confirmados por Pablo','Esperar la aprobación de Google; OAuth no acredita monetización','CONTINUAR verificará la cuenta y su estado real'])
        d.setdefault('identity_provisioning',{})['base_identity']=expected
        _setup_actions(s)
        from .business_orchestration import ensure as account_store
        for a in account_store(d)['accounts']:
            if a.get('provider')=='GOOGLE' and a.get('identity')==expected:a.update(s['google'],state='LISTO')
        for action in s['human_actions']:
            if action['service']=='GOOGLE' and action['action']=='OAUTH':action.update(status='DONE',completed_at=holdings._now())
        from .business_connectors import verification
        d.setdefault('verified_connectors',{})['Google Identity']=verification('Google Identity','LISTO','Google OAuth identity matches selected ZAR email')
        for name,node in [('GMAIL','ZAR Mail'),('YOUTUBE','YouTube'),('ADSENSE','AdSense')]:
            if name in results:
                status=results[name]['status'];d['verified_connectors'][node]=verification(node,'LISTO' if status=='CONNECTED' else 'ERROR' if status=='ERROR' else 'POR CONFIGURAR',results[name].get('evidence',results[name].get('reason','OAuth needs configuration')))
        holdings.write(scope,d);return deepcopy(s)

def require_mail(scope):
    from . import cloud_auth,gmail
    state=ensure(holdings.read(scope));expected=state['google'].get('email')
    if expected:
        profile=gmail.gmail_status()
        if str(profile.get('email','')).lower()!=expected:raise ValueError('El buzón no coincide con la identidad principal de ZAR.')
    return expected

def provider_plan(scope,service):
    from .identity_provisioning import PROVIDERS
    from .business_connectors import inventory
    service=str(service).upper()
    urls={**{k:v[0] for k,v in PROVIDERS.items()},'DOMAIN':'https://vercel.com/domains','SUPPLIER':None,'MEDIA':'https://elevenlabs.io','PHONE':None}
    if service not in urls or service=='GOOGLE':raise ValueError('Proveedor soportado requerido. Google ya existe: conectar OAuth.')
    with holdings.transaction(scope):
        d=holdings.read(scope);s=ensure(d);address=s['google'].get('email')
        if not address:raise ValueError('Registra primero el correo existente de ZAR.')
        old=next((p for p in s['plans'] if p['service']==service and p['identity']==address),None)
        if old:return deepcopy(old)
        node_name={'STRIPE':'Payment','DOMAIN':'Dominio','SUPPLIER':'Proveedor','MEDIA':'ElevenLabs','SHOPIFY':'Shopify','YOUTUBE':'YouTube','ADSENSE':'AdSense','INSTAGRAM':'Instagram','TIKTOK':'TikTok','VERCEL':'Vercel','PHONE':'ZAR Phone'}[service]
        node=next(n for n in inventory(d) if n['name']==node_name)
        existing=next((a for a in d.get('orchestration',{}).get('accounts',[]) if a.get('provider','').upper()==service and a.get('identity')==address),None)
        status='ACTIVE' if node['state']=='LISTO' else 'API_CONFIG' if existing or node.get('configured') else 'HUMAN_ACTION_REQUIRED'
        p={'id':secrets.token_hex(12),'service':service,'identity':address,'display_name':'ZAR','status':status,
           'url':urls[service],'created_at':holdings._now(),'events':['REQUESTED','CHECK_EXISTING','REGISTRATION_PREPARED'],
           'existing_account':bool(existing),'configuration':node.get('configuration',[]),'last_verified':node.get('last_verified')}
        s['plans'].append(p)
        if status!='ACTIVE':queue(s,service,'SETUP','No hay cuenta verificada; comprobar la existente antes de registrar otra',urls[service],
            ['Usar '+address,'Comprobar si ya existe cuenta; no duplicarla','Completar personalmente CAPTCHA, SMS, KYC, términos, plan/pago y datos fiscales cuando aparezcan',
             'Configurar OAuth o secret references en el servicio Railway principal','CONTINUAR verifica configuración; no supone aprobación'],p['id'])
        _setup_actions(s)
        from .business_orchestration import ensure as control
        agents=control(d)['agents'];aid='AccountProvisioningAgent:'+service
        agents[aid]={'id':aid,'name':aid,'domain':'identity','parent':'Identity:'+service,'state':status,'function':'account_provisioning',
            'current_tasks':[p['id']],'last_heartbeat':holdings._now(),'errors':[],'tools':[],'capabilities':['public_plan','human_pause_resume'],'permissions':['local_read']}
        holdings.write(scope,d);return deepcopy(p)

def natural_request(scope,text):
    text=str(text or '')[:1000].upper()
    for alias,name in {'DOMINIO':'DOMAIN','PROVEEDOR':'SUPPLIER','TELÉFONO':'PHONE','TELEFONO':'PHONE'}.items():text=text.replace(alias,name)
    names=[n for n in SERVICES if n not in {'GOOGLE','GMAIL','DRIVE','DOCS','SHEETS','SLIDES','CALENDAR','CONTACTS','TASKS'} and n in text]
    if not names:raise ValueError('Indica un proveedor: Shopify, Stripe, YouTube, AdSense, Instagram, TikTok, Vercel, DOMAIN, SUPPLIER, MEDIA o PHONE.')
    return [provider_plan(scope,n) for n in names]

def _setup_actions(s):
    address=s['google'].get('email') or 'la cuenta Google de ZAR'
    guides={
      'YOUTUBE':('Crear canal YouTube','https://www.youtube.com/account',['Iniciar sesión con '+address,'Crear canal: nombre ZAR Agente IA; handle @zaragente031 si está disponible','Aceptar términos personalmente o con confirmación explícita; volver y pulsar CONTINUAR']),
      'ADSENSE':('CREAR / ACTIVAR ADSENSE','https://www.google.com/adsense/start/',['Usar '+address,'Completar sitio real, términos, datos fiscales y verificación personalmente','CONTINUAR consulta accounts por API; esperar aprobación']),
      'SHOPIFY':('CONFIGURAR SHOPIFY','https://admin.shopify.com',['Configurar SHOPIFY_SHOP_DOMAIN y SHOPIFY_ADMIN_ACCESS_TOKEN únicamente en Railway principal','Pulsar CONTINUAR / VERIFICAR']),
      'STRIPE':('CONFIGURAR STRIPE','https://dashboard.stripe.com/apikeys',['Configurar STRIPE_SECRET_KEY y STRIPE_WEBHOOK_SECRET únicamente en Railway principal','Pulsar CONTINUAR / VERIFICAR'])}
    for a in s['human_actions']:
        if a['service'] not in guides or a['status']=='DONE':continue
        title,url,instructions=guides[a['service']]
        a.update(title=title,url=url,instructions=instructions)
        if a['service']=='YOUTUBE':a.update(suggested_name='ZAR Agente IA',suggested_handle='@zaragente031')
        a['status']='HUMAN_ACTION_REQUIRED'

def view(scope):
    from .business_connectors import inventory
    d=holdings.read(scope);s=deepcopy(ensure(d));_setup_actions(s);nodes=inventory(d)
    s['onboarding']=[{'service':'GOOGLE','status':'CONNECTED' if s['google']['status']=='ACTIVE' else 'ACTION_REQUIRED','account_exists':True,'email':s['google'].get('email')}]
    for name in SERVICES[1:]:
        cap=s['capabilities'].get(name,{});plan=next((p for p in s['plans'] if p['service']==name),{})
        s['onboarding'].append({'service':name,'status':'CONNECTED' if cap.get('status')=='CONNECTED' or plan.get('status')=='ACTIVE' else 'ERROR' if cap.get('status')=='ERROR' else 'ACTION_REQUIRED',
            'capability_status':cap.get('status','NOT_CONNECTED')})
    s['workspace_organization']='NOT_VERIFIED; Gmail does not establish managed Workspace membership'
    s['connect_url']=connect_url(s['google']['email']) if s['google'].get('email') else None
    return s

def operate(scope,action,data):
    if any(k in data for k in ('password','token','access_token','refresh_token','secret')):raise ValueError('Solo metadatos públicos y referencias; nunca credenciales.')
    if action=='register':return register_google(scope,data.get('email'))
    if action=='verify':return verify_google(scope)
    if action=='request':return natural_request(scope,data.get('request'))
    if action=='prepare':return provider_plan(scope,data.get('service'))
    if action=='youtube_validate':
        from .media_adapters import PublishingAdapter
        return PublishingAdapter().prepare_youtube(scope,title=data.get('title','Historia ZAR'),description=data.get('description',''),privacy=data.get('privacy','private'))
    if action=='refresh':
        from .cloud_auth import get_credentials
        get_credentials(user_id=scope);return verify_google(scope)
    if action=='revoke':
        from . import cloud_auth
        if data.get('confirmed') is not True:raise ValueError('Confirma revocar Google OAuth; afecta a todos sus módulos.')
        creds=cloud_auth.get_credentials(auto_refresh=False,user_id=scope)
        if creds:
            r=requests.post('https://oauth2.googleapis.com/revoke',data={'token':creds.refresh_token or creds.token},timeout=15)
            if r.status_code!=200 and not (r.status_code==400 and r.json().get('error')=='invalid_token'):raise ValueError('Google no confirmó revocación; conservar referencia local y reintentar.')
        path=cloud_auth._token_file(scope)
        if path.exists():path.unlink()
        youtube_path=cloud_auth._token_file(cloud_auth.youtube_user_id(scope))
        if youtube_path.exists():youtube_path.unlink()
        with holdings.transaction(scope):
            d=holdings.read(scope);s=ensure(d);s['google'].update(status='NEEDS_OAUTH',capabilities=[]);s['capabilities']={}
            d.setdefault('identity_provisioning',{})['base_identity']=None
            from .business_connectors import verification
            for n in ('Google Identity','ZAR Mail','YouTube','AdSense'):d.setdefault('verified_connectors',{})[n]=verification(n,'POR CONFIGURAR','Google OAuth revoked')
            for a in d.get('orchestration',{}).get('accounts',[]):
                if a.get('provider')=='GOOGLE' and a.get('identity')==s['google'].get('email'):a.update(status='NEEDS_OAUTH',state='POR CONFIGURAR',capabilities=[])
            holdings.write(scope,d)
        return view(scope)
    if action=='continue':
        with holdings.transaction(scope):
            d=holdings.read(scope);s=ensure(d);a=next((x for x in s['human_actions'] if x['id']==data.get('id')),None)
            if not a:raise ValueError('Acción humana no encontrada.')
            if a['status']=='DONE':return deepcopy(a)
            service=a['service'];plan_id=a.get('plan_id')
        if service=='GOOGLE':return verify_google(scope)
        from .business_workflows import operate as workflow
        operations={'SHOPIFY':'commerce_shopify_sync','STRIPE':'agency_payment_probe','YOUTUBE':None,'ADSENSE':None}
        result=None
        if service in {'YOUTUBE','ADSENSE'}:result=verify_google(scope,services=[service])['capabilities'].get(service,{})
        elif operations.get(service):result=workflow(scope,operations[service],{})
        from .business_connectors import inventory
        name={'SHOPIFY':'Shopify','STRIPE':'Payment','YOUTUBE':'YouTube','ADSENSE':'AdSense'}.get(service)
        verified=bool(name and next(n for n in inventory(holdings.read(scope)) if n['name']==name)['state']=='LISTO')
        if service=='ADSENSE':verified=verified and result.get('account_state')=='ACTIVE'
        with holdings.transaction(scope):
            d=holdings.read(scope);s=ensure(d);a=next(x for x in s['human_actions'] if x['id']==data['id']);a.update(status='DONE' if verified else 'ACTION_REQUIRED',last_checked=holdings._now())
            plan=next((p for p in s['plans'] if p['id']==plan_id),None)
            if plan:plan.update(status='ACTIVE' if verified else 'API_CONFIG');plan['events'].append('VERIFY')
            if verified and plan:
                accounts=d.get('orchestration',{}).setdefault('accounts',[])
                account=next((x for x in accounts if x.get('provider')==service and x.get('identity')==plan['identity']),None)
                fields={'provider':service,'type':service,'identity':plan['identity'],'display_name':'ZAR','status':'ACTIVE','state':'LISTO','last_verified':holdings._now(),'secret_ref':'SCOPED_YOUTUBE_OAUTH' if service=='YOUTUBE' else service+'_SERVER_CONFIGURATION'}
                if service=='YOUTUBE':fields['channel_ids']=result.get('channel_ids',[])
                if account:account.update(fields)
                else:accounts.append({'id':secrets.token_hex(12),**fields})
            agent=d.get('orchestration',{}).get('agents',{}).get('AccountProvisioningAgent:'+service)
            if agent:agent.update(state='ACTIVE' if verified else 'ACTION_REQUIRED',last_heartbeat=holdings._now())
            holdings.write(scope,d);return deepcopy(a)
    raise ValueError('Acción Identity no soportada.')
