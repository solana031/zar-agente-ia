"""Explicit controlled provider writes; persist IDs before subsequent edits."""
from . import holdings,google_workspace as w,identity_center
import threading
_locks={};_guard=threading.Lock()

def verify(scope):
    with _guard:lock=_locks.setdefault(scope,threading.Lock())
    if not lock.acquire(blocking=False):raise ValueError('La verificación ya está en curso para esta cuenta.')
    try:return _verify(scope)
    finally:lock.release()

def _verify(scope):
    if identity_center.require_mail(scope)!='zaragente031@gmail.com':raise ValueError('Conecta y verifica primero la identidad operativa de ZAR.')
    result={}
    for target in ('DOCS','SHEETS','SLIDES'):
        with holdings.transaction(scope):
            d=holdings.read(scope);row=d.setdefault('workspace_tests',{}).setdefault(target,{})
            if row.get('status')=='CONNECTED':result[target]=dict(row);continue
            identifier=row.get('id')
        def store(values):
            with holdings.transaction(scope):
                d=holdings.read(scope);d.setdefault('workspace_tests',{}).setdefault(target,{}).update(values);holdings.write(scope,d)
        creation_attempt=row.get('status') in {'CREATING','AMBIGUOUS_CREATION'}
        try:
            if not identifier:
                # A lost create response remains ambiguous: never blindly repeat it.
                if row.get('status') in {'CREATING','AMBIGUOUS_CREATION'}:raise ValueError('Creación anterior no confirmada; revisar Drive antes de repetir.')
                creation_attempt=True;store({'status':'CREATING'})
                if target=='DOCS':created=w.docs_create('ZAR Workspace Test - Docs');identifier=created['documentId']
                elif target=='SHEETS':created=w.sheets_create('ZAR Workspace Test - Sheets');identifier=created['spreadsheetId']
                else:created=w.slides_create('ZAR Workspace Test - Slides');identifier=created['presentationId']
                store({'id':identifier,'url':created['url'],'status':'CREATED'})
            if target=='DOCS':
                svc=w.docs_service().documents();doc=svc.get(documentId=identifier).execute()
                content=str(doc.get('body',{}))
                if 'ZAR DOCS OK' not in content:svc.batchUpdate(documentId=identifier,body={'requests':[{'insertText':{'location':{'index':1},'text':'ZAR DOCS OK\n'}}]}).execute()
                svc.batchUpdate(documentId=identifier,body={'requests':[{'updateParagraphStyle':{'range':{'startIndex':1,'endIndex':12},'paragraphStyle':{'namedStyleType':'HEADING_1'},'fields':'namedStyleType'}}]}).execute()
                if 'ZAR DOCS OK' not in str(svc.get(documentId=identifier).execute()):raise ValueError('Lectura no confirma contenido Docs.')
                evidence='create/write/read/edit/ID/URL'
            elif target=='SHEETS':
                svc=w.sheets_service().spreadsheets();meta=svc.get(spreadsheetId=identifier).execute();sheet=meta['sheets'][0]['properties'];sid=sheet['sheetId']
                svc.batchUpdate(spreadsheetId=identifier,body={'requests':[{'updateSheetProperties':{'properties':{'sheetId':sid,'title':'Test','gridProperties':{'frozenRowCount':1}},'fields':'title,gridProperties.frozenRowCount'}},{'repeatCell':{'range':{'sheetId':sid,'startRowIndex':0,'endRowIndex':1},'cell':{'userEnteredFormat':{'textFormat':{'bold':True},'backgroundColor':{'red':.85,'green':.68,'blue':.44}}},'fields':'userEnteredFormat'}}]}).execute()
                svc.values().update(spreadsheetId=identifier,range='Test!A1:C2',valueInputOption='USER_ENTERED',body={'values':[['ZAR','SHEETS','OK'],['=1+1']]}).execute()
                values=svc.values().get(spreadsheetId=identifier,range='Test!A1:C2').execute().get('values',[])
                if not values or values[0]!=['ZAR','SHEETS','OK'] or str(values[1][0])!='2':raise ValueError('Lectura no confirma contenido y fórmula Sheets.')
                evidence='create/write/format/formula/read/ID/URL'
            else:
                svc=w.slides_service().presentations();doc=svc.get(presentationId=identifier).execute()
                if not any(x['objectId']=='zar_workspace_test' for x in doc.get('slides',[])):
                    requests=[{'createSlide':{'objectId':'zar_workspace_test','slideLayoutReference':{'predefinedLayout':'BLANK'}}}]
                    for name,text,y,size in [('title','ZAR',70,40),('subtitle','SLIDES OK',150,24)]:
                        oid='zar_test_'+name
                        requests.extend([{'createShape':{'objectId':oid,'shapeType':'TEXT_BOX','elementProperties':{'pageObjectId':'zar_workspace_test','size':{'width':{'magnitude':500,'unit':'PT'},'height':{'magnitude':70,'unit':'PT'}},'transform':{'scaleX':1,'scaleY':1,'translateX':70,'translateY':y,'unit':'PT'}}}},{'insertText':{'objectId':oid,'text':text}},{'updateTextStyle':{'objectId':oid,'textRange':{'type':'ALL'},'style':{'fontSize':{'magnitude':size,'unit':'PT'}},'fields':'fontSize'}}])
                    svc.batchUpdate(presentationId=identifier,body={'requests':requests}).execute()
                if 'SLIDES OK' not in str(svc.get(presentationId=identifier).execute()):raise ValueError('Lectura no confirma contenido Slides.')
                evidence='create/slide/write/read/metadata/ID/URL'
            store({'status':'CONNECTED','evidence':evidence,'last_verified':holdings._now()})
            with holdings.transaction(scope):
                d=holdings.read(scope);cap=identity_center.ensure(d)['capabilities'];cap[target]={'status':'CONNECTED','evidence':evidence,'last_verified':holdings._now(),'document_id':identifier};holdings.write(scope,d)
        except Exception as exc:
            http=getattr(getattr(exc,'resp',None),'status',None)
            ambiguous=not identifier and creation_attempt and (http is None or http>=500)
            store({'status':'AMBIGUOUS_CREATION' if ambiguous else 'ACTION_REQUIRED','error':'Google no confirmó la escritura. Revisar permisos/API y el ID existente antes de repetir.'})
        result[target]=holdings.read(scope)['workspace_tests'][target]
    try:
        svc=w.drive_service().files()
        def folder(name,parent=None):
            query="name = '"+name.replace("'","\\'")+"' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
            query+=(" and '"+parent+"' in parents") if parent else " and 'root' in parents"
            rows=svc.list(q=query,fields='files(id,name)',pageSize=100).execute().get('files',[])
            if len(rows)>1:raise ValueError('Carpetas duplicadas: revisar Drive antes de elegir.')
            return rows[0]['id'] if rows else w.drive_folder(name,parent)['id']
        parent=folder('ZAR');folders={name:folder(name,parent) for name in ('Reports','Documents','Spreadsheets','Presentations','Media','Web Agency','Commerce','Archive')}
        with holdings.transaction(scope):
            d=holdings.read(scope);d['drive_structure']={'root_id':parent,'folders':folders,'verified_at':holdings._now()};holdings.write(scope,d)
        result['DRIVE_STRUCTURE']={'status':'CONNECTED','evidence':'ZAR y ocho subcarpetas verificadas, sin duplicar','id':parent,'url':'https://drive.google.com/drive/folders/'+parent}
    except Exception:result['DRIVE_STRUCTURE']={'status':'ACTION_REQUIRED','error':'Drive no confirmó todas las carpetas; revisar acceso antes de repetir.'}
    return result
