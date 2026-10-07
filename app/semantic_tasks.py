"""Verb/object planning, durable dependencies and reviewed external actions."""
import re,secrets
from copy import deepcopy
from . import holdings
BOOT_ID=secrets.token_hex(12)

def plan(message):
    text=str(message or '').strip();low=text.casefold()
    research=bool(re.search(r'\b(investiga(?:r)?|investigación|analiza|compara|averigua|busca ayudas)\b',low))
    report=bool(re.search(r'\b(haz(?:me)?|crea|prepara|genera|redacta)\b.{0,55}\b(informe|documento|presentaci[oó]n|hoja|presupuesto|tabla)\b',low))
    send=bool(re.search(r'\b(env[ií]a(?:selo|lo|le|me)?|manda(?:selo|lo|le)?|enviar|m[aá]ndaselo)\b',low))
    resolve=bool(re.search(r'\bbusca\b.{0,25}\b(correo|email|direcci[oó]n)\b.{0,20}\bde\b',low))
    attach=bool(re.search(r'\badjunta(?:r)?\b',low))
    draft=bool(re.search(r'\b(redacta|prepara|escribe)\b.{0,30}\b(correo|email|mensaje)\b',low))
    read=bool(re.search(r'\b(mira|lee|abre|revisa)\b.{0,18}\b(mi correo|mis correos|bandeja|inbox|email)\b',low)) and not (research or report or send or attach or draft or resolve)
    if not any((research,report,send,resolve,attach,draft,read)):return None
    contact_match=re.search(r'\b(?:a|de)\s+([A-ZÁÉÍÓÚÑ][\wáéíóúñÁÉÍÓÚÑ.-]*(?:\s+[A-ZÁÉÍÓÚÑ][\wáéíóúñÁÉÍÓÚÑ.-]*)*)',text)
    if not contact_match and (resolve or send or draft):
        contact_match=re.search(r'(?:correo\s+de|email\s+de|env[ií]a\w*\s+a|manda\w*\s+a|m[aá]ndaselo\s+a)\s+([^,;.!?]+)',text,re.I)
    explicit=re.search(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}',text)
    contact=explicit.group() if explicit else contact_match.group(1).strip(' .;,') if contact_match else None
    topic=re.sub(r'^(investiga|analiza|compara|averigua)\s+','',text,flags=re.I)
    topic=re.split(r'[,;]|\by después\b|\bdespués\b|\by (?:haz|crea|prepara|envía|manda)',topic,flags=re.I)[0].strip()
    kinds=[]
    if research:kinds.append('RESEARCH')
    if report:kinds.append('CREATE_REPORT')
    if resolve or send or draft:kinds.append('RESOLVE_CONTACT')
    if send or draft:kinds.append('DRAFT_EMAIL')
    if attach or (send and report):kinds.append('ATTACH_ARTIFACT')
    if send:kinds.append('SEND_EMAIL')
    if read:kinds.append('READ_MAIL')
    if not kinds:return None
    fmt='pptx' if re.search('presentaci[oó]n',low) else 'xlsx' if re.search(r'\b(hoja|tabla|presupuesto)\b',low) else 'docx' if 'docx' in low else 'md' if 'markdown' in low else 'pdf'
    steps=[{'id':str(i+1),'kind':kind,'order':i+1,'dependencies':[str(i)] if i else [],'status':'PLANNED','outputs':None,'error':None} for i,kind in enumerate(kinds)]
    return {'goal':text,'topic':topic,'subtasks':steps,'order':[s['id'] for s in steps],'dependencies':{s['id']:s['dependencies'] for s in steps},'entities':{'topic':topic,'recipient':contact},'contacts':[contact] if contact else [],'format':fmt,
        'required_tools':kinds,'required_artifacts':[fmt] if report else [],'external_actions':['SEND_EMAIL'] if send else [],'confirmation_requirements':['REVIEW_EMAIL_AND_RECIPIENT'] if send else [],'expected_outputs':kinds,'status':'PLANNED'}

def create(scope,message):
    task=plan(message)
    if not task:raise ValueError('No se ha identificado una tarea estructurada; especifica verbo y objetivo.')
    task.update(id=secrets.token_hex(12),created_at=holdings._now(),updated_at=holdings._now(),current_step=None,outputs={},errors=[])
    with holdings.transaction(scope):
        d=holdings.read(scope);d.setdefault('semantic_tasks',[]).append(task);holdings.write(scope,d)
    return deepcopy(task)

def tasks(scope):return deepcopy(holdings.read(scope).get('semantic_tasks',[]))
def get(scope,identifier):
    task=next((x for x in tasks(scope) if x['id']==identifier),None)
    if not task:raise ValueError('Tarea no encontrada para este usuario.')
    return task
def save(scope,task):
    task['updated_at']=holdings._now()
    with holdings.transaction(scope):
        d=holdings.read(scope);rows=d.setdefault('semantic_tasks',[])
        for i,row in enumerate(rows):
            if row['id']==task['id']:rows[i]=deepcopy(task);break
        from .business_orchestration import ensure
        agents=ensure(d)['agents'];roles={'RESEARCH':'ResearchAgent','CREATE_REPORT':'ReportAgent','RESOLVE_CONTACT':'ContactResolver','DRAFT_EMAIL':'MailAgent','ATTACH_ARTIFACT':'ArtifactOrchestrator','SEND_EMAIL':'MailAgent'}
        for step in task['subtasks']:
            agent=agents.get(roles.get(step['kind']))
            if agent and step['status'] in {'RUNNING','WAITING','ERROR'}:agent.update(state=step['status'],current_tasks=[task['id']],last_heartbeat=holdings._now())
            elif agent and task['id'] in agent.get('current_tasks',[]):agent.update(state='IDLE',current_tasks=[],last_heartbeat=holdings._now())
        holdings.write(scope,d)

def run(scope,identifier,confirmed=False,selected_email=None):
    from . import web_search,artifact_engine,contact_resolver,identity_mail
    from .file_store import FileStore
    from .google_contacts import search_contacts
    # A persistent RUNNING/ambiguous step is never silently repeated after restart.
    with holdings.transaction(scope):
        task=get(scope,identifier)
        if task['status']=='RUNNING' and task.get('runner_boot')==BOOT_ID:return task
        if task.get('runner_boot')!=BOOT_ID:
            for step in task['subtasks']:
                if step['status']=='RUNNING':step.update(status='WAITING',error='Ejecución interrumpida por reinicio; outputs anteriores conservados.')
        if task['status']=='DONE':return task
        if any(s['status']=='RUNNING' for s in task['subtasks']):
            task['status']='WAITING';task['errors'].append('Paso interrumpido: revisar antes de reintentar una acción externa.');save(scope,task);return task
        task.update(status='RUNNING',runner_boot=BOOT_ID);save(scope,task)
    for step in task['subtasks']:
        if step['status']=='DONE':continue
        task['current_step']=step['id'];step.update(status='RUNNING',error=None);save(scope,task)
        try:
            kind=step['kind'];output=None
            if holdings.read(scope).get('global_stop'):raise ValueError('STOP GLOBAL activo; tarea conservada.')
            if kind=='RESEARCH':
                output=web_search.google_web_search(task['topic'],'Contrasta fuentes, fechas y requisitos. Distingue hechos, opiniones y fechas no verificadas. Incluye resumen ejecutivo, contexto, hallazgos, comparativa, recomendaciones y próximos pasos. No inventes fuentes.')
                if not output.get('ok') or not output.get('sources'):raise ValueError('Investigación no confirmó fuentes web; se conserva la tarea sin inventar resultados.')
                output.update(retrieved_at=holdings._now(),subquestions=['¿Qué fuentes primarias respaldan el tema?','¿Qué requisitos y fechas siguen vigentes?','¿Qué diferencias y próximos pasos hay?'],date_verification='Solo fechas respaldadas en el texto citado; las restantes no verificadas')
            elif kind=='CREATE_REPORT':
                research=task['outputs'].get('RESEARCH',{});content=research.get('text')
                if not content:
                    task['status']='WAITING';step['status']='WAITING';step['error']='Indica el contenido o completa una investigación antes de crear el informe.';save(scope,task);return task
                output=artifact_engine.create(task['topic'],content,task['format'],research.get('sources'),task['id'])
            elif kind=='RESOLVE_CONTACT':
                name=task['entities'].get('recipient')
                if name and re.fullmatch(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}',name):output={'status':'RESOLVED','contact':{'contact_id':None,'display_name':name,'emails':[name],'phones':[],'aliases':[],'source':'USER_EXPLICIT_EMAIL','confidence':1}}
                else:output=contact_resolver.resolve(scope,name)
                if selected_email:
                    matches=[c for c in output.get('candidates',[]) if selected_email in c['emails']]
                    if len(matches)!=1:raise ValueError('La dirección seleccionada no coincide inequívocamente con un contacto real.')
                    output.update(status='RESOLVED',contact=dict(matches[0],emails=[selected_email]))
                if output['status']!='RESOLVED':
                    task['outputs'][kind]=output;task['status']='WAITING';step.update(status='WAITING',outputs=output,error='Selecciona un contacto real o indica su dirección.');save(scope,task);return task
                contact_resolver.remember(scope,output['contact'],tasks=[task['id']])
            elif kind=='DRAFT_EMAIL':
                contact=task['outputs']['RESOLVE_CONTACT']['contact'];artifact=task['outputs'].get('CREATE_REPORT')
                output={'to':contact['emails'][0],'cc':'','bcc':'','subject':task['topic'][:150],'body':'Hola '+contact['display_name']+',\n\n'+('Adjunto el informe solicitado.\n\nSaludos,\nZAR' if artifact else task['goal']),'artifact_ids':[artifact['artifact_id']] if artifact else [],'status':'LOCAL_DRAFT_NOT_SENT'}
            elif kind=='ATTACH_ARTIFACT':
                artifact=task['outputs'].get('CREATE_REPORT')
                if not artifact:raise ValueError('Selecciona un archivo existente; no se inventa un adjunto.')
                FileStore().read(artifact['artifact_id']);output={'artifact_ids':[artifact['artifact_id']],'status':'ATTACHED_TO_REVIEW'}
            elif kind=='SEND_EMAIL':
                draft=task['outputs']['DRAFT_EMAIL']
                if confirmed is not True:
                    task['status']='WAITING';step.update(status='WAITING',error='Revisa destinatario, mensaje y adjuntos; confirma Enviar.');save(scope,task);return task
                output=identity_mail.operate(scope,'send',{**draft,'confirmed':True,'transaction_id':'task_'+task['id'],'agent':'MailAgent','task_id':task['id']})
                if output['status']!='CONFIRMED':raise ValueError('Envío no confirmado; revisar Gmail antes de reintentar.')
                contact=task['outputs']['RESOLVE_CONTACT']['contact'];contact_resolver.remember(scope,contact,files=draft['artifact_ids'],tasks=[task['id']])
                for fid in draft['artifact_ids']:FileStore().metadata(fid,associated_contacts=[contact.get('contact_id') or draft['to']])
            elif kind=='READ_MAIL':output=identity_mail.operate(scope,'inbox',{})
            else:raise ValueError('Paso no soportado.')
            step.update(status='DONE',outputs=output);task['outputs'][kind]=output;save(scope,task)
        except Exception as exc:
            step.update(status='ERROR',error=str(exc));task.update(status='ERROR');task['errors'].append(str(exc));save(scope,task);return task
    task.update(status='DONE',current_step=None);save(scope,task);return task
