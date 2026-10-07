from email.header import decode_header
import base64
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from .cloud_auth import get_credentials

CREDENTIALS_FILE = None

def is_connected():
    return bool(get_credentials())

def service():
    creds = get_credentials()
    if not creds:
        raise RuntimeError('Gmail no está conectado. Pulsa Conectar Gmail.')
    return build('gmail','v1',credentials=creds,cache_discovery=False)

def decode_header_value(value):
    if not value: return ''
    out=[]
    for chunk, enc in decode_header(value):
        out.append(chunk.decode(enc or 'utf-8',errors='replace') if isinstance(chunk,bytes) else chunk)
    return ''.join(out)

def _headers(msg):
    return {h['name'].lower(): decode_header_value(h.get('value','')) for h in msg.get('payload',{}).get('headers',[])}

def recent_messages(query='in:inbox', max_results=10):
    svc=service(); result=svc.users().messages().list(userId='me',q=query,maxResults=max_results,includeSpamTrash=False).execute(); out=[]
    for item in result.get('messages',[]):
        msg=svc.users().messages().get(userId='me',id=item['id'],format='metadata',metadataHeaders=['From','To','Subject','Date']).execute(); h=_headers(msg); labels=msg.get('labelIds',[])
        out.append({'id':msg.get('id'),'rfc_message_id':h.get('message-id'),'threadId':msg.get('threadId'),'from':h.get('from',''),'to':h.get('to',''),'subject':h.get('subject',''),'date':h.get('date',''),'snippet':msg.get('snippet',''),'unread':'UNREAD' in labels})
    return out

def search_messages(query,max_results=10): return recent_messages(query,max_results)

def _decode_part(data):
    if not data: return ''
    try: return base64.urlsafe_b64decode(data+'===').decode('utf-8',errors='replace')
    except Exception: return ''

def extract_plain_text(message):
    payload=message.get('payload',{}); texts=[]
    def walk(part):
        if part.get('mimeType')=='text/plain' and part.get('body',{}).get('data'): texts.append(_decode_part(part['body']['data']))
        for child in part.get('parts',[]) or []: walk(child)
    walk(payload)
    if payload.get('mimeType')=='text/plain' and payload.get('body',{}).get('data'): texts.append(_decode_part(payload['body']['data']))
    return '\n\n'.join(t for t in texts if t).strip() or message.get('snippet','')

def get_message(message_id):
    msg=service().users().messages().get(userId='me',id=message_id,format='full').execute(); h=_headers(msg)
    return {'id':msg.get('id'),'rfc_message_id':h.get('message-id'),'threadId':msg.get('threadId'),'from':h.get('from',''),'to':h.get('to',''),'subject':h.get('subject',''),'date':h.get('date',''),'snippet':msg.get('snippet',''),'text':extract_plain_text(msg)[:30000],'labels':msg.get('labelIds',[])}

def get_latest():
    msgs=recent_messages('in:inbox',1); return get_message(msgs[0]['id']) if msgs else None

def gmail_status():
    p=service().users().getProfile(userId='me').execute(); return {'ok':True,'email':p.get('emailAddress',''),'messagesTotal':p.get('messagesTotal',0)}

def _raw(to,subject,body,reply_to_message_id=None):
    from email.message import EmailMessage
    msg=EmailMessage(); msg['To']=to; msg['Subject']=subject
    if reply_to_message_id: msg['In-Reply-To']=reply_to_message_id; msg['References']=reply_to_message_id
    msg.set_content(body)
    return base64.urlsafe_b64encode(msg.as_bytes()).decode('utf-8')

def thread(thread_id):
    result=service().users().threads().get(userId='me',id=thread_id,format='full').execute()
    return {'id':result.get('id'),'messages':[{'id':m['id'],'threadId':m.get('threadId'),'headers':_headers(m),'text':extract_plain_text(m),'parts':attachment_metadata(m)} for m in result.get('messages',[])]}

def attachment_metadata(message):
    rows=[]
    def walk(part):
        if part.get('filename'):rows.append({'filename':part['filename'],'mimeType':part.get('mimeType'),'attachment_id':part.get('body',{}).get('attachmentId'),'size':part.get('body',{}).get('size')})
        for child in part.get('parts',[]):walk(child)
    walk(message.get('payload',{}));return rows

def attachment(message_id,attachment_id):
    return service().users().messages().attachments().get(userId='me',messageId=message_id,id=attachment_id).execute()

def labels():return service().users().labels().list(userId='me').execute().get('labels',[])

def archive(message_id):
    return service().users().messages().modify(userId='me',id=message_id,body={'removeLabelIds':['INBOX']}).execute()

def list_drafts():return service().users().drafts().list(userId='me',maxResults=30).execute().get('drafts',[])

def send_with_attachments(to,subject,body,attachments=None,thread_id=None,reply_to_message_id=None,draft=False,cc='',bcc=''):
    from email.message import EmailMessage
    msg=EmailMessage();msg['To']=to;msg['Subject']=subject;msg.set_content(body)
    if cc:msg['Cc']=cc
    if bcc:msg['Bcc']=bcc
    if reply_to_message_id:msg['In-Reply-To']=reply_to_message_id;msg['References']=reply_to_message_id
    total=0
    for item in attachments or []:
        content=base64.b64decode(item['data'],validate=True);total+=len(content)
        if total>15*1024*1024:raise ValueError('Adjuntos limitados a 15 MB.')
        mime=str(item.get('mime','application/octet-stream')).split('/',1)
        if len(mime)!=2:raise ValueError('MIME no válido.')
        msg.add_attachment(content,maintype=mime[0],subtype=mime[1],filename=str(item.get('filename','attachment'))[:200])
    payload={'raw':base64.urlsafe_b64encode(msg.as_bytes()).decode()}
    if thread_id:payload['threadId']=thread_id
    svc=service().users()
    return svc.drafts().create(userId='me',body={'message':payload}).execute() if draft else svc.messages().send(userId='me',body=payload).execute()

def send_message(to,subject,body,reply_to_message_id=None,thread_id=None):
    res={'raw':_raw(to,subject,body,reply_to_message_id)}
    if thread_id: res['threadId']=thread_id
    return service().users().messages().send(userId='me',body=res).execute()

def create_draft(to,subject,body,reply_to_message_id=None,thread_id=None):
    msg={'raw':_raw(to,subject,body,reply_to_message_id)}
    if thread_id: msg['threadId']=thread_id
    return service().users().drafts().create(userId='me',body={'message':msg}).execute()

def update_draft(draft_id,to,subject,body,reply_to_message_id=None,thread_id=None):
    msg={'raw':_raw(to,subject,body,reply_to_message_id)}
    if thread_id: msg['threadId']=thread_id
    return service().users().drafts().update(userId='me',id=draft_id,body={'message':msg}).execute()
