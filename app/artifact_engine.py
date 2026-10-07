"""Designed, reusable artifacts saved through the owner's persistent FileStore."""
import io,re,html
from .file_store import FileStore,DuplicateFileError

def create(title,text,kind='pdf',sources=None,source_task=None,contacts=None,projects=None):
    sources=sources or [];text=str(text or '');title=str(title or 'Informe ZAR')[:180]
    full=text+'\n\nFuentes y referencias\n'+'\n'.join(str(x.get('title','Fuente'))+' — '+str(x.get('url','')) for x in sources)
    output=io.BytesIO()
    if kind=='pdf':
        from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer,PageBreak
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib import colors
        styles=getSampleStyleSheet();styles['Title'].textColor=colors.HexColor('#173854');styles['Heading1'].textColor=colors.HexColor('#173854')
        story=[Paragraph(html.escape(title),styles['Title']),Spacer(1,24),Paragraph('Informe profesional · ZAR',styles['Heading2']),PageBreak()]
        for line in full.splitlines():
            if not line.strip():story.append(Spacer(1,8));continue
            style=styles['Heading1'] if line.startswith('#') else styles['BodyText']
            story.append(Paragraph(html.escape(line.lstrip('# ')),style))
        def footer(canvas,doc):
            canvas.setFont('Helvetica',8);canvas.drawString(40,25,'ZAR · '+title[:70]);canvas.drawRightString(555,25,str(doc.page))
        SimpleDocTemplate(output,title=title,author='ZAR',topMargin=50,bottomMargin=45).build(story,onFirstPage=footer,onLaterPages=footer)
        mime='application/pdf'
    elif kind=='docx':
        from docx import Document
        from docx.shared import Pt
        doc=Document();doc.core_properties.title=title;doc.add_heading(title,0);doc.add_paragraph('Informe profesional · ZAR');doc.add_page_break()
        doc.styles['Normal'].font.size=Pt(11)
        for line in full.splitlines():
            if line.startswith('#'):doc.add_heading(line.lstrip('# '),min(3,len(line)-len(line.lstrip('#'))))
            else:doc.add_paragraph(line)
        doc.sections[0].footer.paragraphs[0].text='ZAR · '+title;doc.save(output);mime='application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    elif kind=='xlsx':
        from openpyxl import Workbook
        from openpyxl.styles import Font,PatternFill
        from openpyxl.chart import BarChart,Reference
        wb=Workbook();ws=wb.active;ws.title='Análisis';rows=[line.split('\t') for line in full.splitlines() if line.strip()]
        for row in rows:ws.append(row)
        ws.freeze_panes='A2';ws.auto_filter.ref=ws.dimensions
        for cell in ws[1]:cell.font=Font(color='FFFFFF',bold=True);cell.fill=PatternFill('solid',fgColor='173854')
        for col in ws.columns:ws.column_dimensions[col[0].column_letter].width=min(65,max(20,max(len(str(c.value or '')) for c in col)+2))
        refs=wb.create_sheet('Fuentes');refs.append(['Título','URL'])
        for source in sources:refs.append([source.get('title'),source.get('url')])
        wb.save(output);mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    elif kind=='pptx':
        from pptx import Presentation
        from pptx.util import Inches,Pt
        from pptx.dml.color import RGBColor
        prs=Presentation();prs.slide_width=Inches(13.33);prs.slide_height=Inches(7.5)
        blocks=re.split(r'\n(?=#)',full);blocks=[title]+blocks
        for block in blocks[:30]:
            slide=prs.slides.add_slide(prs.slide_layouts[6]);bg=slide.background.fill;bg.solid();bg.fore_color.rgb=RGBColor(15,31,49)
            lines=block.splitlines();heading=lines[0].lstrip('# ');content='\n'.join(lines[1:])[:600]
            for y,h,body,size in [(0.6,1.2,heading,30),(2,4.8,content,20)]:
                shape=slide.shapes.add_textbox(Inches(.8),Inches(y),Inches(11.7),Inches(h));shape.text_frame.word_wrap=True;shape.text=body
                for p in shape.text_frame.paragraphs:p.font.size=Pt(size);p.font.color.rgb=RGBColor(240,244,249)
            slide.notes_slide.notes_text_frame.text=block
        prs.save(output);mime='application/vnd.openxmlformats-officedocument.presentationml.presentation'
    elif kind=='md':output.write(full.encode());mime='text/markdown'
    else:raise ValueError('Formato soportado: pdf, docx, xlsx, pptx, md.')
    store=FileStore()
    try:item=store.save(title+'.'+kind,output.getvalue(),mime,type=kind,title=title,creator_agent='ArtifactOrchestrator',source_task=source_task,version=1,associated_contacts=contacts or [],associated_projects=projects or [],retrieval_text=full[:100000])
    except DuplicateFileError as exc:item=exc.item
    return {'artifact_id':item['id'],'type':kind,'title':title,'mime':mime,'size':item['size'],'created_at':item['created_at'],'creator_agent':'ArtifactOrchestrator','source_task':source_task,'storage_path':item.get('stored_name'),'drive_id':item.get('drive_id'),'version':item.get('version',1),'associated_contacts':item.get('associated_contacts',[]),'associated_projects':item.get('associated_projects',[]),'download_url':'/api/files/'+item['id']+'/download'}

def workspace_export(artifact_id,target,confirmed=False):
    if confirmed is not True:raise ValueError('Confirma crear el documento en Google con la identidad de ZAR.')
    from . import google_workspace as workspace
    store=FileStore();item=store.metadata(artifact_id);text=item.get('retrieval_text','');title=item.get('title',item['name'])
    if target not in {'docs','sheets','slides'}:raise ValueError('Google Docs, Sheets o Slides requerido.')
    exports=dict(item.get('workspace_exports') or {})
    previous=exports.get(target)
    if previous:
        if previous.get('status')=='COMPLETE':return previous['result']
        raise ValueError('Existe una exportación pendiente de verificar. Revisa el documento '+str(previous.get('id',''))+' antes de repetir; no se creará un duplicado.')
    def register(result,identifier,status='CREATED'):
        exports[target]={'id':identifier,'status':status,'result':result}
        store.metadata(artifact_id,drive_id=identifier,workspace_exports=exports)
    if target=='docs':
        result=workspace.docs_create(title,title+'\n'+text,on_created=register);identifier=result['documentId']
        register(result,identifier)
        workspace.docs_service().documents().batchUpdate(documentId=identifier,body={'requests':[{'updateParagraphStyle':{'range':{'startIndex':1,'endIndex':1+len((title+'\n').encode('utf-16-le'))//2},'paragraphStyle':{'namedStyleType':'TITLE'},'fields':'namedStyleType'}}]}).execute()
    elif target=='sheets':
        result=workspace.sheets_create(title);identifier=result['spreadsheetId'];rows=[line.split('\t') for line in text.splitlines() if line.strip()]
        register(result,identifier)
        workspace.sheets_write(identifier,'A1',rows)
        workspace.sheets_service().spreadsheets().batchUpdate(spreadsheetId=identifier,body={'requests':[{'updateSheetProperties':{'properties':{'sheetId':0,'gridProperties':{'frozenRowCount':1}},'fields':'gridProperties.frozenRowCount'}},{'repeatCell':{'range':{'sheetId':0,'startRowIndex':0,'endRowIndex':1},'cell':{'userEnteredFormat':{'textFormat':{'bold':True},'backgroundColor':{'red':.1,'green':.22,'blue':.33}}},'fields':'userEnteredFormat'}}]}).execute()
    elif target=='slides':
        result=workspace.slides_create(title);identifier=result['presentationId'];requests=[]
        register(result,identifier)
        for i,block in enumerate(re.split(r'\n(?=#)',text)[:20]):
            page='zar_page_'+str(i);box='zar_box_'+str(i)
            requests.extend([{'createSlide':{'objectId':page,'slideLayoutReference':{'predefinedLayout':'BLANK'}}},{'createShape':{'objectId':box,'shapeType':'TEXT_BOX','elementProperties':{'pageObjectId':page,'size':{'width':{'magnitude':650,'unit':'PT'},'height':{'magnitude':320,'unit':'PT'}},'transform':{'scaleX':1,'scaleY':1,'translateX':35,'translateY':30,'unit':'PT'}}}},{'insertText':{'objectId':box,'text':block[:600]}},{'updateTextStyle':{'objectId':box,'textRange':{'type':'ALL'},'style':{'fontSize':{'magnitude':22,'unit':'PT'}},'fields':'fontSize'}}])
        workspace.slides_service().presentations().batchUpdate(presentationId=identifier,body={'requests':requests}).execute()
    else:raise ValueError('Google Docs, Sheets o Slides requerido.')
    register(result,identifier,'COMPLETE');return result
