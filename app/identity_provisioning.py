"""Public account provisioning plans; interactive checks always stay with Pablo."""
import re
import secrets
from copy import deepcopy
from . import holdings

PROVIDERS={
 'GOOGLE':('https://accounts.google.com/signup',['Datos reales y fecha de nacimiento','Elegir nombre disponible en Google','Contraseña en Google/gestor seguro','Recovery, teléfono/SMS o CAPTCHA si Google los solicita','Aceptar términos personalmente','Conectar OAuth en ZAR y verificar buzón']),
 'SHOPIFY':('https://www.shopify.com/free-trial',['Alta oficial','Plan/pago y términos humanos','Configurar token servidor y verificar tienda']),
 'STRIPE':('https://dashboard.stripe.com/register',['Alta oficial','Email y KYC humanos','Configurar clave servidor y webhook firmado']),
 'YOUTUBE':('https://www.youtube.com',['Acceder con identidad Google ZAR','Crear/verificar canal personalmente','Conectar OAuth y permisos']),
 'INSTAGRAM':('https://www.instagram.com/accounts/emailsignup/',['Alta oficial','Verificar identidad personalmente','Conectar cuenta profesional y token servidor']),
 'TIKTOK':('https://www.tiktok.com/signup',['Alta oficial','Verificación humana','Conectar aplicación/permissions']),
 'ADSENSE':('https://adsense.google.com/start/',['Acceder con Google ZAR','Verificar titular, sitio y políticas','Configurar OAuth y publisher']),
 'VERCEL':('https://vercel.com/signup',['Alta oficial','Confirmar email y términos','Configurar token servidor']),
}
STATES={'NOT_CREATED','CREATING','HUMAN_ACTION_REQUIRED','VERIFYING','ACTIVE','ERROR','SUSPENDED'}


def ensure(d):return d.setdefault('identity_provisioning',{'base_identity':None,'plans':[]})
def view(scope):return deepcopy(ensure(holdings.read(scope)))


def link_oauth_plan(old_scope,new_scope,email):
    """Keep only the explicitly selected signup plan across Google's scoped login."""
    if old_scope==new_scope:return
    plans=[deepcopy(p) for p in ensure(holdings.read(old_scope))['plans']
           if p.get('service')=='GOOGLE' and p.get('status')=='VERIFYING'
           and p.get('identity')==str(email).strip().lower()]
    if not plans:return
    with holdings.transaction(new_scope):
        d=holdings.read(new_scope);target=ensure(d)['plans'];ids={p['id'] for p in target}
        for plan in plans:
            if plan['id'] not in ids and len(target)<200:target.append(plan)
        holdings.write(new_scope,d)


def alternatives(desired):
    stem=re.sub('[^a-z0-9.]','',str(desired).lower().split('@')[0])[:35].strip('.') or 'zar.business'
    if not stem.startswith('zar'):stem='zar.'+stem
    return [{'email':name+'@gmail.com','availability':'NOT_VERIFIED_BY_GOOGLE'}
            for name in [stem,stem+'.office',stem+'.studio',stem+'.'+secrets.token_hex(2)]]


def operate(scope,action,data):
    from .business_orchestration import ensure as accounts
    allowed={'id','service','objective','identity','desired_name','display_name','notes','confirmed','human_step','secret_reference','recovery_status'}
    if set(data)-allowed:raise ValueError('Solo metadatos públicos; nunca contraseñas ni tokens.')
    if action=='suggest':return {'alternatives':alternatives(data.get('desired_name')),'note':'Google confirma disponibilidad durante el alta.'}
    with holdings.transaction(scope):
        d=holdings.read(scope);state=ensure(d)
        if action=='prepare':
            service=str(data.get('service') or '').upper()
            if service not in PROVIDERS:raise ValueError('Selecciona un proveedor con flujo oficial soportado.')
            email=str(data.get('identity') or state['base_identity'] or '').strip().lower()
            if email and not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',email):raise ValueError('Email válido requerido.')
            url,steps=PROVIDERS[service]
            row={'id':secrets.token_hex(12),'service':service,'identity':email,'display_name':str(data.get('display_name') or 'ZAR')[:100],
                 'desired_name':str(data.get('desired_name') or '')[:100],'objective':str(data.get('objective') or '')[:500],
                 'notes':str(data.get('notes') or '')[:1000],'status':'NOT_CREATED','url':url,'steps':steps,
                 'human_step':None,'oauth_state':'UNVERIFIED','last_verified':None,'recovery_status':'UNKNOWN',
                 'capabilities':[],'created_at':holdings._now(),'events':[]}
            if len(state['plans'])>=200:raise ValueError('Límite de planes alcanzado.')
            state['plans'].append(row)
        else:
            row=next((x for x in state['plans'] if x['id']==data.get('id')),None)
            if not row:raise ValueError('Plan no encontrado.')
            if action=='start':
                row['status']='CREATING';row['events'].append({'status':'CREATING','timestamp':holdings._now()})
                row.update(status='HUMAN_ACTION_REQUIRED',human_step=row['steps'][0],
                           notice='ACCIÓN HUMANA NECESARIA: completa el registro oficial. ZAR no acepta términos ni supera SMS/CAPTCHA/KYC.')
            elif action=='human_completed':
                if data.get('confirmed') is not True or not data.get('identity'):raise ValueError('Confirma creación y email real; esto aún no verifica la cuenta.')
                email=str(data['identity']).strip().lower()
                if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',email):raise ValueError('Email real válido requerido.')
                row.update(identity=email,status='VERIFYING',human_step='Conecta OAuth de esta cuenta y pulsa VERIFICAR',recovery_status=data.get('recovery_status','UNKNOWN'))
            elif action=='verify':
                if row['service'] not in {'GOOGLE','YOUTUBE','ADSENSE'}:raise ValueError('Usa VERIFICAR del nodo proveedor; no inferir alta por un formulario.')
                from . import gmail
                if not gmail.is_connected():row.update(status='HUMAN_ACTION_REQUIRED',human_step='Conectar OAuth real de ZAR',oauth_state='POR CONFIGURAR')
                else:
                    profile=gmail.gmail_status();email=str(profile.get('email') or '').lower()
                    if not row['identity'] or email!=row['identity']:raise ValueError('El buzón conectado no coincide con la identidad ZAR elegida.')
                    # Gmail only proves the Google account, not channel/AdSense approval.
                    if row['service']!='GOOGLE':raise ValueError('Gmail no verifica YouTube/AdSense; usa su nodo específico.')
                    row.update(status='ACTIVE',oauth_state='CONNECTED',last_verified=holdings._now(),human_step=None,capabilities=['gmail_profile_verified','gmail_read_send_checked_on_operation'])
                    state['base_identity']=email
                    from .business_connectors import verification
                    d.setdefault('verified_connectors',{})['Google Identity']=verification('Google Identity','LISTO','Gmail profile matches selected ZAR identity; registration completed by user')
                    inventory=accounts(d)['accounts'];old=next((a for a in inventory if a['provider']=='GOOGLE' and a['identity']==email),None)
                    record={'id':old['id'] if old else secrets.token_hex(12),'provider':'GOOGLE','type':'GOOGLE','identity':email,'email':email,
                            'account_id':email,'display_name':row['display_name'],'status':'ACTIVE','state':'LISTO','secret_reference':'GOOGLE_OAUTH_SCOPED',
                            'secret_ref':'GOOGLE_OAUTH_SCOPED','oauth_state':'CONNECTED','expires_at':None,'last_verified':row['last_verified'],
                            'verified_at':row['last_verified'],'recovery_status':row['recovery_status'],'capabilities':row['capabilities']}
                    if old:old.update(record)
                    else:inventory.append(record)
            elif action=='disconnect':
                if data.get('confirmed') is not True:raise ValueError('Confirma desconectar OAuth de esta identidad; afecta sus módulos Google.')
                from . import gmail,cloud_auth
                if gmail.is_connected():
                    connected_email=str(gmail.gmail_status().get('email') or '').lower()
                    if connected_email!=row['identity']:raise ValueError('No desconectar una identidad distinta de la seleccionada.')
                    token_path=cloud_auth._token_file(scope)
                    if token_path.exists():token_path.unlink()
                row.update(status='SUSPENDED',oauth_state='DISCONNECTED_LOCAL',capabilities=[],human_step='Revoca también el consentimiento OAuth en Google si procede')
                if state['base_identity']==row['identity']:state['base_identity']=None
                from .business_connectors import verification
                for name in ('Google Identity','ZAR Mail'):
                    d.setdefault('verified_connectors',{})[name]=verification(name,'POR CONFIGURAR','Disconnected by user')
                for account in accounts(d)['accounts']:
                    if account.get('identity')==row['identity'] and account.get('provider')=='GOOGLE':account.update(state='POR CONFIGURAR',status='SUSPENDED',oauth_state='DISCONNECTED_LOCAL',capabilities=[])
            else:raise ValueError('Acción de identidad no admitida.')
        row['events'].append({'status':row['status'],'timestamp':holdings._now(),'action':action})
        holdings.write(scope,d);return deepcopy(row)
