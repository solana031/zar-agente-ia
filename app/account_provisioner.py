"""Official login first, existing account before signup. No fabricated identities."""
SERVICES = {
    'SHOPIFY': 'https://accounts.shopify.com/lookup',
    'TIKTOK': 'https://www.tiktok.com/login/phone-or-email/email',
    'INSTAGRAM': 'https://www.instagram.com/accounts/login/',
    'ADSENSE': 'https://www.google.com/adsense/',
    'ELEVENLABS': 'https://elevenlabs.io/app/sign-in',
    'STRIPE': 'https://dashboard.stripe.com/login',
    'LOVABLE': 'https://lovable.dev/',
}


def prepare(scope, service):
    from . import identity_center
    if service not in SERVICES:
        raise ValueError('Servicio no disponible')
    account = 'solana031@gmail.com' if service == 'LOVABLE' else 'zaragente031@gmail.com'
    existing = next((row for row in identity_center.view(scope).get('integrations', [])
                     if row['service'] == service and row.get('account') == account), {})
    if existing.get('status') in ('VERIFIED', 'CONNECTED'):
        return {'ok': True, 'status': existing['status'], 'account': account,
                'reason': 'Cuenta existente verificada. No se crea otra.', 'url': SERVICES[service]}
    return {'ok': True, 'status': 'ACTION_REQUIRED', 'account': account,
            'reason': 'Comprobar acceso a la cuenta existente mediante login oficial antes de cualquier alta. CAPTCHA, 2FA, credenciales, términos o KYC requieren intervención personal.',
            'url': SERVICES[service], 'action': 'CHECK_EXISTING_ACCOUNT'}
