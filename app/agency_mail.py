"""CRM mailbox operations; real OAuth, scoped identity and durable send intent."""
import re
from copy import deepcopy
from decimal import Decimal
from . import holdings,agency_crm

def classify(text):
    value=str(text or '').lower()
    rules=[('DO_NOT_CONTACT',r'\b(baja|unsubscribe|no me contact\w*|no nos contact\w*|do not contact)\b'),
           ('NOT_INTERESTED',r'\b(no nos interesa|no me interesa|not interested)\b'),
           ('TOO_EXPENSIVE',r'\b(muy caro|demasiado caro|too expensive|fuera de presupuesto)\b'),
           ('ACCEPTED',r'\b(acepto la propuesta|aceptamos la propuesta|we accept|de acuerdo con el precio)\b'),
           ('INTERESTED',r'\b(me interesa|nos interesa|interested)\b'),('QUESTION',r'\?|\b(pregunta|question)\b')]
    return next((name for name,pattern in rules if re.search(pattern,value)),'OTHER')

def verify(scope):
    from . import gmail
    from .business_connectors import verification
    if not gmail.is_connected():
        state='POR CONFIGURAR';result={'state':state,'missing':['Google OAuth / Gmail']}
    else:
        try:
            profile=gmail.gmail_status()
            if not profile.get('email'):raise ValueError('Buzón sin identidad verificable.')
            state='LISTO';result={'state':state,'email':profile['email'],'scope':'Gmail profile; read/send permissions checked on operation'}
        except Exception:
            state='ERROR';result={'state':state,'error':'Gmail no confirmó identidad; reautoriza los permisos.'}
    with holdings.transaction(scope):
        d=holdings.read(scope);d.setdefault('verified_connectors',{})['ZAR Mail']=verification('ZAR Mail',state,'Gmail profile; does not prove send permissions')
        if state=='LISTO':
            from .business_orchestration import note_verified_account
            note_verified_account(d,'Gmail',result['email'],'GOOGLE_OAUTH','Gmail profile')
        holdings.write(scope,d)
    return result

def send(scope,data):
    from . import gmail
    from .identity_center import require_mail
    require_mail(scope)
    if data.get('confirmed') is not True:raise ValueError('Confirma el envío del destinatario, asunto y texto revisados.')
    if not gmail.is_connected():raise ValueError('POR CONFIGURAR: conecta Gmail/OAuth real antes de enviar.')
    with holdings.transaction(scope):
        d=holdings.read(scope);lead=agency_crm.find(agency_crm.ensure(d)['leads'],data['lead_id'])
        control=d.get('orchestration',{})
        if d.get('global_stop') or control.get('mode','OFF') in {'OFF','SHADOW'} or lead['state']=='DO_NOT_CONTACT':
            raise ValueError('Envío bloqueado por STOP, modo o baja.')
        if control.get('agents',{}).get('SalesOutreachAgent',{}).get('state') in {'OFF','PAUSED'}:
            raise ValueError('SalesOutreachAgent pausado.')
        draft=agency_crm.find(lead['emails'],data['draft_id'])
        if draft.get('send_intent'):return deepcopy(draft)
        if draft.get('to')!=lead.get('email') or not draft.get('to'):raise ValueError('Email público no coincide con el lead.')
        if 'ZAR' not in draft.get('body',''):raise ValueError('Identidad ZAR requerida.')
        identity=gmail.gmail_status().get('email')
        if not identity:raise ValueError('Identidad real Gmail no verificada.')
        draft.update(send_intent='REQUESTED',sender_identity=identity)
        holdings.write(scope,d)
        previous=(lead.get('inbound') or [{}])[-1]
        try:
            result=gmail.send_message(draft['to'],draft['subject'],draft['body'],
                reply_to_message_id=previous.get('rfc_message_id'),thread_id=lead.get('thread_id'))
            if not result.get('id'):raise ValueError('Sin ID confirmado.')
        except Exception:
            draft['send_intent']='REVIEW_REQUIRED';holdings.write(scope,d)
            raise ValueError('Envío ambiguo: revisa Gmail; no se reenviará automáticamente.') from None
        draft.update(send_intent='CONFIRMED',sent=True,provider_id=result['id'],thread_id=result.get('threadId'),sent_at=holdings._now())
        from .identity_center import ensure as identity_state
        identity_state(d)['mail_audit'].append({'transaction_id':'agency:'+draft['id'],'message_id':result['id'],'thread_id':result.get('threadId'),
            'sender':identity,'recipient':draft['to'],'subject':draft['subject'],'agent':'SalesOutreachAgent','business':'web_agency',
            'client':lead['id'],'timestamp':holdings._now(),'status':'CONFIRMED','action':'send'})
        lead['thread_id']=result.get('threadId') or lead.get('thread_id')
        if lead['state'] not in {'REPLIED','NEGOTIATING','WON','DELIVERED'}:
            agency_crm.transition(lead,'CONTACTED',{'confirmed':True,'evidence':'Gmail confirmed message '+result['id']})
        holdings.write(scope,d);return deepcopy(draft)

def sync_inbound(scope,data):
    from . import gmail,agency_events
    from .identity_center import require_mail
    require_mail(scope)
    if not gmail.is_connected():raise ValueError('POR CONFIGURAR: Gmail/OAuth no conectado.')
    lead=agency_crm.find(agency_crm.ensure(holdings.read(scope))['leads'],data['lead_id'])
    address=lead.get('email','')
    if not re.fullmatch(r'[A-Za-z0-9_.+%-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}',address):raise ValueError('Email público válido requerido.')
    messages=gmail.search_messages('in:inbox from:'+address,20)
    return [agency_events.inbound(scope,{'lead_id':lead['id'],'message_id':m['id'],'auto_classify':True})
            for m in messages if lead.get('thread_id') and m.get('threadId')==lead['thread_id']]

def auto_negotiate(lead,row):
    if row['classification'] not in {'TOO_EXPENSIVE','INTERESTED','ACCEPTED'} or lead['state']=='DO_NOT_CONTACT':return
    proposal=next((p for p in lead.get('proposals',[]) if p['id']==lead.get('proposal_id')),None)
    if not proposal or lead.get('checkout_intent') or lead.get('paid'):return
    text='\n'.join(line for line in row.get('text','').splitlines() if not line.lstrip().startswith('>'))
    matches=re.findall(r'(?<!\d)(\d{1,8}(?:[.,]\d{1,2})?)\s*'+re.escape(proposal['currency'])+r'\b',text,re.I)
    if len(matches)!=1:
        row['negotiation_state']='REVIEW_AMBIGUOUS_PRICE';return
    offer=Decimal(matches[0].replace(',','.'));minimum=Decimal(proposal['minimum']);premium=Decimal(proposal['premium'])
    if not minimum<=offer<=premium:
        row['negotiation_state']='ESCALATE_PRICE_OUTSIDE_RANGE';return
    proposal_copy=dict(proposal,id=__import__('uuid').uuid4().hex,target=str(offer),source='inbound_rule_negotiation',inbound_id=row['id'])
    lead['proposals'].append(proposal_copy);lead['proposal_id']=proposal_copy['id']
    lead.setdefault('negotiations',[]).append({'inbound_id':row['id'],'offer':str(offer),'minimum':proposal['minimum'],'source':'RULE_BASED','sent':False})
    lead['emails'].append({'id':__import__('uuid').uuid4().hex,'to':lead.get('email'),'subject':'Re: Propuesta ZAR',
        'body':'Somos ZAR Web Agency. Podemos ofrecer el alcance revisado por '+str(offer)+' '+proposal['currency']+'. Confirmad el alcance antes del checkout. Para no recibir más contactos, indicad baja.',
        'state':'DRAFT','sent':False,'timestamp':holdings._now()})
    agency_crm.transition(lead,'NEGOTIATING',{'evidence':'Authenticated Gmail inbound '+row['id']})
