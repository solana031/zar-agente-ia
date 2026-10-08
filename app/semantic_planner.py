"""Validated semantic plans and scoped references; planning never executes tools."""
import json,re
from copy import deepcopy
from datetime import datetime,timedelta,timezone
from . import holdings

KINDS={'RESEARCH','CREATE_REPORT','RESOLVE_REFERENCE','RESOLVE_CONTACT','DRAFT_EMAIL','ATTACH_ARTIFACT','SEND_EMAIL','READ_MAIL'}

def build(scope,message,fallback,allow_model=True):
    base=fallback(message)
    if not base:raise ValueError('Describe una acción y su objetivo.')
    text=message.casefold();state=holdings.read(scope)
    previous=next((t for t in reversed(state.get('semantic_tasks',[])) if t.get('outputs') and t.get('status') in {'DONE','WAITING'}),None)
    reference=bool(re.search(r'\b(lo anterior|esto|eso|esas cifras|esas fotos|las fotos que|el documento que|el informe que|adjunta el informe|m[aá]ndasela|env[ií]aselo tambi[eé]n|que hicimos ayer)\b',text))
    if any(s['kind']=='RESEARCH' for s in base['subtasks']) and re.fullmatch(r'.*\bm[aá]ndasela\b.*',text) and not re.search(r'lo anterior|esto|eso|esas cifras|esas fotos|el documento|ayer',text):reference=False
    base['planner_version']=2;base['planning_engine']='VERB_OBJECT_CONTEXT'
    base['references']=[];base['conditions']=re.findall(r'\bsi\s+([^,;.]+)',message,re.I)
    if reference:
        base['references']=[{'description':message,'status':'UNRESOLVED'}]
        from .context import get_context
        context=get_context();uploaded=context.get('last_uploaded_file') or {}
        if 'ayer' in text:
            from .file_store import FileStore
            date=(datetime.now(timezone.utc)-timedelta(days=1)).date().isoformat()
            files=[f for f in FileStore().list() if str(f.get('created_at','')).startswith(date)]
            if len(files)==1:base['references'][0].update(status='RESOLVED',artifact_id=files[0]['id'])
        elif ('foto' in text or 'archivo que' in text) and uploaded.get('id'):
            base['references'][0].update(status='RESOLVED',artifact_id=uploaded['id'])
        elif previous:
            base['references'][0].update(status='RESOLVED',task_id=previous['id'])
            base['topic']=previous.get('topic',base['topic'])
            if not base['entities'].get('recipient'):
                contact=previous.get('outputs',{}).get('RESOLVE_CONTACT',{}).get('contact') or {}
                if len(contact.get('emails',[]))==1:base['entities']['recipient']=contact['emails'][0]
        base['subtasks'].insert(0,{'kind':'RESOLVE_REFERENCE'})
    if allow_model:
        from .config import load
        cfg=load()
        if any((cfg.get(key) or {}).get('api_key') for key in ('api','openai','openrouter')):
            try:
                from .agent import api_text
                prompt='Planifica sin ejecutar herramientas. Devuelve únicamente JSON: {"topic":string,"steps":[{"kind":string,"depends_on":[índices cero]}],"recipient":string|null,"conditions":[string],"format":"pdf|docx|xlsx|pptx|md"}. Interpreta verbos, objetos, secuencia, pronombres, referencias y condiciones. Nunca inventes email o datos. Un email mencionado no implica READ_MAIL. Acciones permitidas: '+','.join(sorted(KINDS))+'. Contactos solo literales de la petición o referencia resuelta. Contexto: '+json.dumps({'previous_goal':previous.get('goal') if previous and reference else None,'base':base},ensure_ascii=False)+'\nPetición: '+message
                answer=api_text(prompt,cfg);answer=re.sub(r'^```(?:json)?\s*|\s*```$','',answer.strip());candidate=json.loads(answer)
                steps=candidate.get('steps') or []
                if not 1<=len(steps)<=16 or any(s.get('kind') not in KINDS for s in steps):raise ValueError('Plan de herramientas inválido.')
                kinds=[s['kind'] for s in steps]
                if len(kinds)!=len(set(kinds)):raise ValueError('Pasos repetidos sin identidad independiente.')
                original={s['kind'] for s in base['subtasks']}
                if not original.issubset(kinds):raise ValueError('El plan omite una acción solicitada.')
                if any(k in kinds and k not in original for k in ('SEND_EMAIL','READ_MAIL','ATTACH_ARTIFACT')):raise ValueError('Acción externa no solicitada.')
                producers={'CREATE_REPORT':['RESEARCH','RESOLVE_REFERENCE'],'DRAFT_EMAIL':['CREATE_REPORT','RESOLVE_REFERENCE','RESOLVE_CONTACT'],'ATTACH_ARTIFACT':['CREATE_REPORT','RESOLVE_REFERENCE'],'SEND_EMAIL':['DRAFT_EMAIL','ATTACH_ARTIFACT','RESOLVE_CONTACT']}
                for kind,required in producers.items():
                    if kind in kinds and any(k in kinds and kinds.index(k)>=kinds.index(kind) for k in required):raise ValueError('El resultado debe existir antes de consumirse.')
                if 'SEND_EMAIL' in kinds and not all(k in kinds for k in ('RESOLVE_CONTACT','DRAFT_EMAIL')):raise ValueError('Envío sin destinatario y borrador.')
                for i,s in enumerate(steps):
                    if any(not isinstance(d,int) or d<0 or d>=i for d in s.get('depends_on',[])):raise ValueError('Dependencia futura o cíclica.')
                recipient=candidate.get('recipient')
                if recipient and recipient.casefold() not in text and recipient!=base['entities'].get('recipient'):raise ValueError('Destinatario no acreditado.')
                if reference and 'RESOLVE_REFERENCE' not in kinds:
                    for s in steps:s['depends_on']=[d+1 for d in s.get('depends_on',[])]
                    steps.insert(0,{'kind':'RESOLVE_REFERENCE'})
                base['subtasks']=steps;base['topic']=str(candidate.get('topic') or base['topic'])[:500]
                if recipient:base['entities']['recipient']=recipient
                if candidate.get('format') in {'pdf','docx','xlsx','pptx','md'}:base['format']=candidate['format']
                base['conditions']=list(dict.fromkeys(base['conditions']+[str(x) for x in candidate.get('conditions',[])]))
                base['planning_engine']='VALIDATED_SEMANTIC_MODEL'
            except Exception:
                base['planning_note']='Modelo no confirmó un plan válido; se conserva el plan contextual y sus ambigüedades.'
    if re.search(r'\bmi (?:propio )?(?:email|correo)\b',text):base['entities']['recipient']='SELF'
    kinds=[s['kind'] for s in base['subtasks']]
    ids={kind:str(i+1) for i,kind in enumerate(kinds)}
    dependencies={'CREATE_REPORT':['RESEARCH','RESOLVE_REFERENCE'],'DRAFT_EMAIL':['CREATE_REPORT','RESOLVE_REFERENCE','RESOLVE_CONTACT'],'ATTACH_ARTIFACT':['CREATE_REPORT','RESOLVE_REFERENCE','DRAFT_EMAIL'],'SEND_EMAIL':['DRAFT_EMAIL','ATTACH_ARTIFACT','RESOLVE_CONTACT']}
    steps=[]
    for i,s in enumerate(base['subtasks']):
        deps=list(dict.fromkeys([str(d+1) for d in s.get('depends_on',[])]+[ids[k] for k in dependencies.get(s['kind'],[]) if k in ids and int(ids[k])<i+1]))
        if s['kind']=='RESOLVE_CONTACT':deps=[]
        steps.append({'id':str(i+1),'kind':s['kind'],'order':i+1,'dependencies':deps,'status':'PLANNED','outputs':None,'error':None})
    base.update(subtasks=steps,steps=deepcopy(steps),order=[s['id'] for s in steps],dependencies={s['id']:s['dependencies'] for s in steps},required_tools=kinds,tools=kinds,artifacts=[base['format']] if 'CREATE_REPORT' in kinds else [],external_actions=['SEND_EMAIL'] if 'SEND_EMAIL' in kinds else [],confirmations=['REVIEW_EMAIL_AND_RECIPIENT'] if 'SEND_EMAIL' in kinds else [],features={'MULTI_INTENT':len(steps)>1,'SEQUENCE':len(steps)>1,'DEPENDENCY':any(s['dependencies'] for s in steps),'CONDITIONAL':bool(base['conditions']),'REFERENCE':reference,'PRONOUN':bool(re.search(r'\b(esto|eso|selo|anterior|esas)\b',text)),'CONTACT':bool(base['entities'].get('recipient')),'TEMPORAL_REFERENCE':'ayer' in text,'EXTERNAL_ACTION':'SEND_EMAIL' in kinds,'FOLLOW_UP':reference})
    base['features'].update(PERSON=bool(base['entities'].get('recipient')),ARTIFACT='CREATE_REPORT' in kinds or 'ATTACH_ARTIFACT' in kinds,CONFIRMATION=bool(base['confirmations']))
    base['contacts']=[base['entities']['recipient']] if base['entities'].get('recipient') else []
    return base

def resolve_reference(scope,task,selected_artifact_id=None):
    from .file_store import FileStore
    store=FileStore();refs=task.get('references') or []
    ref=refs[0] if refs else {}
    if selected_artifact_id:ref={'artifact_id':selected_artifact_id,'status':'RESOLVED'}
    if ref.get('artifact_id'):
        item=store.metadata(ref['artifact_id']);store.read(item['id'])
        artifact={'artifact_id':item['id'],'title':item.get('title',item['name']),'type':item.get('type',item['mime']),'download_url':'/api/files/'+item['id']+'/download'}
        return {'status':'RESOLVED','artifact':artifact,'research':{'text':item.get('retrieval_text') or item.get('note'),'sources':[]}}
    if ref.get('task_id'):
        previous=next((t for t in holdings.read(scope).get('semantic_tasks',[]) if t['id']==ref['task_id']),None)
        if previous:return {'status':'RESOLVED','task_id':previous['id'],'artifact':previous.get('outputs',{}).get('CREATE_REPORT'),'research':previous.get('outputs',{}).get('RESEARCH')}
    return {'status':'WAITING','reason':'Selecciona un archivo o una tarea acreditada; referencia no inequívoca.','candidates':[{'id':f['id'],'name':f['name']} for f in store.list()[:100]]}
