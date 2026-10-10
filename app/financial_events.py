"""Scoped, idempotent events from authenticated provider evidence, never estimates."""
from datetime import datetime, timezone, timedelta
from decimal import Decimal
import hashlib, re
from . import holdings

BUSINESSES={'sites','commerce','media','web_agency','zar'}

def ingest(scope, kind, event, *, provider_verified=False, ledger_id=None):
    if kind not in {'cost','revenue'} or provider_verified is not True:
        raise ValueError('Authenticated provider evidence required.')
    provider=str(event.get('provider','')).strip();external=str(event.get('external_id','')).strip()
    source=str(event.get('source','')).strip();business=event.get('business');currency=str(event.get('currency','')).upper()
    amount=Decimal(str(event.get('amount')))
    stamp=datetime.fromisoformat(str(event.get('timestamp','')).replace('Z','+00:00'))
    if not provider or len(provider)>80 or not external or len(external)>300 or not source or len(source)>200 or business not in BUSINESSES or not re.fullmatch('[A-Z]{3}',currency) or stamp.tzinfo is None or not amount.is_finite() or amount<0 or amount!=amount.quantize(Decimal('0.000001')):
        raise ValueError('Complete, finite provider amount, currency, date and identity required.')
    key=hashlib.sha256((provider+'\0'+external+'\0'+kind).encode()).hexdigest()
    row={'id':key,'kind':kind,'provider':provider[:80],'business':business,'amount':str(amount),'currency':currency,'timestamp':stamp.astimezone(timezone.utc).isoformat(),'source':source[:200],'task_id':str(event.get('task_id') or '')[:100],'external_id':external[:300],'verified':True,
         'metadata':{k:v for k,v in (event.get('metadata') or {}).items() if k in {'model','quantity','invoice_id','classification'} and isinstance(v,(str,int,float,bool))},'ledger_id':ledger_id}
    with holdings.transaction(scope):
        d=holdings.read(scope);events=d.setdefault('financial_events',[]);previous=next((x for x in events if x['id']==key),None)
        if previous:
            if Decimal(previous['amount'])!=amount or any(previous[k]!=row[k] for k in ('currency','business')):raise ValueError('Provider event conflict: reconcile the source; do not overwrite.')
            return previous
        if ledger_id and not any(x['id']==ledger_id for x in d.get('ledger',[])):raise ValueError('Source ledger missing.')
        if not ledger_id and amount>0:
            # Costs describe billed consumption; revenues require a received source.
            if kind=='revenue' and row['metadata'].get('classification')!='RECEIVED':raise ValueError('Estimated/unpaid revenue cannot book cash.')
            ledger={'id':key[:16],'timestamp':row['timestamp'],'company':business,'kind':kind,'amount':str(amount),'currency':currency,'status':'collected','source':source,'reference':key,'verified':True,'note':'Provider evidence; book entry does not verify bank balance.'}
            d.setdefault('ledger',[]).append(ledger);row['ledger_id']=ledger['id']
        events.append(row);holdings.write(scope,d)
    holdings.recalculate(scope)
    return row

def sync_existing(scope):
    """Automatically index already verified receipts without booking them twice."""
    d=holdings.read(scope);added=0
    for row in d.get('ledger',[]):
        if row.get('verified') is not True or row.get('kind') not in {'cost','expense','revenue'} or row.get('status')!='collected' or not row.get('reference'):continue
        if row.get('source') not in {'agency_received','adsense_received'}:continue
        kind='revenue' if row['kind']=='revenue' else 'cost'
        event={'provider':'Stripe' if row['source']=='agency_received' else 'AdSense','business':row['company'],'amount':row['amount'],'currency':row['currency'],'timestamp':row['timestamp'],'source':row['source'],'external_id':row['reference'],'metadata':{'classification':'RECEIVED'}}
        before=len(holdings.read(scope).get('financial_events',[]));ingest(scope,kind,event,provider_verified=True,ledger_id=row['id']);added+=len(holdings.read(scope).get('financial_events',[]))-before
    return added

def summary(d, now=None):
    now=now or datetime.now(timezone.utc);events=d.get('financial_events',[]);result={}
    for kind in ('cost','revenue'):
        result[kind]={}
        for name,start in [('today',now.replace(hour=0,minute=0,second=0,microsecond=0)),('week',now-timedelta(days=7)),('month',now.replace(day=1,hour=0,minute=0,second=0,microsecond=0))]:
            groups={}
            for row in events:
                stamp=datetime.fromisoformat(row['timestamp'])
                if row['kind']!=kind or not start<=stamp<=now:continue
                key=(row['business'],row['provider'],row['currency']);groups[key]=groups.get(key,Decimal(0))+Decimal(row['amount'])
            result[kind][name]=[{'business':b,'provider':p,'currency':c,'amount':str(v)} for (b,p,c),v in groups.items()]
    return {'events':events[-200:][::-1],'periods':result,'errors':d.get('financial_ingestion_errors',{}),'note':'Sin datos cuando no hay eventos verificables; monedas separadas. No equivale a saldo bancario.'}
