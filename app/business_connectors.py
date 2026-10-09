"""Configuration inventory: env presence is never proof of connectivity."""
import os
import hashlib
import json

SPECS = {
    "Canva": (["CANVA_ACCESS_TOKEN"], "https://www.canva.com/signup/"),
    "Alpaca Paper": (["ALPACA_API_KEY","ALPACA_API_SECRET"], "https://app.alpaca.markets"),
    "JEV": (["JEV_API_KEY"], "https://typesafe.ai"),
    "ElevenLabs": (["ELEVENLABS_API_KEY", "ELEVENLABS_VOICE_ID"], "https://elevenlabs.io"),
    "F5-TTS": (["F5_TTS_API_URL"], None),
    "Shopify": (["SHOPIFY_SHOP_DOMAIN", "SHOPIFY_ADMIN_ACCESS_TOKEN"], "https://partners.shopify.com"),
    "Proveedor": (["ZAR_SUPPLIER_ORDER_WEBHOOK","ZAR_SUPPLIER_CATALOG_URL","ZAR_SUPPLIER_QUOTE_URL","ZAR_SUPPLIER_TRACKING_URL","ZAR_SUPPLIER_API_TOKEN"], None),
    "Stripe Webhook": (["STRIPE_WEBHOOK_SECRET"], "https://dashboard.stripe.com/webhooks"),
    "Payment": (["STRIPE_SECRET_KEY","ZAR_CHECKOUT_SUCCESS_URL","ZAR_CHECKOUT_CANCEL_URL"], "https://dashboard.stripe.com/apikeys"),
    "Google Maps": (["ZAR_MAPS_API_KEY"], "https://console.cloud.google.com"),
    "TikTok": (["TIKTOK_ACCESS_TOKEN"], "https://developers.tiktok.com"),
    "Instagram": (["INSTAGRAM_ACCESS_TOKEN", "INSTAGRAM_IG_USER_ID"], "https://developers.facebook.com"),
    "DramaClaw DIRECT": (["DRAMACLAW_API_URL"], None),
    "AdSense": (["GOOGLE_ADSENSE_ACCESS_TOKEN", "GOOGLE_ADSENSE_ACCOUNT", "GOOGLE_ADSENSE_PUBLISHER_ID"], "https://adsense.google.com"),
    "Vercel": (["VERCEL_TOKEN"], "https://vercel.com/account/tokens"),
    "Dominio": (["ZAR_DOMAIN_REGISTRANT_JSON"], "https://vercel.com/domains"),
}


def verification(name,state,scope='API response'):
    from . import holdings
    return {'state':state,'checked_at':holdings._now(),'fingerprint':fingerprint(name),'verification_scope':scope}


def fingerprint(name):
    variables=SPECS.get(name,([],None))[0]
    extra={'Alpaca Paper':['ALPACA_BASE_URL','ALPACA_PAPER_API_KEY','ALPACA_PAPER_API_SECRET'],'Shopify':['SHOPIFY_API_VERSION'],'Proveedor':['ZAR_SUPPLIER_CATALOG_URL','ZAR_SUPPLIER_QUOTE_URL','ZAR_SUPPLIER_TRACKING_URL','ZAR_SUPPLIER_API_TOKEN'],
           'JEV':['TYPESAFE_API_KEY','JEV_API_BASE','JEV_MODEL'], 'DramaClaw DIRECT':['DRAMACLAW_API_TOKEN'],
           'AdSense':['ADSENSE_PUBLISHER_ID']}.get(name,[])
    return hashlib.sha256(json.dumps([os.environ.get(x,'') for x in variables+extra]).encode()).hexdigest()


def inventory(state=None):
    rows = []
    for name, (variables, url) in SPECS.items():
        missing = [var for var in variables if not os.environ.get(var, '').strip()]
        if name=='Alpaca Paper':
            from .alpaca_configuration import credentials
            key,secret=credentials()
            missing=[] if key and secret else ['ALPACA_API_KEY','ALPACA_API_SECRET']
        if name == 'JEV' and os.environ.get('TYPESAFE_API_KEY', '').strip():
            missing = []
        if name == 'AdSense' and (os.environ.get('ADSENSE_PUBLISHER_ID', '').strip()):
            missing = [x for x in missing if x != 'GOOGLE_ADSENSE_PUBLISHER_ID']
        rows.append({'name': name, 'state': 'POR CONFIGURAR', 'configured': not missing,
            'missing': missing, 'variables': variables, 'provider_url': url,
            'next_step': 'Configurar las variables en el almacén de secretos del servidor; después probar el conector existente.' if missing
                else 'Configuración presente, conexión no verificada en este inventario. Probar el conector existente.',
            'verified_at': None})
    rows.extend([
        {'name':'Google Identity','state':'POR CONFIGURAR','missing':['Cuenta ZAR creada y OAuth de esa identidad verificado'],'variables':[],
         'next_step':'Abrir CUENTAS DE ZAR, preparar Google, completar alta humana y verificar OAuth del buzón elegido.','provider_url':'https://accounts.google.com/signup','verified_at':None},
        {'name': 'faster-whisper', 'state': 'POR CONFIGURAR', 'missing': [], 'variables': ['ZAR_STT_PROVIDER'],
         'next_step': 'Usar el estado de Voice para comprobar runtime y modelo; inventario sin prueba de inferencia.', 'provider_url': None, 'verified_at': None},
        {'name': 'YouTube', 'state': 'POR CONFIGURAR', 'missing': ['OAuth de YouTube con permiso de publicación'],
         'variables': [], 'next_step': 'Vincular una identidad empresarial mediante el OAuth existente; aprobar revisión y publicación desde Media. Acceso todavía no verificado.', 'provider_url': 'https://console.cloud.google.com', 'verified_at': None},
        {'name': 'ZAR Mail', 'state': 'POR CONFIGURAR', 'missing': ['Buzón empresarial y OAuth'], 'variables': [],
         'next_step': 'Conectar la identidad empresarial con el flujo Gmail existente. No hay envío desde este inventario.', 'provider_url': None, 'verified_at': None},
        {'name': 'ZAR Phone', 'state': 'POR CONFIGURAR', 'missing': ['Proveedor y número'], 'variables': [],
         'next_step': 'Seleccionar proveedor/número con Pablo; no existe adaptador telefónico todavía.', 'provider_url': None, 'verified_at': None},
    ])
    from datetime import datetime, timezone
    checks=(state or {}).get('verified_connectors',{})
    for row in rows:
        check=checks.get(row['name']) or {}
        try:
            age=(datetime.now(timezone.utc)-datetime.fromisoformat(check.get('checked_at',''))).total_seconds()
            if 0<=age<600 and check.get('fingerprint')==fingerprint(row['name']) and check.get('state') in {'LISTO','POR CONFIGURAR','ERROR','NO DISPONIBLE'}:
                row['state']=check['state'];row['verified_at']=check['checked_at']
                if row['state']=='LISTO':row['missing']=[]
                row['next_step']='Verificado: '+check.get('verification_scope','respuesta del proveedor')+'. Revalidar tras cambiar configuración.'
        except (TypeError,ValueError): pass
    groups={'Alpaca Paper':'TRADING','JEV':'INFRA','ElevenLabs':'MEDIA','F5-TTS':'MEDIA','DramaClaw DIRECT':'MEDIA',
            'Shopify':'COMMERCE','Proveedor':'COMMERCE','Payment':'PAYMENTS','Stripe Webhook':'PAYMENTS',
            'AdSense':'ADS','Google Maps':'INFRA','Vercel':'INFRA','Dominio':'IDENTITY','YouTube':'SOCIAL',
            'Instagram':'SOCIAL','TikTok':'SOCIAL','ZAR Mail':'GOOGLE','ZAR Phone':'IDENTITY','faster-whisper':'MEDIA','Google Identity':'GOOGLE'}
    operations={'Alpaca Paper':{'path':'/api/stonks/alpaca/verify','action':None},
                'Shopify':{'path':'/api/holdings/workflows/commerce_shopify_sync','action':None},
                'Payment':{'path':'/api/holdings/workflows/agency_payment_probe','action':None},
                'DramaClaw DIRECT':{'path':'/api/holdings/workflows/probe','action':'DramaClaw DIRECT'},
                'ElevenLabs':{'path':'/api/holdings/workflows/probe','action':'ElevenLabs'},
                'ZAR Mail':{'path':'/api/holdings/workflows/identity_email_verify','action':None}}
    for row in rows:
        row.update(capabilities={'Alpaca Paper':['paper_account','paper_feed','paper_portfolio'],'ZAR Mail':['profile','inbox','send','reply','threads'],'Google Identity':['human_signup_workflow','oauth_identity_verification'],'Shopify':['shop','products','orders'],'Proveedor':['catalog','quote','order','tracking'],'DramaClaw DIRECT':['health','preview','generation_requires_credentials'],'ZAR Phone':['configuration_pending']}.get(row['name'],['configuration','provider_verification_in_module']),provider=row['name'],group=groups.get(row['name'],'INFRA'),status=row['state'],
                   last_verified=row['verified_at'],missing_requirements=row['missing'],verify=operations.get(row['name']))
        variables=list(row['variables'])
        if row['name']=='Alpaca Paper':variables.append('ALPACA_BASE_URL')
        row['configuration']=[{'variable':name,
            'expected':'https://paper-api.alpaca.markets' if name=='ALPACA_BASE_URL' else 'Valor del proveedor; secreto solo en servidor' if any(x in name for x in ('KEY','SECRET','TOKEN')) else 'Identificador/URL real del proveedor',
            'obtain_at':row.get('provider_url') or 'Panel/documentación del proveedor conectado',
            'paste_at':'Railway → proyecto existente → servicio web → Variables → Deploy'} for name in variables]
    center=(state or {}).get('identity_center',{})
    account=center.get('google',{})
    for row in rows:
        row['account']=next((p.get('identity') for p in center.get('plans',[]) if p['service']=={'Payment':'STRIPE','Dominio':'DOMAIN','Proveedor':'SUPPLIER'}.get(row['name'],row['name'].upper())),None)
        if row['name'] in {'Google Identity','ZAR Mail','YouTube','AdSense'}:
            row['account']=account.get('email')
        if row['name']=='Google Identity':
            row.update(provider_url='https://myaccount.google.com',missing_requirements=[] if account.get('status')=='ACTIVE' else ['Cuenta creada: registrar email y autorizar OAuth'],
                       next_step='Cuenta Google de ZAR ya creada. Abrir ACTIVAR ZAR para registrar email, conectar OAuth y verificar capacidades.')
    for name in ('GMAIL','DRIVE','DOCS','SHEETS','SLIDES','CALENDAR','CONTACTS','TASKS'):
        cap=center.get('capabilities',{}).get(name,{})
        rows.append({'name':'Google '+name.title(),'provider':'GOOGLE','account':account.get('email'),'group':'GOOGLE',
            'state':'LISTO' if cap.get('status')=='CONNECTED' else 'ERROR' if cap.get('status')=='ERROR' else 'POR CONFIGURAR',
            'status':cap.get('status','NOT_CONNECTED'),'capabilities':[name.lower()],
            'missing':[cap.get('reason','Autorizar OAuth y verificar acceso real')],
            'missing_requirements':[] if cap.get('status')=='CONNECTED' else [cap.get('reason','Autorizar OAuth y verificar acceso real')],
            'verified_at':cap.get('last_verified'),'last_verified':cap.get('last_verified'),'configuration':[],
            'next_step':'ACTIVAR ZAR → CONECTAR → VERIFICAR; permisos adicionales solo al necesitar el servicio.',
            'provider_url':'https://myaccount.google.com/permissions',
            'verify':{'path':'/api/holdings/workflows/identity_center_verify','action':None}})
    for row in rows:
        if row['name'] == 'JEV':
            # The server policy is wired into semantic_tasks.run; the hosted
            # TypeSafe model is an optional, separate decision provider.
            row.update(state='READY', status='READY', missing=[], missing_requirements=[],
                       capabilities=['server_policy', 'explicit_confirmation', 'live_trading_denied'],
                       next_step='Política interna activa en TaskOrchestrator. El modelo TypeSafe externo es opcional; su presencia no concede autoridad de ejecución.',
                       provider='ZAR server policy', configuration=[], variables=[])
        elif row['name'] in {'F5-TTS', 'faster-whisper'} and row['state'] == 'POR CONFIGURAR':
            row.update(state='OPTIONAL', status='OPTIONAL',
                       next_step='Motor opcional. No se ha verificado inferencia; consultar Voice para el proveedor activo. No es un bloqueo de ZAR.')
    return rows
