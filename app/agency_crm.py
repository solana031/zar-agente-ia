"""Commercial CRM in Holdings; drafts, quotes and provider-confirmed payments."""
import os
import re
import uuid
from copy import deepcopy
from decimal import Decimal
from urllib.parse import urlparse
import requests
from . import holdings,web_agency,jev_decision
from .commerce_pricing import number,fmt
from .business_connectors import verification

STATES=('LEAD','RESEARCH','DEMO','CONTACTED','REPLIED','NEGOTIATING','WON','LOST','DO_NOT_CONTACT')
AGENTS=('LeadScoutAgent','BusinessResearchAgent','OpportunityScoreAgent','WebDesignerAgent','WebBuilderAgent',
 'QAAgent','PricingAgent','SalesOutreachAgent','NegotiationAgent','ClosingAgent','PaymentAgent','ProjectDeliveryAgent')

def ensure(d):
    crm=d.setdefault('agency_crm',{})
    for key in ('leads','payments','operations'):crm.setdefault(key,[])
    return crm

def find(rows,key):
    try:return next(x for x in rows if x['id']==key)
    except StopIteration:raise ValueError('Registro CRM no encontrado.') from None

def txt(x,limit=2000):return str(x or '').strip()[:limit]

def secure_url(value):
    p=urlparse(str(value or ''))
    if p.scheme!='https' or not p.hostname or p.username or p.password:raise ValueError('URL HTTPS requerida.')
    return value

class PaymentAdapter:
    """Stripe Checkout, authenticated reads; PAID is not a bank deposit."""
    def __init__(self,session=None):self.session=session or requests.Session()
    def call(self,path,method='GET',data=None,key=None):
        token=os.environ.get('STRIPE_SECRET_KEY','').strip()
        if not token:raise ValueError('POR CONFIGURAR: STRIPE_SECRET_KEY del proveedor conectado.')
        if not re.fullmatch(r'/(account|checkout/sessions(?:/[A-Za-z0-9_]+)?)',path):raise ValueError('Ruta Stripe inválida.')
        headers={'Authorization':'Bearer '+token}
        if key:headers['Idempotency-Key']=key
        fn=self.session.get if method=='GET' else self.session.post
        kw={'params':data or {}} if method=='GET' else {'data':data or {}}
        r=fn('https://api.stripe.com/v1'+path,headers=headers,timeout=(5,30),allow_redirects=False,**kw)
        if not r.ok:raise ValueError('Stripe no confirmó operación (HTTP '+str(r.status_code)+').')
        value=r.json()
        if not isinstance(value,dict) or not value.get('id'):raise ValueError('Stripe no confirmó recurso.')
        return value
    def verify(self):
        x=self.call('/account');return {k:x.get(k) for k in ('id','country','charges_enabled','payouts_enabled')}
    def checkout(self,scope,lead,proposal,key):
        amount=Decimal(proposal['target'])
        # Current quotes support EUR/USD/GBP, all two-decimal currencies.
        if proposal['currency'] not in {'EUR','USD','GBP'}:raise ValueError('Checkout requiere EUR/USD/GBP; no inventar exponentes monetarios.')
        data={'mode':'payment','success_url':secure_url(os.environ.get('ZAR_CHECKOUT_SUCCESS_URL')),
            'cancel_url':secure_url(os.environ.get('ZAR_CHECKOUT_CANCEL_URL')),
            'client_reference_id':lead['id'],'metadata[scope]':scope,'metadata[lead]':lead['id'],
            'metadata[proposal]':proposal['id'],'line_items[0][quantity]':'1',
            'line_items[0][price_data][currency]':proposal['currency'].lower(),
            'line_items[0][price_data][unit_amount]':str(int(amount*100)),
            'line_items[0][price_data][product_data][name]':'ZAR Web Agency · '+lead['name'][:120]}
        x=self.call('/checkout/sessions','POST',data,key)
        return {'provider_id':x['id'],'url':secure_url(x.get('url')),'state':'PENDING','amount':proposal['target'],
            'currency':proposal['currency'],'test_mode':x.get('livemode') is not True,'provider':'Stripe','timestamp':holdings._now()}
    def payment(self,session_id):return self.call('/checkout/sessions/'+session_id,data={'expand[]':'payment_intent.latest_charge'})

def view(scope):
    with holdings.transaction(scope):
        d=holdings.read(scope);crm=ensure(d);holdings.write(scope,d)
        return deepcopy(crm)

def lead_record(crm,data):
    row=find(crm['leads'],data['id']) if data.get('id') else {'id':uuid.uuid4().hex,'state':'LEAD',
        'history':[],'emails':[],'proposals':[],'negotiations':[],'created_at':holdings._now(),'last_contact':None,'next_action':'Investigar','agent':'LeadScoutAgent'}
    name=txt(data.get('name') or row.get('name'),200)
    if not name:raise ValueError('Nombre real del negocio requerido.')
    for field in ('sector','address','city','phone','email','website','maps_url','source_url','services','branding'):
        if field in data:row[field]=txt(data[field])
    for field in ('rating','reviews'):
        if field in data:row[field]=fmt(number(data[field]))
    if row.get('email') and not web_agency._EMAIL_RE.fullmatch(row['email']):raise ValueError('Email público inválido.')
    row.update(name=name,source=data.get('source') or 'user_input',updated_at=holdings._now())
    if not data.get('id'):crm['leads'].append(row)
    return row

def pricing(data):
    cost=number(data.get('cost'),required=True);minimum=number(data.get('minimum'),required=True)
    target=number(data.get('target'),required=True);premium=number(data.get('premium'),required=True)
    if minimum<cost or minimum<=0 or target<minimum or premium<target:raise ValueError('Coste ≤ MINIMUM ≤ TARGET ≤ PREMIUM; importes positivos.')
    currency=data.get('currency','EUR')
    if not re.fullmatch(r'[A-Z]{3}',str(currency)):raise ValueError('Moneda requerida.')
    scope=txt(data.get('scope'),10000)
    if not scope:raise ValueError('Alcance y supuestos revisados requeridos.')
    return {'id':uuid.uuid4().hex,'cost':fmt(cost),'minimum':fmt(minimum),'target':fmt(target),'premium':fmt(premium),
        'currency':currency,'scope':scope,'taxes':fmt(number(data.get('taxes'))),'classification':'ESTIMADA','created_at':holdings._now()}

def transition(lead,state,data):
    if state not in STATES:raise ValueError('Estado CRM no admitido.')
    current=lead['state']
    if current=='DO_NOT_CONTACT' and state!='DO_NOT_CONTACT':raise ValueError('Baja activa; conservar DO_NOT_CONTACT. Reconsentimiento requiere revisión separada.')
    if state in {'CONTACTED','REPLIED'} and (data.get('confirmed') is not True or not txt(data.get('evidence'))):
        raise ValueError('Contacto/respuesta exige evidencia y confirmación, no inferir envío de un borrador.')
    if state=='WON' and not lead.get('paid'):raise ValueError('WON requiere pago confirmado por proveedor.')
    if state=='DEMO' and not lead.get('demo'):raise ValueError('Demo persistente requerida.')
    lead['state']=state
    lead['history'].append({'timestamp':holdings._now(),'from':current,'to':state,'evidence':txt(data.get('evidence')),'source':'user_confirmed' if data.get('confirmed') is True else 'local_workflow'})
    if state in {'CONTACTED','REPLIED'}:lead['last_contact']=holdings._now()
    return lead

def operate(scope,action,data):
    if not isinstance(data,dict):raise ValueError('Objeto JSON requerido.')
    with holdings.transaction(scope):
        d=holdings.read(scope);crm=ensure(d)
        if action=='lead':result=lead_record(crm,data)
        elif action=='discover':
            if data.get('confirmed') is not True:raise ValueError('Google Maps puede consumir cuota; confirma consulta limitada.')
            result=web_agency.discover(scope,txt(data.get('query'),200),min(int(data.get('limit',10)),10))
            if not result.get('ok'):raise ValueError('Google Maps no confirmó discovery; revisar configuración.')
            existing={x.get('external_id'):x for x in crm['leads']}
            for item in result['leads']:
                if item['id'] in existing:continue
                row=lead_record(crm,{**item,'id':None,'source':'Google Places'});row['external_id']=item['id']
            d['companies']=holdings.read(scope)['companies']
            d.setdefault('verified_connectors',{})['Google Maps']=verification('Google Maps','LISTO','bounded Places text search')
        elif action=='payment_probe':
            result=PaymentAdapter().verify();d.setdefault('verified_connectors',{})['Payment']=verification('Payment','LISTO','Stripe account read; checkout not tested')
            from .business_orchestration import note_verified_account
            note_verified_account(d,'Payment',result['id'],'STRIPE_SECRET_KEY','Stripe account read')
        else:
            lead=find(crm['leads'],data.get('lead_id'))
            if action=='state':result=transition(lead,data['state'],data)
            elif action=='research':
                from .web_search import _public_search
                rows=_public_search(lead['name']+' '+lead.get('city','')+' '+lead.get('sector',''),8)
                sources=[{k:x.get(k) for k in ('title','url','snippet')} for x in rows.get('results',[])]
                lead['research']={'sources':sources,'timestamp':holdings._now(),'mobile_quality':None,'broken_site':None,
                    'opportunity':'Sin web registrada' if not lead.get('website') else 'Auditoría de web pendiente',
                    'score':None,'rating_is_not_conversion':True}
                transition(lead,'RESEARCH',{});result=lead['research']
            elif action=='pricing':
                proposal=pricing(data);lead['proposals'].append(proposal);lead['proposal_id']=proposal['id'];result=proposal
            elif action=='demo':
                if not lead.get('sector') or not lead.get('services'):raise ValueError('Sector y servicios reales revisados requeridos para personalizar demo.')
                demo=web_agency.build_demo(scope,lead,number(data.get('price'),required=True))
                lead['demo']=demo;transition(lead,'DEMO',{});d['companies']=holdings.read(scope)['companies'];result=demo
            elif action=='outreach':
                if lead['state']=='DO_NOT_CONTACT':raise ValueError('DO_NOT_CONTACT: outreach bloqueado.')
                proposal=find(lead['proposals'],lead.get('proposal_id'))
                if not lead.get('demo'):raise ValueError('Demo requerida antes de outreach.')
                url=txt(data.get('preview_url')) or lead['demo']['relative_url']
                body=('Hola '+lead['name']+',\n\nSomos ZAR Web Agency. Hemos preparado una propuesta para '+lead.get('sector','vuestro negocio')+
                    ' en '+lead.get('city','vuestra ubicación')+': '+url+'\n\nAlcance: '+proposal['scope']+
                    '\nPrecio propuesto: '+proposal['target']+' '+proposal['currency']+'.\n¿Os interesa revisar la demo y el alcance?'+
                    '\nSi preferís no recibir más contactos, responded indicando baja.\n\nZAR Web Agency')
                draft={'id':uuid.uuid4().hex,'to':lead.get('email'),'subject':'Propuesta web ZAR para '+lead['name'],
                    'body':body,'state':'DRAFT','sent':False,'timestamp':holdings._now()};lead['emails'].append(draft);result=draft
            elif action=='gmail_draft':
                from .identity_center import require_mail
                require_mail(scope)
                if lead['state']=='DO_NOT_CONTACT' or data.get('confirmed') is not True:raise ValueError('Confirma borrador externo y revisa baja.')
                draft=find(lead['emails'],data['draft_id'])
                if draft.get('gmail_intent'):return draft
                if not draft.get('to'):raise ValueError('Contacto público revisado requerido.')
                draft['gmail_intent']='REQUESTED';holdings.write(scope,d)
                from .gmail import create_draft
                saved=create_draft(draft['to'],draft['subject'],draft['body'])
                if not saved.get('id'):raise ValueError('Gmail no confirmó borrador; revisar sin duplicar.')
                draft.update(gmail_id=saved['id'],gmail_intent='CONFIRMED');result=draft
            elif action=='negotiate':
                proposal=find(lead['proposals'],lead.get('proposal_id'));offer=number(data.get('offer'),required=True)
                minimum=Decimal(proposal['minimum'])
                if offer<minimum and data.get('below_minimum_approved') is not True:raise ValueError('Oferta inferior a MINIMUM exige aprobación específica.')
                message=txt(data.get('message'),10000)
                if not message:raise ValueError('Respuesta/objeción del cliente requerida.')
                row={'id':uuid.uuid4().hex,'timestamp':holdings._now(),'message':message,'offer':fmt(offer),
                    'minimum':proposal['minimum'],'below_minimum_approved':data.get('below_minimum_approved') is True,
                    'scope_change':txt(data.get('scope_change')),'reply_draft':'ZAR propone revisar alcance y precio '+fmt(offer)+' '+proposal['currency']+' antes de cualquier compromiso.',
                    'sent':False};lead['negotiations'].append(row);transition(lead,'NEGOTIATING',{});result=row
            elif action=='checkout':
                if data.get('confirmed') is not True or d.get('global_stop') or lead['state']=='DO_NOT_CONTACT':raise ValueError('Confirma checkout revisado; revisar STOP/baja.')
                proposal=find(lead['proposals'],lead.get('proposal_id'))
                if proposal.get('taxes') is None:raise ValueError('Confirma impuestos incluidos (cero explícito si corresponde) antes de crear checkout.')
                if str(data.get('total'))!=proposal['target']:raise ValueError('Confirma total exacto de propuesta; impuestos deben estar incluidos en alcance.')
                if lead.get('checkout_intent'):return lead['checkout_intent']
                decision=jev_decision.proposal(scope,{'source_agent':'PaymentAgent','task':'Agency checkout','action':'Create reviewed payment checkout',
                    'expected_cost':0,'expected_revenue':proposal['target'],'currency':proposal['currency'],'risk':.3,'urgency':.5,'resources':['stripe']})
                if decision['decision']=='REJECT':raise ValueError('JEV rechazó checkout.')
                d['jev_decisions']=holdings.read(scope).get('jev_decisions',[])
                intent={'state':'REQUESTED','key':'zar-agency-'+lead['id']+'-'+proposal['id']};lead['checkout_intent']=intent;holdings.write(scope,d)
                result=PaymentAdapter().checkout(scope,lead,proposal,intent['key']);result.update(id=uuid.uuid4().hex,lead_id=lead['id'],proposal_id=proposal['id'])
                crm['payments'].append(result);lead['payment_id']=result['id'];intent.update(state='CONFIRMED',payment_id=result['id'])
                for row in d.get('jev_decisions',[]):
                    if row['id']==decision['id']:row['subsequent_state']='CHECKOUT_CONFIRMED_AWAITING_PAYMENT'
            elif action=='payment_sync':
                payment=find(crm['payments'],lead.get('payment_id'));value=PaymentAdapter().payment(payment['provider_id'])
                proposal=find(lead['proposals'],payment['proposal_id'])
                metadata=value.get('metadata') or {}
                if value.get('id')!=payment['provider_id'] or metadata.get('scope')!=scope or metadata.get('lead')!=lead['id'] or metadata.get('proposal')!=proposal['id']:
                    raise ValueError('Checkout no corresponde al scope/propuesta.')
                if value.get('amount_total')!=int(Decimal(payment['amount'])*100) or value.get('currency','').upper()!=payment['currency']:raise ValueError('Pago difiere de propuesta.')
                if value.get('livemode') is not True:payment.update(state='PENDING',test_mode=True,note='Stripe test mode: no ingreso real.')
                else:
                    payment['test_mode']=False
                    intent=value.get('payment_intent') or {};charge=intent.get('latest_charge') if isinstance(intent,dict) else None
                    payment['payment_intent_id']=intent.get('id') if isinstance(intent,dict) else intent
                    payment['charge_id']=charge.get('id') if isinstance(charge,dict) else charge
                    if isinstance(charge,dict) and charge.get('refunded') is True:
                        payment.update(state='REFUNDED');lead['paid']=False
                    elif value.get('payment_status')=='paid':payment.update(state='PAID');lead['paid']=True
                    elif value.get('status')=='expired':payment.update(state='EXPIRED')
                    else:payment.update(state='PENDING')
                payment['checked_at']=holdings._now();result=payment
            elif action=='receipt':
                payment=find(crm['payments'],lead.get('payment_id'))
                if payment['state']!='PAID' or payment.get('test_mode') or data.get('confirmed') is not True or not txt(data.get('bank_reference')):
                    raise ValueError('Pago real confirmado y cobro recibido con referencia bancaria requeridos.')
                amount=number(data.get('amount'),required=True)
                if not amount or amount>Decimal(payment['amount']):raise ValueError('Cobro positivo dentro del pago confirmado requerido.')
                if payment.get('receipt'):
                    if payment['receipt']['amount']!=fmt(amount) or payment['receipt']['bank_reference']!=txt(data['bank_reference'],200):raise ValueError('Cobro ya registrado con otra referencia/importe.')
                    return payment['receipt']
                holdings.add_ledger(scope,'web_agency','revenue',fmt(amount),currency=payment['currency'],source='agency_received',
                    reference=payment['provider_id'],note='Cobro bancario confirmado: '+txt(data['bank_reference'],200),verified=True)
                d['ledger']=holdings.read(scope)['ledger'];payment['receipt']={'amount':fmt(amount),'bank_reference':txt(data['bank_reference'],200),'timestamp':holdings._now()};result=payment['receipt']
            elif action=='delivery':
                if not lead.get('paid') or data.get('confirmed') is not True:raise ValueError('Entrega exige pago real confirmado y revisión explícita.')
                lead['delivery']={'url':secure_url(data.get('url')),'notes':txt(data.get('notes')),'timestamp':holdings._now(),'source':'user_confirmed_delivery'}
                transition(lead,'WON',{});result=lead['delivery']
            else:raise ValueError('Operación Agency no disponible.')
        crm['operations'].append({'id':uuid.uuid4().hex,'timestamp':holdings._now(),'action':action,'lead_id':data.get('lead_id')})
        holdings.write(scope,d);return deepcopy(result)
