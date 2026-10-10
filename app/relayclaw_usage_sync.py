"""Read existing token usage. Monetary fields must be explicit, never quota conversion."""
import os
from urllib.parse import urlsplit
import requests
from .financial_events import ingest


class RelayClawUsageSync:
    def __init__(self,session=None):self.session=session or requests.Session()

    def run(self,scope):
        key=os.environ.get('RELAYCLAW_USAGE_API_KEY','')
        if not key:
            # Existing private DramaClaw configuration is consulted only server-side.
            base=os.environ.get('DRAMACLAW_API_URL','').rstrip('/')
            if base and (urlsplit(base).hostname or '').endswith('.railway.internal'):
                response=self.session.get(base+'/api/v1/model-gateway/config',headers={'Authorization':'Bearer '+os.environ.get('DRAMACLAW_API_TOKEN','')},timeout=(5,15),allow_redirects=False)
                if response.status_code==200:
                    effective=(response.json().get('data') or {}).get('effective') or {}
                    endpoint=effective.get('baseUrl') or effective.get('base_url') or ''
                    if urlsplit(endpoint).hostname=='relayclaw.cdnfg.com':key=effective.get('apiKey') or effective.get('api_key') or ''
        if not key:return {'status':'ACTION_REQUIRED','reason':'Credencial de consulta de consumo no accesible. No se solicita generar contenido.'}
        response=self.session.get('https://relayclaw.cdnfg.com/api/log/token',headers={'Authorization':'Bearer '+key},timeout=(5,20),allow_redirects=False)
        if response.status_code!=200:return {'status':'ACTION_REQUIRED','reason':'Historial API no autorizado (HTTP '+str(response.status_code)+').'}
        body=response.json();rows=body.get('data')
        if isinstance(rows,dict):rows=rows.get('items')
        if not isinstance(rows,list):return {'status':'ACTION_REQUIRED','reason':'No hay una lista de cargos monetarios verificables.'}
        added=0;unknown=0
        for row in rows:
            # quota/tokens and rounded UI prices are not a currency-denominated receipt.
            if row.get('status')!='charged' or row.get('amount') is None or not row.get('currency') or not row.get('id') or not row.get('timestamp'):
                unknown+=1;continue
            ingest(scope,'cost',{'provider':'RelayClaw','business':'media','amount':row['amount'],'currency':row['currency'],'external_id':str(row['id']),'timestamp':row['timestamp'],'source':'RELAYCLAW_USAGE_API','task_id':row.get('job_id'),'metadata':{'model':row.get('model_name')}},provider_verified=True)
            added+=1
        return {'status':'ACTION_REQUIRED' if unknown else 'VERIFIED','rows_checked':len(rows),'rows_verified':added,'rows_without_money':unknown,'reason':'Sin conversión de cuota a dinero. Lectura limitada a la página devuelta; no afirma histórico completo.'}


def sync(scope):
    from . import holdings
    try:result=RelayClawUsageSync().run(scope)
    except (requests.RequestException,ValueError,ArithmeticError):result={'status':'ERROR','reason':'No se pudo verificar la fuente de facturación; no se registran importes estimados.'}
    with holdings.transaction(scope):
        state=holdings.read(scope);state.setdefault('billing_sync',{})['RelayClaw']={**result,'last_checked':holdings._now()};holdings.write(scope,state)
    return result
