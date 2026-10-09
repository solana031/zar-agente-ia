"""Explicit sender selection for the existing scoped Gmail connection."""
import re
from . import gmail

ZAR_EMAIL = 'zaragente031@gmail.com'

def available():
    if not gmail.is_connected():
        return []
    profile = gmail.gmail_status()
    email = str(profile.get('email') or '').strip().lower()
    if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email):
        raise ValueError('Gmail no ha confirmado una identidad válida.')
    return [{'email': email, 'label': 'ZAR' if email == ZAR_EMAIL else 'Cuenta personal / sesión Google',
             'status': 'VERIFIED', 'evidence': 'Gmail users.getProfile; envío pendiente de confirmación'}]

def validate(sender_identity):
    selected = str(sender_identity or '').strip().lower()
    if not selected:
        raise ValueError('Selecciona el remitente antes de confirmar el envío.')
    accounts = available()
    if not any(row['email'] == selected for row in accounts):
        raise ValueError('El remitente elegido ya no está conectado. Revisa la cuenta; no se enviará desde otra identidad.')
    return selected
