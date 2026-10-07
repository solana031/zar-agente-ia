"""Configuration inventory: env presence is never proof of connectivity."""
import os
import hashlib
import json

SPECS = {
    "JEV": (["JEV_API_KEY"], "https://typesafe.ai"),
    "ElevenLabs": (["ELEVENLABS_API_KEY", "ELEVENLABS_VOICE_ID"], "https://elevenlabs.io"),
    "F5-TTS": (["F5_TTS_API_URL"], None),
    "Shopify": (["SHOPIFY_SHOP_DOMAIN", "SHOPIFY_ADMIN_ACCESS_TOKEN"], "https://partners.shopify.com"),
    "Proveedor": (["ZAR_SUPPLIER_ORDER_WEBHOOK"], None),
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
    extra={'Shopify':['SHOPIFY_API_VERSION'],'Proveedor':['ZAR_SUPPLIER_CATALOG_URL','ZAR_SUPPLIER_QUOTE_URL','ZAR_SUPPLIER_TRACKING_URL','ZAR_SUPPLIER_API_TOKEN'],
           'JEV':['TYPESAFE_API_KEY','JEV_API_BASE','JEV_MODEL'], 'DramaClaw DIRECT':['DRAMACLAW_API_TOKEN'],
           'AdSense':['ADSENSE_PUBLISHER_ID']}.get(name,[])
    return hashlib.sha256(json.dumps([os.environ.get(x,'') for x in variables+extra]).encode()).hexdigest()


def inventory(state=None):
    rows = []
    for name, (variables, url) in SPECS.items():
        missing = [var for var in variables if not os.environ.get(var, '').strip()]
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
                row['next_step']='Verificado: '+check.get('verification_scope','respuesta del proveedor')+'. Revalidar tras cambiar configuración.'
        except (TypeError,ValueError): pass
    return rows
