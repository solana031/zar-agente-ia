"""Provider-neutral domain preparation; never buys domains or invents DNS targets."""
import re
import requests
from pathlib import Path
from . import holdings, site_projects


def normalize(value):
    value = str(value or '').strip().lower().rstrip('.')
    try: value = value.encode('idna').decode('ascii')
    except UnicodeError: raise ValueError('Dominio inválido.')
    if len(value) > 253 or not re.fullmatch(r'(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}',value):
        raise ValueError('Introduce un dominio sin protocolo, ruta ni puerto.')
    if value.endswith(('.local','.internal','.localhost','.test','.example')):
        raise ValueError('Se necesita un dominio público registrable.')
    return value


def view(scope, project_id):
    row = site_projects.get(scope, project_id)
    config = row.get('domain_setup',{})
    return {'project_id':row['id'], 'name':row.get('domain'),
            'status':config.get('status','DOMAIN_ENTERED' if row.get('domain') else 'NO_DOMAIN'),
            'dns':config.get('dns','NOT_VERIFIED'), 'https':config.get('https','NOT_VERIFIED'), 'dns_provider':'UNKNOWN',
            'records':[], 'target_status':'HOSTING_BINDING_REQUIRED',
            'public_url':row.get('canonical'), 'requested_url':'https://'+row['domain']+'/' if row.get('domain') else None,
            'analytics':'NOT_CONNECTED', 'purchase_automatic':False,
            'next_steps':['Comprar un dominio registrable propio, si todavía no existe.',
                          'Vincular el dominio al proyecto y obtener del hosting los registros DNS exactos.',
                          'Configurar esos registros en cualquier proveedor DNS estándar.',
                          'Verificar certificado HTTPS y que la raíz sirve este sitio, antes de cambiar canonical, sitemap y robots.',
                          'Revisar identidad y privacidad; solicitar aprobación del sitio en la cuenta AdSense existente.'],
            'note':'Guardar el nombre no conecta el dominio. La URL publicada se conserva; no se inventan registros DNS.'}


def save(scope, data):
    name = normalize(data.get('domain'))
    with holdings.transaction(scope):
        row = site_projects.get(scope,data['id'])
        previous = row.get('domain_setup',{})
        setup = previous if row.get('domain') == name else {'status':'DOMAIN_ENTERED','entered_at':holdings._now()}
        site_projects.patch(scope,row['id'],domain=name,domain_setup=setup)
    return view(scope,row['id'])


def verify(scope, data):
    """Resolve public DNS and probe TLS through the existing pinned-IP egress guard."""
    from . import browser_network, sites_company
    row = site_projects.get(scope,data['id'])
    if not row.get('canonical') or not row.get('slug'):
        raise ValueError('Publica y revisa primero el proyecto; no hay un destino que verificar.')
    name = normalize(row.get('domain'))
    setup = {'status':'VERIFYING','dns':'NOT_VERIFIED','https':'NOT_VERIFIED','checked_at':holdings._now()}
    site_projects.patch(scope,row['id'],domain_setup=setup)
    proxy = None
    try:
        browser_network.public_addresses(name)
        setup['dns'] = 'VERIFIED'
        proxy = browser_network.start_proxy()
        with requests.Session() as client:
            client.trust_env = False
            client.proxies = {'https':'http://127.0.0.1:'+str(proxy.server_address[1])}
            with client.get('https://'+name+'/',timeout=(5,10),allow_redirects=False,stream=True) as response:
                setup['https'] = 'VERIFIED'
                setup['http_status'] = response.status_code
                content = bytearray()
                for chunk in response.iter_content(8192):
                    content.extend(chunk)
                    if len(content)>256000: raise ValueError('Respuesta demasiado grande para verificar el sitio.')
                origin = 'https://'+name+'/'
                root = sites_company._public_root()/row['slug']
                expected = (root/'index.html').read_text(encoding='utf-8').replace(row.get('canonical',''),origin)
                # An arbitrary reachable domain is never accepted as this project.
                if response.status_code != 200 or bytes(content).decode('utf-8') != expected or row.get('state') != 'PUBLISHED':
                    setup.update(status='DNS_REQUIRED',reason='HTTPS responde, pero la raíz no sirve la versión publicada de este proyecto con su canonical propio.')
                else:
                    if data.get('confirmed') is not True:
                        setup.update(status='DNS_REQUIRED',reason='Contenido verificado. Confirma aplicar el dominio para actualizar canonical, sitemap y robots.')
                        site_projects.patch(scope,row['id'],domain_setup=setup)
                        result=view(scope,row['id']);result['verification']=setup
                        return result
                    old = row['canonical']
                    for filename in row.get('files',[]):
                        if Path(filename).suffix in {'.html','.xml','.txt'}:
                            path=root/filename
                            if path.exists(): path.write_text(path.read_text(encoding='utf-8').replace(old,origin),encoding='utf-8')
                    site_projects.patch(scope,row['id'],canonical=origin)
                    setup.update(status='ACTIVE',reason='DNS público, TLS válido y contenido exacto del proyecto verificados en la raíz.')
    except (OSError, ValueError, UnicodeError, requests.RequestException):
        setup.update(status='ERROR',reason='No se pudo verificar DNS público, TLS o contenido. Revisa la vinculación del hosting y repite; la URL anterior se conserva.')
    finally:
        if proxy: proxy.shutdown(); proxy.server_close()
    site_projects.patch(scope,row['id'],domain_setup=setup)
    result=view(scope,row['id']);result['verification']=setup
    return result
