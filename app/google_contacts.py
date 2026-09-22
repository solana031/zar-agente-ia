from googleapiclient.discovery import build
from .cloud_auth import get_credentials


def _creds():
    c = get_credentials(auto_refresh=True)
    if not c:
        raise RuntimeError('Google no está conectado o necesita reautorización.')
    return c


def people_service():
    return build('people', 'v1', credentials=_creds(), cache_discovery=False)


def contacts_status():
    c = _creds()
    return {'ok': True, 'connected': bool(c.valid or c.refresh_token), 'service': 'Google Contacts'}


def _flatten_person(p):
    names = p.get('names') or []
    emails = p.get('emailAddresses') or []
    phones = p.get('phoneNumbers') or []
    orgs = p.get('organizations') or []
    name = next((x.get('displayName') for x in names if x.get('displayName')), '')
    if not name:
        n = names[0] if names else {}
        name = ' '.join([n.get('givenName',''), n.get('familyName','')]).strip()
    email = next((x.get('value') for x in emails if x.get('value')), '')
    phone = next((x.get('value') for x in phones if x.get('value')), '')
    company = next((x.get('name') for x in orgs if x.get('name')), '')
    return {
        'resourceName': p.get('resourceName',''),
        'etag': p.get('etag',''),
        'name': name,
        'email': email,
        'phone': phone,
        'company': company,
        'photo': (p.get('photos') or [{}])[0].get('url','') if p.get('photos') else '',
        'raw': p,
    }


def list_connections(page_size=200):
    svc = people_service()
    out = []
    page_token = None
    while True:
        req = svc.people().connections().list(
            resourceName='people/me',
            pageSize=min(max(int(page_size), 1), 500),
            personFields='names,emailAddresses,phoneNumbers,organizations,photos,metadata',
            pageToken=page_token,
        )
        data = req.execute()
        out.extend(data.get('connections', []))
        page_token = data.get('nextPageToken')
        if not page_token or len(out) >= page_size:
            break
    return [_flatten_person(p) for p in out[:page_size]]


def search_contacts(query, limit=10):
    q = (query or '').strip().lower()
    contacts = list_connections(max(100, limit * 5))
    if not q:
        return contacts[:limit]
    scored = []
    for c in contacts:
        hay = ' '.join([c.get('name',''), c.get('email',''), c.get('phone',''), c.get('company','')]).lower()
        if q in hay:
            score = 0 if c.get('name','').lower().startswith(q) else 1
            scored.append((score, c))
    scored.sort(key=lambda x: (x[0], x[1].get('name','').lower()))
    return [c for _, c in scored[:limit]]


def get_contact(resource_name):
    svc = people_service()
    p = svc.people().get(resourceName=resource_name, personFields='names,emailAddresses,phoneNumbers,organizations,photos,metadata').execute()
    return _flatten_person(p)


def create_contact(name, email='', phone='', company=''):
    svc = people_service()
    body = {'names':[{'givenName': name}]}
    if email:
        body['emailAddresses'] = [{'value': email}]
    if phone:
        body['phoneNumbers'] = [{'value': phone}]
    if company:
        body['organizations'] = [{'name': company}]
    p = svc.people().createContact(body=body).execute()
    return _flatten_person(p)


def update_contact(resource_name, etag, name=None, email=None, phone=None, company=None):
    svc = people_service()
    body = {'resourceName': resource_name, 'etag': etag}
    fields = []
    if name is not None:
        body['names'] = [{'givenName': name}]; fields.append('names')
    if email is not None:
        body['emailAddresses'] = [{'value': email}]; fields.append('emailAddresses')
    if phone is not None:
        body['phoneNumbers'] = [{'value': phone}]; fields.append('phoneNumbers')
    if company is not None:
        body['organizations'] = [{'name': company}]; fields.append('organizations')
    if not fields:
        raise ValueError('No hay campos para actualizar.')
    p = svc.people().updateContact(resourceName=resource_name, updatePersonFields=','.join(fields), body=body).execute()
    return _flatten_person(p)
