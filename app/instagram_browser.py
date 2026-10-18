"""Instagram authentication is exclusively local, never in the server browser."""
from flask import jsonify, Response
from .user_scope import get_current_user, user_id_for_email

ACCOUNT = 'zaragente031'


def allowed_owner():
    from . import cloud_auth
    return cloud_auth.connected() and get_current_user() in {
        user_id_for_email('solana031@gmail.com'), user_id_for_email('zaragente031@gmail.com')}


def verify():
    return {'status': 'LOCAL_WORKER_REQUIRED', 'authenticated': False, 'account': ACCOUNT}


def discovery(url):
    return {'status': 'LOCAL_WORKER_REQUIRED'}


def register(blueprint):
    @blueprint.get('/instagram-browser')
    def login_page():
        if not allowed_owner():
            return Response('Acceso reservado al titular conectado de ZAR.', status=403)
        return Response('<h1>Instagram ZAR · worker local</h1><p>El acceso se realiza en el PC, en el perfil dedicado ZAR Instagram Browser Profile. Inicia sesión como @zaragente031 en la ventana local de Instagram.</p><p>Consulta el estado y conecta zar-local-worker desde ReposNews Inbox.</p>',
            headers={'Cache-Control': 'no-store', 'X-Robots-Tag': 'noindex,nofollow'})

    @blueprint.post('/api/browser/instagram')
    def login_action():
        return jsonify(ok=False, reason='LOCAL_WORKER_REQUIRED: inicia sesión en el navegador local de ZAR.'), 410
