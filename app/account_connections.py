"""Global account view over ZAR's existing scoped identity/provider adapters.

GET serves safe persisted observations. Explicit reverify performs status reads;
it cannot publish, send messages, place orders or modify provider resources.
"""
import os
import secrets
from dataclasses import dataclass
from flask import abort, jsonify, render_template, request, session
from . import holdings, identity_center

GOOD={'CONNECTED','UPLOAD_READY','PARTIAL'}
ATTENTION={'AUTH_REQUIRED','REAUTH_REQUIRED','PERMISSION_REQUIRED','CHANNEL_REQUIRED','DISCONNECTED','ERROR','PARTIAL'}


@dataclass(frozen=True)
class Provider:
    id: str
    name: str
    category: str
    icon: str
    used_by: tuple
    adapter: object
    kind: str='USER_ACCOUNT'


def google(scope):
    from . import cloud_auth
    creds=cloud_auth.get_credentials(user_id=scope)
    if not creds:return {'status':'AUTH_REQUIRED','human_action':'Autoriza tu cuenta Google en el flujo existente.'}
    actual=cloud_auth.get_account_email(creds)
    if not actual:return {'status':'REAUTH_REQUIRED','human_action':'Google necesita volver a autorizarse.'}
    state=identity_center.verify_google(scope,services=['GMAIL','DRIVE','CALENDAR','CONTACTS','TASKS'])
    # This adapter reuses existing proofs; it never creates documents to test access.
    caps=state.get('capabilities',{})
    proof=holdings.read(scope).get('workspace_tests',{}).get('FORMS',{})
    caps=dict(caps,FORMS=proof)
    capabilities={name:('READY' if caps.get(name,{}).get('status')=='CONNECTED' else 'PERMISSION_REQUIRED' if caps.get(name,{}).get('status')=='NOT_CONNECTED' else 'UNKNOWN') for name in ('GMAIL','DRIVE','DOCS','SHEETS','SLIDES','FORMS','CALENDAR','CONTACTS','TASKS')}
    complete=all(v=='READY' for v in capabilities.values())
    return {'status':'CONNECTED' if complete else 'PARTIAL','connected':True,'account':actual,'capabilities':capabilities,
            'human_action':None if complete else 'Cuenta conectada; algunos servicios necesitan permisos o una comprobación con un documento autorizado.'}


def social(scope,provider):
    if provider=='instagram':
        from . import reposnews as rn, reposnews_inbox as inbox
        if rn.read().get('owner')==scope:inbox.recover_pending_identity()
    from .text_video_social import _provider_connections
    result=_provider_connections(scope,[provider])[provider]
    if provider=='instagram':
        from . import reposnews as rn
        result['diagnostic']={**result.get('diagnostic',{}),**rn.read().get('instagram_credential_diagnostic',{}),'selected_source':result.get('credential_source'),'legacy_env':'LEGACY_STALE_NOT_SELECTED' if result.get('credential_source')=='CANONICAL_OAUTH' and os.environ.get('INSTAGRAM_ACCESS_TOKEN') else 'LEGACY_FALLBACK' if result.get('credential_source')=='LEGACY_ENV' else 'NOT_SELECTED'}
        if result.get('connected'):
            result['status']='UPLOAD_READY' if result.get('ready') else 'PARTIAL'
            result['human_action']=None if result.get('ready') else 'Instagram está conectado; faltan permisos de alguna función.'
        elif result.get('status')=='REAUTH_REQUIRED':result['human_action']='Instagram necesita volver a autorizarse.'
    if provider=='youtube':
        result['capabilities']={'publishing':'READY' if result.get('ready') else 'PERMISSION_REQUIRED','channel':'READY' if result.get('channel') else 'UNKNOWN'}
    if provider=='tiktok':
        result['capabilities']={'publishing':'READY' if result.get('ready') else 'PERMISSION_REQUIRED'}
        if not result.get('connected'):result['human_action']='Conecta la cuenta ZAR desde la app existente de TikTok Developers. Abre el asistente para ver el paso pendiente.'
    return result


def shopify(scope):
    from .commerce_adapters import ShopifyAdapter
    if not os.environ.get('SHOPIFY_SHOP_DOMAIN') or not os.environ.get('SHOPIFY_ADMIN_ACCESS_TOKEN'):
        return {'status':'DISCONNECTED','human_action':'Configura el dominio y el acceso de la tienda existente; abre el asistente.'}
    try:data=ShopifyAdapter().verify()
    except ValueError:return {'status':'ERROR','human_action':'Shopify no confirmó la tienda o sus permisos. Revisa la conexión existente.'}
    shop=data['shop'];permissions=[x['handle'] for x in data.get('currentAppInstallation',{}).get('accessScopes',[]) if isinstance(x.get('handle'),str)]
    return {'status':'CONNECTED','connected':True,'account':shop.get('name'),'account_id':shop['id'],'store':shop.get('myshopifyDomain'),
            'permissions':permissions,'capabilities':{'identity':'READY'},'human_action':None}


def stripe(scope):
    from .agency_crm import PaymentAdapter
    proof=PaymentAdapter().verify()
    return {'status':'CONNECTED','connected':True,'account':proof['id'],'account_id':proof['id'],
            'capabilities':{'identity':'READY'},'diagnostic':{'test_mode':proof.get('test_mode')},'human_action':None}


def adsense(scope):
    state=identity_center.verify_google(scope,services=['ADSENSE'])
    proof=state.get('capabilities',{}).get('ADSENSE',{})
    connected=proof.get('status')=='CONNECTED'
    return {'status':'CONNECTED' if connected else 'AUTH_REQUIRED','connected':connected,'account':state.get('google',{}).get('email'),
            'capabilities':{'identity':'READY' if connected else 'UNKNOWN'},'human_action':None if connected else 'Revisa la autorización de AdSense en tu cuenta Google existente.'}


class AccountConnectionRegistry:
    def __init__(self,scope):
        self.scope=scope
        self.providers=[Provider('google','Google','GOOGLE / PRODUCTIVIDAD','G',('Workspace','ReposNews'),google),
            Provider('youtube','YouTube','GOOGLE / PRODUCTIVIDAD','▶',('Publicación social',),lambda s:social(s,'youtube')),
            Provider('instagram','Instagram','SOCIAL','◎',('ReposNews','Publicación social'),lambda s:social(s,'instagram')),
            Provider('tiktok','TikTok','SOCIAL','♪',('Publicación social',),lambda s:social(s,'tiktok')),
            Provider('shopify','Shopify','COMERCIO','S',('Reselling',),shopify,'BACKEND_PROVIDER')]
        state=holdings.read(scope).get('identity_center',{})
        if os.environ.get('STRIPE_SECRET_KEY'):self.providers.append(Provider('stripe','Stripe','FINANZAS / NEGOCIO','◈',('Web Agency',),stripe,'BACKEND_PROVIDER'))
        if 'ADSENSE' in state.get('capabilities',{}):self.providers.append(Provider('adsense','AdSense','FINANZAS / NEGOCIO','A',('Sites',),adsense))

    def provider(self,key):
        return next((p for p in self.providers if p.id==key),None)

    def connect_url(self,key):
        email=holdings.read(self.scope).get('identity_center',{}).get('google',{}).get('email') or 'zaragente031@gmail.com'
        urls={'google':identity_center.connect_url(email),'youtube':identity_center.connect_url(email,'youtube'),
              'instagram':'/api/reposnews/instagram/connect?publishing=1&return_to=/accounts',
              'adsense':identity_center.connect_url(email,'adsense')}
        return urls.get(key,'/accounts#'+key)

    def view(self):
        data=holdings.read(self.scope);cached=data.get('account_connections',{})
        rows=[]
        for provider in self.providers:
            observed=cached.get(provider.id,{})
            item={'id':provider.id,'name':provider.name,'category':provider.category,'icon':provider.icon,'kind':provider.kind,
                  'account_identity':None,'status':'UNKNOWN','capabilities':{},'last_verified':None,
                  'disconnect_available':False,'human_action':'Comprueba el estado de esta conexión.','diagnostic':{},
                  'used_by':list(provider.used_by),**observed}
            item.update(connect_url=self.connect_url(provider.id),reconnect_url=self.connect_url(provider.id))
            rows.append(item)
        return {'providers':rows,'summary':{'connected':sum(x['status'] in GOOD for x in rows),'attention':sum(x['status'] in ATTENTION for x in rows)}}

    def reverify(self,key):
        provider=self.provider(key)
        if not provider:raise ValueError('UNKNOWN_PROVIDER')
        try:result=provider.adapter(self.scope)
        except Exception:result={'status':'ERROR','human_action':'No se ha podido comprobar la conexión. Vuelve a verificar.','ready':False}
        # Explicit whitelist: adapters may hold private credentials internally, never in observations.
        allowed={'status','connected','ready','upload_ready','account','account_id','channel','store','capabilities','permissions','human_action','diagnostic','blocker','identity_status','verified_cause','privacy_options','max_duration','max_video_post_duration_sec','publish_capability','required_permission','permission_check_http'}
        safe={k:v for k,v in result.items() if k in allowed}
        safe.update(last_verified=holdings._now(),account_identity=result.get('account'),connect_url='/accounts#'+key,reconnect_url='/accounts#'+key)
        with holdings.transaction(self.scope):
            data=holdings.read(self.scope);data.setdefault('account_connections',{})[key]=safe;holdings.write(self.scope,data)
        self.notification(key,safe)
        return safe

    def notification(self,key,item):
        from .notification_center import emit
        attention=item['status'] in ATTENTION
        condition=item['status'] if attention else None
        prefix='account:'+key+':'
        with holdings.transaction(self.scope):
            data=holdings.read(self.scope);center=identity_center.ensure(data)
            for row in center['human_actions']:
                if row.get('service')==key.upper() and row.get('action') in {'SOCIAL_CONNECTION','SETUP'} and row.get('status')!='DONE':
                    row.update(status='DONE',resolution='ACCOUNT_CENTER',completed_at=holdings._now(),read_at=holdings._now())
                if str(row.get('notification_key','')).startswith(prefix) and row.get('status')!='DONE' and row.get('details',{}).get('condition')!=condition:
                    row.update(status='DONE',completed_at=holdings._now(),read_at=holdings._now())
            holdings.write(self.scope,data)
        if attention:
            emit(self.scope,'ACCOUNT_CONNECTION',prefix+condition,'Revisar conexión · '+self.provider(key).name,item.get('human_action') or 'La cuenta requiere atención.',
                 '/accounts#'+key,entity_id=key,entity_type='ACCOUNT',actions=[{'label':'RECONECTAR' if condition=='REAUTH_REQUIRED' else 'VER CUENTA','url':'/accounts#'+key}],details={'condition':condition})
            # A later recurrence reopens the same condition, without duplicating it.
            with holdings.transaction(self.scope):
                data=holdings.read(self.scope)
                for row in identity_center.ensure(data)['human_actions']:
                    if row.get('notification_key')==prefix+condition and row.get('status')=='DONE':
                        row.update(status='ACTION_REQUIRED',read_at=None,completed_at=None)
                holdings.write(self.scope,data)


def social_connections(scope,only=None):
    registry=AccountConnectionRegistry(scope)
    return {key:registry.reverify(key) for key in sorted({'youtube','instagram','tiktok'}.intersection(only if only is not None else {'youtube','instagram','tiktok'}))}


def register(app,scope_fn,csrf_owner):
    def owner():
        if session.get('zar_auth') is not True:abort(401)
        return scope_fn()

    @app.get('/accounts')
    def accounts_page():
        owner()
        return render_template('accounts.html')

    @app.get('/api/accounts/connections')
    def accounts_get():
        registry=AccountConnectionRegistry(owner())
        return jsonify(ok=True,csrf=session.setdefault('business_csrf',secrets.token_urlsafe(32)),**registry.view())

    @app.post('/api/accounts/connections/<provider>/<action>')
    def accounts_action(provider,action):
        registry=AccountConnectionRegistry(csrf_owner())
        if not registry.provider(provider):abort(404)
        if action=='reverify':return jsonify(ok=True,result=registry.reverify(provider))
        if action in {'connect','reconnect'}:
            return jsonify(ok=True,url=registry.connect_url(provider),assistant=provider if provider in {'tiktok','shopify','stripe'} else None)
        abort(404)
