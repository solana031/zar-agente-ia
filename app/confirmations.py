"""Durable confirmation IDs, exact payload binding and execution claims."""
import hashlib,json,secrets
from copy import deepcopy
from . import holdings

def fingerprint(payload):return hashlib.sha256(json.dumps(payload,sort_keys=True,default=str).encode()).hexdigest()

def prepare(scope,action,payload,risk='MEDIUM'):
    signature=fingerprint(payload)
    with holdings.transaction(scope):
        d=holdings.read(scope);rows=d.setdefault('confirmations',[])
        prior=next((r for r in reversed(rows) if r['action_id']==signature and r['state'] in {'PENDING','WAITING_SECOND','RUNNING'}),None)
        if prior:return deepcopy(prior)
        row={'confirmation_id':secrets.token_hex(16),'action_id':signature,'description':action,'risk':risk,'state':'PENDING','created_at':holdings._now(),'confirmed_at':None,'second_confirm_at':None,'executed_at':None,'job_id':None}
        rows.append(row);holdings.write(scope,d);return deepcopy(row)

def decide(scope,identifier,payload,decision,second=False,job_id=None):
    with holdings.transaction(scope):
        d=holdings.read(scope);row=next((r for r in d.get('confirmations',[]) if r['confirmation_id']==identifier),None)
        if not row:raise ValueError('Confirmación no encontrada para esta cuenta.')
        if row['state'] in {'RUNNING','EXECUTED','ERROR','CANCELLED'}:return deepcopy(row)
        if row['action_id']!=fingerprint(payload):raise ValueError('La acción ha cambiado: revisa una nueva confirmación.')
        if decision=='cancel':row.update(state='CANCELLED',confirmed_at=holdings._now(),job_id=job_id)
        elif decision=='confirm':
            row['confirmed_at']=row['confirmed_at'] or holdings._now()
            if row['risk'] in {'HIGH','CRITICAL'} and (second is not True or row['state']!='WAITING_SECOND'):row['state']='WAITING_SECOND'
            else:row.update(state='RUNNING',second_confirm_at=holdings._now() if row['risk'] in {'HIGH','CRITICAL'} else None,job_id=job_id)
        else:raise ValueError('Decisión inválida.')
        holdings.write(scope,d);return deepcopy(row)

def complete(scope,identifier,error=False):
    with holdings.transaction(scope):
        d=holdings.read(scope)
        row=next((r for r in d.get('confirmations',[]) if r['confirmation_id']==identifier),None)
        if row:row.update(state='ERROR' if error else 'CANCELLED' if row['state']=='CANCELLED' else 'EXECUTED',executed_at=holdings._now())
        holdings.write(scope,d)
