"""Authenticated Stripe notifications and scoped CRM inbound classification."""
import hashlib
import hmac
import json
import os
import re
from pathlib import Path
import time
from email.utils import parseaddr
from . import holdings, agency_crm

CLASSIFICATIONS = ('INTERESTED','TOO_EXPENSIVE','QUESTION','NOT_INTERESTED','DO_NOT_CONTACT','ACCEPTED','OTHER')

def inbound(scope, data):
    """Import a real mailbox message; classification is explicitly reviewed."""
    from . import gmail
    message = gmail.get_message(data['message_id'])
    classification = data.get('classification', 'OTHER')
    if classification not in CLASSIFICATIONS:
        raise ValueError('Clasificación no válida.')
    with holdings.transaction(scope):
        d = holdings.read(scope)
        lead = agency_crm.find(agency_crm.ensure(d)['leads'], data['lead_id'])
        if parseaddr(message.get('from',''))[1].lower() != str(lead.get('email') or '').lower():
            raise ValueError('Remitente no corresponde al lead.')
        rows = lead.setdefault('inbound', [])
        old = next((x for x in rows if x['id']==message['id']), None)
        if old: return old
        row = {k:message.get(k) for k in ('id','threadId','from','to','subject','date','text')}
        row.update(classification=classification, timestamp=holdings._now(), source='Gmail')
        rows.append(row)
        lead['thread_id'] = message.get('threadId')
        if classification == 'DO_NOT_CONTACT':
            agency_crm.transition(lead, 'DO_NOT_CONTACT', {})
        elif lead['state'] != 'DO_NOT_CONTACT':
            agency_crm.transition(lead, 'LOST' if classification=='NOT_INTERESTED' else 'REPLIED', {})
        holdings.write(scope,d)
        return row

def verify_event(raw, signature):
    secret = os.environ.get('STRIPE_WEBHOOK_SECRET','')
    if not secret: raise ValueError('POR CONFIGURAR: STRIPE_WEBHOOK_SECRET')
    pairs = [x.split('=',1) for x in signature.split(',') if '=' in x]
    stamp = next((v for k,v in pairs if k=='t'), '')
    if not stamp.isdigit() or abs(time.time()-int(stamp))>300:
        raise ValueError('Firma Stripe caducada o inválida.')
    expected = hmac.new(secret.encode(),stamp.encode()+b'.'+raw,hashlib.sha256).hexdigest()
    if not any(hmac.compare_digest(expected,v) for k,v in pairs if k=='v1'):
        raise ValueError('Firma Stripe inválida.')
    event = json.loads(raw)
    if not isinstance(event,dict) or not event.get('id'): raise ValueError('Evento inválido.')
    return event

def apply_event(event):
    supported = {'checkout.session.completed','checkout.session.async_payment_succeeded',
                 'checkout.session.async_payment_failed','checkout.session.expired','charge.refunded'}
    if event.get('type') not in supported: return {'ignored':True}
    obj = event.get('data',{}).get('object',{})
    scope = obj.get('metadata',{}).get('scope')
    if event.get('type')=='charge.refunded':
        scope=None
        if not obj.get('payment_intent'):return {'ignored':True}
        base=Path(os.environ.get('ZAR_DATA_DIR','/data'))/'users'
        for path in base.glob('*/holdings/state.json'):
            saved=json.loads(path.read_text(encoding='utf-8'))
            match=next((p for p in saved.get('agency_crm',{}).get('payments',[])
                        if p.get('payment_intent_id')==obj['payment_intent'] and p.get('charge_id')==obj.get('id')),None)
            if match:
                scope=path.parent.parent.name;obj=dict(obj,id=match['provider_id']);break

    if not isinstance(scope,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,150}',scope) or not (Path(os.environ.get('ZAR_DATA_DIR','/data'))/'users'/scope/'holdings'/'state.json').exists():
        return {'ignored':True}
    with holdings.transaction(scope):
        d=holdings.read(scope);crm=agency_crm.ensure(d)
        events=crm.setdefault('stripe_events',[])
        if event['id'] in events: return {'duplicate':True}
        payment=next((x for x in crm['payments'] if x['provider_id']==obj.get('id')),None)
        if not payment: return {'ignored':True}
        lead=agency_crm.find(crm['leads'],payment['lead_id'])
        # Re-read the authenticated Stripe resource. Notifications never book cash.
        agency_crm.operate(scope,'payment_sync',{'lead_id':lead['id']})
        d=holdings.read(scope);crm=agency_crm.ensure(d)
        payment=agency_crm.find(crm['payments'],payment['id'])
        if event.get('livemode') is True and obj.get('livemode') is True and payment['state']=='PENDING':
            if event['type']=='checkout.session.async_payment_failed': payment['state']='FAILED'
        crm.setdefault('stripe_events',[]).append(event['id'])
        holdings.write(scope,d)
        return {'state':payment['state']}

def register(app):
    from flask import request,jsonify
    @app.post('/api/agency/stripe/webhook')
    def agency_stripe_webhook():
        try:
            event=verify_event(request.get_data(cache=False),request.headers.get('Stripe-Signature',''))
            return jsonify(ok=True,**apply_event(event))
        except (ValueError,KeyError,TypeError):
            return jsonify(ok=False,error='Signature/event not confirmed'),400
        except Exception:
            return jsonify(ok=False,error='Provider unavailable; retry notification'),503
