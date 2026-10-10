"""Read-only diagnostics. Never print credentials, responses or quota-to-money guesses."""
import os, json
from urllib.parse import urlsplit
import requests

def main():
    base=os.environ.get('DRAMACLAW_API_URL','').rstrip('/')
    if not base:return print(json.dumps({'DramaClaw':'NOT_CONFIGURED'}))
    if (urlsplit(base).hostname or '').endswith('.railway.internal'):
        public=os.environ.get('DRAMACLAW_WEB_URL','').rstrip('/')
        if public.startswith('https://'):base=public
    headers={'Authorization':'Bearer '+os.environ.get('DRAMACLAW_API_TOKEN','')}
    r=requests.get(base+'/api/v1/model-gateway/config',headers=headers,timeout=10,allow_redirects=False)
    if not r.ok:return print(json.dumps({'gateway_http':r.status_code}))
    body=r.json().get('data') or {};effective=body.get('effective') or {}
    print(json.dumps({'gateway_fields':list(body),'effective_fields':list(effective),'configured':effective.get('configured'),'source':effective.get('source')}))
    # API keys, if explicitly available in the server configuration, remain in memory.
    key=os.environ.get('NEWAPI_API_KEY') or effective.get('apiKey') or effective.get('api_key')
    endpoint=effective.get('baseUrl') or effective.get('base_url')
    if not key or not endpoint or urlsplit(endpoint).hostname!='relayclaw.cdnfg.com':
        return print(json.dumps({'billing':'ACTION_REQUIRED','reason':'No accessible exact provider key/base pair; no endpoint guessed.'}))
    origin='https://relayclaw.cdnfg.com'
    for path in ['/api/usage/token','/api/log/token']:
        response=requests.get(origin+path,headers={'Authorization':'Bearer '+key},timeout=10,allow_redirects=False)
        result={'path':path,'http':response.status_code}
        if response.ok:
            value=response.json();data=value.get('data');result['data_fields']=list(data) if isinstance(data,dict) else []
            result['rows']=len(data) if isinstance(data,list) else None
            result['money_fields_present']=isinstance(data,dict) and any(k in data for k in ['amount','currency','cost'])
        print(json.dumps(result))
    print(json.dumps({'billing':'NO_VERIFIED_CURRENCY_COST','reason':'Usage quota is not a verified monetary charge; no conversion booked.'}))

if __name__=='__main__':
    try:main()
    except requests.RequestException:print(json.dumps({'billing':'ERROR','reason':'Provider unreachable from this runtime; no credentials or response logged.'}))
