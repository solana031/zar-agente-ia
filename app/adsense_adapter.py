"""Read-only Google AdSense v2 adapter; provider totals never imply bank receipt."""
import os
import re
from decimal import Decimal, InvalidOperation
import requests
from . import holdings
from .business_connectors import verification

METRICS = ['PAGE_VIEWS','IMPRESSIONS','CLICKS','PAGE_VIEWS_CTR','COST_PER_CLICK','PAGE_VIEWS_RPM','ESTIMATED_EARNINGS']


def parse_amount(value):
    text = str(value or '').strip()
    match = re.search(r'\b([A-Z]{3})\b', text)
    currency = match.group(1) if match else next((c for symbol,c in [('€','EUR'),('$','USD'),('£','GBP'),('¥','JPY')] if symbol in text), None)
    # Google returns formatted values: never assume a currency or ambiguous locale.
    number = re.sub(r'[^0-9.,-]', '', text)
    if ',' in number and '.' in number:
        number = number.replace(',', '') if number.rfind('.') > number.rfind(',') else number.replace('.', '').replace(',', '.')
    elif ',' in number:
        number = number.replace(',', '') if re.fullmatch(r'-?\d{1,3}(,\d{3})+', number) else number.replace(',', '.')
    try:
        amount = Decimal(number)
    except InvalidOperation:
        return None, currency
    return (str(amount) if amount.is_finite() and amount >= 0 else None), currency


class AdSenseAdapter:
    def __init__(self, session=None):
        self.session = session or requests.Session()

    def get(self, path, params=None):
        token = os.environ.get('GOOGLE_ADSENSE_ACCESS_TOKEN', '').strip()
        if not token:
            raise ValueError('POR CONFIGURAR: GOOGLE_ADSENSE_ACCESS_TOKEN con scope adsense.readonly.')
        if not re.fullmatch(r'accounts(?:/[^/?#]+(?:/(?:sites|payments|reports:generate))?)?', path):
            raise ValueError('Recurso AdSense no válido.')
        try:
            r = self.session.get('https://adsense.googleapis.com/v2/'+path,
                headers={'Authorization':'Bearer '+token}, params=params, timeout=(5,30), allow_redirects=False)
            if not r.ok:
                raise ValueError('AdSense HTTP '+str(r.status_code)+'. Revisa OAuth/permisos.')
            data = r.json()
            if not isinstance(data, dict):
                raise ValueError('Respuesta AdSense no válida.')
            return data
        except requests.RequestException:
            raise ValueError('AdSense no disponible; respuesta no confirmada.') from None

    def collection(self, path, field):
        rows, token = [], None
        for _ in range(30):
            data = self.get(path, {'pageToken':token} if token else None)
            items = data.get(field, [])
            if not isinstance(items, list):
                raise ValueError('Colección AdSense no válida.')
            rows.extend(items)
            token = data.get('nextPageToken')
            if not token:
                return rows
        raise ValueError('AdSense supera el límite de páginas; no se guarda una lectura parcial.')

    def accounts(self):
        return self.collection('accounts', 'accounts')

    def snapshot(self, account=None, domain=None):
        accounts = self.accounts()
        if not account:
            if len(accounts) != 1:
                raise ValueError('Selecciona GOOGLE_ADSENSE_ACCOUNT: no se elige una cuenta arbitraria.')
            account = accounts[0]['name']
        if not account.startswith('accounts/'):
            account = 'accounts/'+account
        if account not in {x.get('name') for x in accounts}:
            raise ValueError('Cuenta AdSense no accesible.')
        if domain and not re.fullmatch(r'[a-z0-9.-]+', domain):
            raise ValueError('Dominio inválido.')
        params = [('dateRange','LAST_30_DAYS'),('languageCode','en'),('currencyCode','EUR')]
        params += [('metrics',m) for m in METRICS]
        if domain:
            params += [('filters','OWNED_SITE_DOMAIN_NAME=='+domain)]
        report = self.get(account+'/reports:generate', params)
        cells = (report.get('totals') or {}).get('cells') or []
        averages = (report.get('averages') or {}).get('cells') or []
        numbers = {}
        for index, header in enumerate(report.get('headers', [])):
            value = cells[index].get('value') if index < len(cells) else None
            if value in {None,''} and index < len(averages):value=averages[index].get('value')
            try:
                number = Decimal(str(value)) if value is not None and str(value) != '' else None
                numbers[header['name']] = str(number) if number is not None and number.is_finite() else None
            except InvalidOperation:
                numbers[header['name']] = None
        payments = []
        for p in self.collection(account+'/payments','payments'):
            name = str(p.get('name',''))
            if 'youtube-' in name:
                continue
            amount, currency = parse_amount(p.get('amount'))
            payments.append({'reference':name, 'amount':amount, 'currency':currency, 'date':p.get('date'),
                'classification':'FINALIZED', 'provider_status':'UNPAID' if name.endswith('/unpaid') else 'CREDITED_BY_GOOGLE',
                'receipt_verified':False})
        return {'state':'LISTO','source':'Google AdSense API','account':account, 'accounts':accounts,
            'site':domain, 'sites':self.collection(account+'/sites','sites'), 'period':'LAST_30_DAYS',
            'start_date':report.get('startDate'), 'end_date':report.get('endDate'), 'currency':'EUR',
            'metrics':{m:numbers.get(m) for m in METRICS}, 'classification':'ESTIMATED',
            'payments':payments,'updated_at':holdings._now(), 'google_updated_at':None,
            'warnings':report.get('warnings',[]),
            'note':'Datos de informe, no tiempo real. Google no proporciona aquí timestamp de actualización; updated_at es la consulta de ZAR. Pagos pendientes de conciliación bancaria.'}


def sync(scope, account=None, domain=None):
    try:
        result = AdSenseAdapter().snapshot(account or os.environ.get('GOOGLE_ADSENSE_ACCOUNT','').strip() or None, domain)
    except ValueError:
        with holdings.transaction(scope):
            d = holdings.read(scope)
            d.setdefault('verified_connectors', {})['AdSense'] = verification('AdSense','ERROR' if os.environ.get('GOOGLE_ADSENSE_ACCESS_TOKEN') else 'POR CONFIGURAR')
            holdings.write(scope,d)
        raise
    with holdings.transaction(scope):
        d = holdings.read(scope)
        previous = d.get('adsense', {})
        received = {x['reference']:x for x in previous.get('payments',[]) if x.get('classification')=='RECEIVED'}
        for p in result['payments']:
            if p['reference'] in received:
                p.update(received[p['reference']])
        d['adsense'] = result
        d.setdefault('adsense_history',[]).append(result)
        d.setdefault('verified_connectors',{})['AdSense'] = verification('AdSense','LISTO','accounts, report and payments read')
        holdings.write(scope,d)
        from . import sites_company
        projects=sites_company._read_registry(scope)
        for project in projects:
            remote=next((x for x in result['sites'] if x.get('domain')==project.get('domain')),None)
            if remote:
                project['adsense_status']=remote.get('state')
                project['adsense_checked_at']=result['updated_at']
                if remote.get('state')=='READY':project['state']='MONETIZED'
                elif remote.get('state') in {'GETTING_READY','REQUIRES_REVIEW'}:project['state']='ADSENSE_PENDING'
            if domain and project.get('domain')==domain:project['metrics']=result['metrics']
        sites_company._write_registry(scope,projects)
    return result


def confirm_received(scope, reference, bank_reference, confirmed=False):
    if confirmed is not True or not isinstance(bank_reference,str) or not bank_reference.strip():
        raise ValueError('Confirma la recepción e indica referencia bancaria; no se ejecuta una transferencia.')
    with holdings.transaction(scope):
        d = holdings.read(scope)
        p = next((x for x in d.get('adsense',{}).get('payments',[]) if x['reference']==reference),None)
        if not p or p['provider_status'] != 'CREDITED_BY_GOOGLE' or not p['amount'] or not p['currency']:
            raise ValueError('Pago identificable de Google requerido; no se pueden cobrar estimados/unpaid.')
        if p.get('classification')=='RECEIVED':
            if p.get('bank_reference')!=bank_reference[:200]:raise ValueError('Cobro ya registrado con otra referencia bancaria.')
            return p
        holdings.add_ledger(scope,'sites','revenue',p['amount'],currency=p['currency'],source='adsense_received',
            reference=p['reference'],note='RECEIVED confirmado por Pablo; referencia bancaria: '+bank_reference[:200],verified=True)
        d = holdings.read(scope)
        p = next(x for x in d['adsense']['payments'] if x['reference']==reference)
        p.update(classification='RECEIVED',receipt_verified=True,bank_reference=bank_reference[:200],received_at=holdings._now())
        holdings.write(scope,d)
        return p
