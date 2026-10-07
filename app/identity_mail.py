"""ZAR Mail reuses Gmail; public associations and durable, non-repeating send intent."""
import re
import json
import hashlib
from copy import deepcopy
from . import gmail,holdings
from .identity_center import ensure,require_mail

def operate(scope,action,data):
    require_mail(scope)
    if action in {'inbox','unread','search'}:return gmail.search_messages(data.get('query') or ('is:unread' if action=='unread' else 'in:inbox'),min(50,int(data.get('limit',20))))
    if action=='message':
        m=gmail.get_message(data['id']);raw=gmail.service().users().messages().get(userId='me',id=data['id'],format='full').execute();m['attachments']=gmail.attachment_metadata(raw);return m
    if action=='thread':return gmail.thread(data['id'])
    if action=='attachment':return gmail.attachment(data['id'],data['attachment_id'])
    if action=='labels':return gmail.labels()
    if action=='drafts':return gmail.list_drafts()
    if action not in {'send','reply','forward','draft','archive'}:raise ValueError('Acción Gmail no soportada.')
    if data.get('confirmed') is not True:raise ValueError('Revisa y confirma la escritura en Gmail.')
    tid=str(data.get('transaction_id') or '')
    if not re.fullmatch(r'[A-Za-z0-9_-]{8,100}',tid):raise ValueError('transaction_id estable requerido para evitar duplicados.')
    signature=hashlib.sha256(json.dumps({'action':action,'data':data},sort_keys=True).encode()).hexdigest()
    with holdings.transaction(scope):
        d=holdings.read(scope);s=ensure(d)
        if d.get('global_stop'):raise ValueError('Mail bloqueado por STOP global.')
        prior=next((r for r in s['mail_audit'] if r['transaction_id']==tid),None)
        if prior:
            if prior.get('request_hash')!=signature:raise ValueError('transaction_id reutilizado con otros datos.')
            return deepcopy(prior)
        recipient=str(data.get('to','')).strip();subject=str(data.get('subject',''))[:500];body=str(data.get('body',''))[:100000]
        if action!='archive' and not re.fullmatch(r'[^\r\n\s@]+@[^\r\n\s@]+\.[^\r\n\s@]+',recipient):raise ValueError('Un destinatario email válido requerido.')
        sender=gmail.gmail_status()['email'];reference=None;thread_id=data.get('thread_id')
        if action in {'reply','forward'}:
            original=gmail.get_message(data['id']);reference=original.get('rfc_message_id') if action=='reply' else None
            if action=='reply':thread_id=original['threadId']
            else:body+='\n\n--- Forwarded message ---\nFrom: '+original['from']+'\nSubject: '+original['subject']+'\n'+original['text']
        row={'transaction_id':tid,'message_id':None,'thread_id':thread_id,'sender':sender,'recipient':recipient,'subject':subject,
             'agent':str(data.get('agent','Pablo'))[:100],'business':str(data.get('business',''))[:100],'client':str(data.get('client',''))[:100],
             'timestamp':holdings._now(),'status':'PENDING','action':action,'request_hash':signature}
        s['mail_audit'].append(row);holdings.write(scope,d)
        try:
            if action=='archive':result=gmail.archive(data['id'])
            else:result=gmail.send_with_attachments(recipient,subject,body,data.get('attachments'),thread_id,reference,draft=action=='draft')
            message=result.get('message',result);row.update(message_id=message.get('id'),thread_id=message.get('threadId',thread_id),draft_id=result.get('id') if action=='draft' else None,status='CONFIRMED')
            if not row['message_id']:raise ValueError('Sin ID confirmado.')
        except Exception:
            row['status']='REVIEW_REQUIRED';holdings.write(scope,d)
            raise ValueError('Resultado ambiguo: revisar Gmail. No se repetirá automáticamente.') from None
        holdings.write(scope,d);return deepcopy(row)
