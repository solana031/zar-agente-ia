"""Native Workspace plans and validated Forms requests; reuse existing OAuth."""
THEMES={
 'ZAR':('#17130F','#DAB179','Arial'),'REPOSNEWS':('#142238','#F59E0B','Arial'),
 'CORPORATE':('#17365D','#4472C4','Arial'),'EDITORIAL':('#202020','#A64B2A','Georgia'),
 'MINIMAL':('#202020','#777777','Arial'),'DARK':('#111827','#FBBF24','Arial'),
 'LIGHT':('#FFFFFF','#1F2937','Arial')}


def form_requests(items):
    if not isinstance(items,list) or not 1<=len(items)<=100:raise ValueError('Entre 1 y 100 elementos por formulario.')
    requests=[]
    for index,src in enumerate(items):
        title=str(src.get('title') or '').strip();kind=src.get('kind','TEXT')
        if not title:raise ValueError('Cada elemento necesita un título.')
        item={'title':title[:1000],'description':str(src.get('description') or '')[:3000]}
        if kind=='SECTION':item['pageBreakItem']={}
        elif kind=='HEADING':item['textItem']={}
        else:
            q={'required':bool(src.get('required'))}
            if kind in ('TEXT','PARAGRAPH'):q['textQuestion']={'paragraph':kind=='PARAGRAPH'}
            elif kind in ('RADIO','CHECKBOX','DROP_DOWN'):
                options=src.get('options') or []
                if not 1<=len(options)<=100 or any(not isinstance(v,str) or not v.strip() for v in options):raise ValueError('Opciones vacías o no válidas.')
                q['choiceQuestion']={'type':kind,'options':[{'value':v.strip()[:1000]} for v in options],'shuffle':False}
            elif kind=='SCALE':
                low=int(src.get('low',1));high=int(src.get('high',5))
                if low not in (0,1) or not 2<=high<=10:raise ValueError('Escala no admitida por Forms.')
                q['scaleQuestion']={'low':low,'high':high}
            elif kind=='DATE':q['dateQuestion']={'includeTime':False,'includeYear':True}
            else:raise ValueError('Tipo de pregunta no admitido.')
            if src.get('correct_answer') is not None:
                answer=str(src['correct_answer'])
                if kind in ('RADIO','CHECKBOX','DROP_DOWN') and answer not in src.get('options',[]):raise ValueError('Respuesta correcta fuera de las opciones.')
                q['grading']={'pointValue':max(1,min(100,int(src.get('points',1)))),'correctAnswers':{'answers':[{'value':answer}]}}
            item['questionItem']={'question':q}
        requests.append({'createItem':{'item':item,'location':{'index':index}}})
    return requests


def record(result,kind,title,context=''):
    import json
    from datetime import datetime,timezone
    from . import file_store,holdings
    from .user_scope import get_current_user,safe_slug
    identifier=next((result.get(k) for k in ('documentId','presentationId','spreadsheetId','formId') if result.get(k)),None)
    if not identifier:return result
    now=datetime.now(timezone.utc).isoformat();scope=get_current_user()
    path=file_store.DATA_DIR/'users'/safe_slug(scope)/'workspace_artifacts.json'
    with holdings.transaction('workspace-artifacts-'+safe_slug(scope)):
        path.parent.mkdir(parents=True,exist_ok=True)
        data=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
        old=data.get(identifier,{})
        data[identifier]={'id':identifier,'file_id':identifier,'artifact_id':result.get('artifact_id',old.get('artifact_id',identifier)),'url':result.get('url'),'Drive URL':result.get('url'),'type':kind,'title':title,
                          'owner':scope,'context':context,'created_at':old.get('created_at',now),'updated_at':now}
        tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8');tmp.replace(path)
    return result


def build_form(title,description,items):
    from . import google_workspace as gw
    requests=form_requests(items)  # Validate completely before creating anything externally.
    result=gw.forms_create(title,description)
    identifier=result['formId']
    gw.forms_service().forms().batchUpdate(formId=identifier,body={'requests':requests}).execute()
    actual=gw.forms_get(identifier)
    if len(actual.get('items',[]))!=len(items):raise RuntimeError('FORM_VALIDATION_FAILED: '+identifier)
    result.update(ok=True,items=len(items),preview=result.get('responderUri'),validation='API_ITEM_COUNT_VERIFIED')
    return record(result,'FORM',title)
