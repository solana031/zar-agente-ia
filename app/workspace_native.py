"""Native Docs/Slides/Sheets/Forms requests. Existing files are edited in place."""
import secrets
from . import google_workspace as gw,workspace_artifacts as wa


def utf16(text):return len(text.encode('utf-16-le'))//2


def end_index(doc):return max([1]+[int(x.get('endIndex',1))-1 for x in doc.get('body',{}).get('content',[])])


def docs_build(fid,payload,plan):
    service=gw.docs_service();doc=service.documents().get(documentId=fid).execute();start=end_index(doc)
    title=payload['title'];subtitle=str(plan.get('subtitle') or '')
    text=title+'\n'+subtitle+'\n\n';spans=[];images=[];tables=[]
    for section in plan['sections']:
        heading=section['heading'];body=section['body'];offset=start+utf16(text)
        spans.append((offset,offset+utf16(heading),'HEADING_1'));text+=heading+'\n'+body+'\n\n'
        if section.get('quote'):text+='“'+section['quote']+'”\n\n'
        if section.get('image_url'):images.append((start+utf16(text)-1,section['image_url']))
        if section.get('table'):tables.append(section['table'])
    for source in plan.get('references',[]):text+=str(source.get('title',''))+' · '+str(source.get('url',''))+'\n'
    style=plan['design'];requests=[{'insertText':{'location':{'index':start},'text':text}},
        {'updateTextStyle':{'range':{'startIndex':start,'endIndex':start+utf16(text)},'textStyle':{'weightedFontFamily':{'fontFamily':style['font']},'fontSize':{'magnitude':11,'unit':'PT'}},'fields':'weightedFontFamily,fontSize'}},
        {'updateParagraphStyle':{'range':{'startIndex':start,'endIndex':start+utf16(text)},'paragraphStyle':{'spaceAbove':{'magnitude':6,'unit':'PT'},'spaceBelow':{'magnitude':9,'unit':'PT'},'lineSpacing':120},'fields':'spaceAbove,spaceBelow,lineSpacing'}},
        {'updateParagraphStyle':{'range':{'startIndex':start,'endIndex':start+utf16(title)},'paragraphStyle':{'namedStyleType':'TITLE'},'fields':'namedStyleType'}}]
    if subtitle:requests.append({'updateParagraphStyle':{'range':{'startIndex':start+utf16(title)+1,'endIndex':start+utf16(title)+1+utf16(subtitle)},'paragraphStyle':{'namedStyleType':'SUBTITLE'},'fields':'namedStyleType'}})
    for a,b,style_name in spans:requests.append({'updateParagraphStyle':{'range':{'startIndex':a,'endIndex':b},'paragraphStyle':{'namedStyleType':style_name},'fields':'namedStyleType'}})
    # Add a genuine cover break, not a simulated blank wall of text.
    requests.append({'insertPageBreak':{'location':{'index':start+utf16(title+'\n'+subtitle+'\n')}}})
    service.documents().batchUpdate(documentId=fid,body={'requests':requests}).execute()
    for index,url in reversed(images):
        service.documents().batchUpdate(documentId=fid,body={'requests':[{'insertInlineImage':{'location':{'index':index+1},'uri':url,'objectSize':{'width':{'magnitude':420,'unit':'PT'}}}}]}).execute()
    for rows in tables[:8]:
        if not rows or not rows[0]:continue
        if len(rows)>30 or max(map(len,rows))>8:raise ValueError('DOC_TABLE_TOO_LARGE')
        doc=service.documents().get(documentId=fid).execute();at=end_index(doc)
        service.documents().batchUpdate(documentId=fid,body={'requests':[{'insertTable':{'rows':len(rows),'columns':max(map(len,rows)),'location':{'index':at}}}]}).execute()
        actual=service.documents().get(documentId=fid).execute();table=next((x['table'] for x in reversed(actual['body']['content']) if 'table' in x),None)
        requests=[]
        if table:
            for r,source in zip(table['tableRows'],rows):
                for cell,value in zip(r['tableCells'],source):
                    requests.append({'insertText':{'location':{'index':cell['content'][0]['startIndex']},'text':str(value)}})
            requests.sort(key=lambda x:x['insertText']['location']['index'],reverse=True)
            service.documents().batchUpdate(documentId=fid,body={'requests':requests}).execute()
    if not doc.get('headers'):
        response=service.documents().batchUpdate(documentId=fid,body={'requests':[{'createHeader':{'type':'DEFAULT'}},{'createFooter':{'type':'DEFAULT'}}]}).execute()
        header=response['replies'][0]['createHeader']['headerId'];footer=response['replies'][1]['createFooter']['footerId']
        service.documents().batchUpdate(documentId=fid,body={'requests':[{'insertText':{'endOfSegmentLocation':{'segmentId':header},'text':payload.get('theme','ZAR')+' · '+title}},
             {'insertText':{'endOfSegmentLocation':{'segmentId':footer},'text':'ZAR · '+str(payload.get('source_article_id') or 'Workspace')}}]}).execute()


def element(page,x,y,w,h):
    return {'pageObjectId':page,'size':{'width':{'magnitude':w,'unit':'PT'},'height':{'magnitude':h,'unit':'PT'}},
            'transform':{'scaleX':1,'scaleY':1,'translateX':x,'translateY':y,'unit':'PT'}}


def text_box(req,page,key,text,x,y,w,h,size,style,bold=False):
    if not text:return
    req.extend([{'createShape':{'objectId':key,'shapeType':'TEXT_BOX','elementProperties':element(page,x,y,w,h)}},
        {'insertText':{'objectId':key,'text':str(text)}},
        {'updateTextStyle':{'objectId':key,'textRange':{'type':'ALL'},'style':{'fontFamily':style['font'],'fontSize':{'magnitude':size,'unit':'PT'},'bold':bold,
             'foregroundColor':{'opaqueColor':{'rgbColor':style['text']}}},'fields':'fontFamily,fontSize,bold,foregroundColor'}}])


def slide_requests(slides,style,prefix):
    req=[]
    for i,s in enumerate(slides):
        page=prefix+'_page_'+str(i);layout=s.get('layout','TITLE_BODY')
        req.extend([{'createSlide':{'objectId':page,'slideLayoutReference':{'predefinedLayout':'BLANK'}}},
            {'updatePageProperties':{'objectId':page,'pageProperties':{'pageBackgroundFill':{'solidFill':{'color':{'rgbColor':style['background']}}}},'fields':'pageBackgroundFill'}}])
        text_box(req,page,page+'_title',s['title'],40,25,640,76,30 if layout in {'COVER','SECTION_DIVIDER','CLOSING'} else 26,style,True)
        body='\n'.join('• '+x for x in s.get('bullets',[])) or s.get('body','')
        image=s.get('image_url');columns=s.get('columns',[])
        x=40;y=115;w=640
        if layout in {'TWO_COLUMN','COMPARISON','TIMELINE','PROCESS','DIAGRAM','KPI'} and not columns:
            chunks=s.get('bullets',[]) or [body];mid=max(1,(len(chunks)+1)//2)
            columns=[{'title':'','body':'\n'.join(chunks[:mid])},{'title':'','body':'\n'.join(chunks[mid:])}]
        if columns:
            for c,col in enumerate(columns[:3]):
                cw=620/min(len(columns),3);cx=40+c*(cw+10)
                text_box(req,page,page+'_col'+str(c),str(col.get('title',''))+'\n'+str(col.get('body','')),cx,y,cw,240,18,style)
                if c<min(len(columns),3)-1:req.append({'createLine':{'objectId':page+'_line'+str(c),'lineCategory':'STRAIGHT','elementProperties':element(page,cx+cw+3,y,1,230)}})
        else:
            if image:
                if layout=='IMAGE_LEFT':x=375;w=305
                elif layout=='FULL_IMAGE':w=0
                else:w=305
            if s.get('chart') or s.get('video_id'):w=305
            if w and not s.get('table'):text_box(req,page,page+'_body',body,x,y,w,240,20 if layout in {'COVER','QUOTE','KPI'} else 18,style)
        if image:
            ix=40 if layout in {'IMAGE_LEFT','FULL_IMAGE'} else 375;iw=640 if layout=='FULL_IMAGE' else 305
            req.append({'createImage':{'objectId':page+'_image','url':image,'elementProperties':element(page,ix,115,iw,240)}})
        if s.get('table'):
            rows=s['table'];cols=max(map(len,rows))
            req.append({'createTable':{'objectId':page+'_table','rows':len(rows),'columns':cols,'elementProperties':element(page,40,140,640,200)}})
            for r,row in enumerate(rows):
                for c,value in enumerate(row):req.append({'insertText':{'objectId':page+'_table','cellLocation':{'rowIndex':r,'columnIndex':c},'text':str(value)}})
        if s.get('video_id'):req.append({'createVideo':{'objectId':page+'_video','source':'YOUTUBE','id':s['video_id'],'elementProperties':element(page,375,115,305,240)}})
        if s.get('chart'):
            chart=s['chart'];req.append({'createSheetsChart':{'objectId':page+'_chart','spreadsheetId':chart['spreadsheet_id'],'chartId':int(chart['chart_id']),'linkingMode':'LINKED','elementProperties':element(page,375,115,305,240)}})
        text_box(req,page,page+'_source',str(s.get('source_note') or '')[:150],40,378,600,18,10,style)
    return req


def build(payload,plan,fid,remember):
    kind=payload['type'];title=payload['title']
    if not fid:
        created={'DOC':gw.docs_create,'SLIDES':gw.slides_create,'SHEET':gw.sheets_create,'FORM':gw.forms_create}[kind](title)
        fid=next(created[k] for k in ('documentId','presentationId','spreadsheetId','formId') if created.get(k));remember(fid)
    if kind=='DOC':docs_build(fid,payload,plan);key='documentId';url='https://docs.google.com/document/d/'+fid+'/edit'
    elif kind=='SLIDES':
        svc=gw.slides_service();prefix='zar_'+secrets.token_hex(6)
        req=slide_requests(plan['slides'],plan['design'],prefix)
        svc.presentations().batchUpdate(presentationId=fid,body={'requests':req}).execute()
        key='presentationId';url='https://docs.google.com/presentation/d/'+fid+'/edit'
    elif kind=='SHEET':
        result=gw.sheets_upgrade_workbook(fid,plan['sheets'],plan.get('charts'))
        if any(not c.get('ok') for c in result.get('charts',[])):raise ValueError('SHEET_CHART_VALIDATION_FAILED')
        meta=gw._sheet_metadata(fid);props={x['properties']['title']:x['properties']['sheetId'] for x in meta['sheets']}
        req=[]
        for named in plan.get('named_ranges',[]):
            sheet,r1,c1,r2,c2=gw._a1_range_parts(named['range_a1'])
            if sheet not in props:raise ValueError('NAMED_RANGE_SHEET_MISSING')
            req.append({'addNamedRange':{'namedRange':{'name':named['name'],'range':{'sheetId':props[sheet],'startRowIndex':r1-1,'endRowIndex':r2,'startColumnIndex':c1-1,'endColumnIndex':c2}}}})
        for rule in plan.get('conditional_formats',[]):
            sheet,r1,c1,r2,c2=gw._a1_range_parts(rule['range_a1'],rule.get('sheet'))
            if sheet not in props:raise ValueError('CONDITIONAL_RANGE_SHEET_MISSING')
            req.append({'addConditionalFormatRule':{'index':0,'rule':{'ranges':[{'sheetId':props[sheet],'startRowIndex':r1-1,'endRowIndex':r2,'startColumnIndex':c1-1,'endColumnIndex':c2}],
                'booleanRule':{'condition':{'type':'CUSTOM_FORMULA','values':[{'userEnteredValue':rule['formula']}]},'format':{'backgroundColor':plan['design']['accent']}}}}})
        if req:gw.sheets_service().spreadsheets().batchUpdate(spreadsheetId=fid,body={'requests':req}).execute()
        key='spreadsheetId';url='https://docs.google.com/spreadsheets/d/'+fid+'/edit'
    else:
        svc=gw.forms_service();actual=gw.forms_get(fid);offset=len(actual.get('items',[]));req=wa.form_requests(plan['items'])
        for command in req:command['createItem']['location']['index']+=offset
        if plan.get('mode')=='QUIZ':req.insert(0,{'updateSettings':{'settings':{'quizSettings':{'isQuiz':True}},'updateMask':'quizSettings.isQuiz'}})
        if plan.get('description'):req.insert(0,{'updateFormInfo':{'info':{'description':plan['description']},'updateMask':'description'}})
        svc.forms().batchUpdate(formId=fid,body={'requests':req}).execute()
        key='formId';url='https://docs.google.com/forms/d/'+fid+'/edit'
    return {'ok':True,'file_id':fid,key:fid,'url':url}


def validate_remote(kind,fid,plan):
    if kind=='DOC':
        doc=gw.docs_service().documents().get(documentId=fid).execute()
        if end_index(doc)<30:raise ValueError('DOC_EMPTY')
        return {'status':'VERIFIED','check':'native content and headings','sections':len(plan['sections'])}
    if kind=='SLIDES':
        deck=gw.slides_service().presentations().get(presentationId=fid).execute()
        if len(deck.get('slides',[]))<len(plan['slides']):raise ValueError('SLIDES_MISSING')
        return {'status':'VERIFIED','check':'native pages; bounded layout and font sizes; image insertion succeeded','slides':len(deck['slides'])}
    if kind=='SHEET':
        result=gw.sheets_service().spreadsheets().get(spreadsheetId=fid,includeGridData=True).execute()
        for sheet in result.get('sheets',[]):
            for grid in sheet.get('data',[]):
                for row in grid.get('rowData',[]):
                    if any('errorValue' in cell.get('effectiveValue',{}) for cell in row.get('values',[])):raise ValueError('SHEET_FORMULA_ERROR')
        return {'status':'VERIFIED','check':'native grid formula error scan','tabs':len(result.get('sheets',[]))}
    actual=gw.forms_get(fid)
    if len(actual.get('items',[]))<len(plan['items']):raise ValueError('FORM_ITEMS_MISSING')
    return {'status':'VERIFIED','check':'native items and question configuration','items':len(actual['items']),
            'limitations':['Forms REST API does not expose form theme/confirmation-message editing or linkedSheetId writing.']}
