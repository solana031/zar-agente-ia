"""Designed, reusable artifacts saved through the owner's persistent FileStore."""
import io,re,html
from .file_store import FileStore,DuplicateFileError

TEMPLATES={'BUSINESS_REPORT','MARKET_RESEARCH','FINANCIAL_REPORT','PROJECT_REPORT','PROPOSAL','TECHNICAL_REPORT','GENERAL_REPORT','RESEARCH','BUSINESS','FINANCIAL','EXECUTIVE'}

def create(title,text,kind='pdf',sources=None,source_task=None,contacts=None,projects=None,template='GENERAL_REPORT',charts=None):
    sources=sources or [];text=str(text or '');title=str(title or 'Informe ZAR')[:180]
    full=text+'\n\nFuentes y referencias\n'+'\n'.join(str(x.get('title','Fuente'))+' — '+str(x.get('url','')) for x in sources)
    if template not in TEMPLATES:raise ValueError('Plantilla de informe no soportada.')
    from .chart_agent import render
    chart_images=[(spec,render(spec)) for spec in (charts or [])]
    headings=[line.lstrip('# ').strip() for line in text.splitlines() if line.startswith('#')]
    output=io.BytesIO()
    if kind=='pdf':
        from .document_renderer import render_pdf
        output.write(render_pdf(title,text,template,sources,chart_images))
        mime='application/pdf'
    elif kind=='docx':
        from docx import Document
        from docx.shared import Pt
        doc=Document();doc.core_properties.title=title;doc.add_heading(title,0);doc.add_paragraph('ZAR · '+template.replace('_',' '));doc.add_page_break();doc.add_heading('Índice',1)
        for heading in headings:doc.add_paragraph(heading,style='List Bullet')
        doc.styles['Normal'].font.size=Pt(11)
        for line in full.splitlines():
            if line.startswith('#'):doc.add_heading(line.lstrip('# '),min(3,len(line)-len(line.lstrip('#'))))
            elif '\t' in line:
                cells=line.split('\t');table=doc.add_table(rows=1,cols=len(cells));table.style='Light Shading Accent 1'
                for cell,value in zip(table.rows[0].cells,cells):cell.text=value
            else:doc.add_paragraph(line)
        doc.sections[0].header.paragraphs[0].text='ZAR · '+template.replace('_',' ')
        from docx.shared import Inches
        for spec,data in chart_images:doc.add_heading(spec.get('title','Gráfico'),2);doc.add_picture(io.BytesIO(data),width=Inches(6))
        doc.sections[0].footer.paragraphs[0].text='ZAR · '+title+' · '
        from docx.oxml import OxmlElement
        from docx.oxml.ns import qn
        page=OxmlElement('w:fldSimple');page.set(qn('w:instr'),'PAGE');doc.sections[0].footer.paragraphs[0]._p.append(page)
        doc.save(output);mime='application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    elif kind=='xlsx':
        from openpyxl import Workbook
        from openpyxl.styles import Font,PatternFill
        from openpyxl.chart import BarChart,Reference
        wb=Workbook();ws=wb.active;ws.title='Análisis';rows=[line.split('\t') for line in full.splitlines() if line.strip()]
        for row in rows:
            converted=[]
            for value in row:
                try:converted.append(float(value) if '.' in value else int(value))
                except (ValueError,TypeError):converted.append(value)
            ws.append(converted)
        ws.freeze_panes='A2';ws.auto_filter.ref=ws.dimensions
        for cell in ws[1]:cell.font=Font(color='FFFFFF',bold=True);cell.fill=PatternFill('solid',fgColor='173854')
        for col in ws.columns:ws.column_dimensions[col[0].column_letter].width=min(65,max(20,max(len(str(c.value or '')) for c in col)+2))
        refs=wb.create_sheet('Fuentes');refs.append(['Título','URL'])
        for source in sources:refs.append([source.get('title'),source.get('url')])
        from openpyxl.formatting.rule import ColorScaleRule
        from openpyxl.worksheet.datavalidation import DataValidation
        from openpyxl.drawing.image import Image as SheetImage
        dashboard=wb.create_sheet('Dashboard');dashboard.append(['ZAR · '+title]);dashboard.append(['Filas de contenido',"=COUNTA('Análisis'!A:A)-1"]);dashboard.append(['Fuentes',len(sources)]);dashboard.column_dimensions['A'].width=45;dashboard.column_dimensions['B'].width=24
        for col in range(1,ws.max_column+1):
            cells=[ws.cell(r,col).value for r in range(2,ws.max_row+1)]
            if cells and all(isinstance(v,(int,float)) for v in cells):
                letter=ws.cell(1,col).column_letter;ws.conditional_formatting.add(letter+'2:'+letter+str(ws.max_row),ColorScaleRule(start_type='min',start_color='F2E4C9',end_type='max',end_color='48776C'))
                chart=BarChart();chart.title=str(ws.cell(1,col).value or 'Datos');chart.add_data(Reference(ws,min_col=col,min_row=1,max_row=ws.max_row),titles_from_data=True);chart.set_categories(Reference(ws,min_col=1,min_row=2,max_row=ws.max_row));dashboard.add_chart(chart,'D2');break
        validation=DataValidation(type='list',formula1='"Pendiente,Revisado,Completado"');dashboard.add_data_validation(validation);dashboard['A5']='Estado de revisión';dashboard['B5']='Pendiente';validation.add(dashboard['B5'])
        for i,(spec,data) in enumerate(chart_images):
            sheet=wb.create_sheet(('Gráfico '+str(i+1))[:31]);image=SheetImage(io.BytesIO(data));image.width=800;image.height=464;sheet.add_image(image,'A1')
        wb.save(output);mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    elif kind=='pptx':
        from pptx import Presentation
        from pptx.util import Inches,Pt
        from pptx.dml.color import RGBColor
        prs=Presentation();prs.slide_width=Inches(13.33);prs.slide_height=Inches(7.5)
        # Keep all content in paced slides; notes retain each complete source block.
        blocks=[]
        for section in re.split(r'\n(?=#)',full):
            lines=section.splitlines();heading=lines[0].lstrip('# ') if lines else title
            chunks=[];chunk=''
            for line in lines[1:]:
                for start in range(0,max(1,len(line)),180):
                    part=line[start:start+180]
                    if len(chunk)+len(part)>480:chunks.append(chunk);chunk=''
                    chunk+=part+'\n'
            if chunk:chunks.append(chunk)
            blocks.extend((heading,content) for content in chunks or [''])
        slides=[(title,'ZAR · '+template.replace('_',' '),'TITLE')]+[(heading,content,'CONTENT') for heading,content in blocks]
        for i,(heading,content,layout) in enumerate(slides):
            slide=prs.slides.add_slide(prs.slide_layouts[6]);bg=slide.background.fill;bg.solid();bg.fore_color.rgb=RGBColor(15,31,49)
            for y,h,body,size in [(0.6,1.1,heading,30),(1.9,4.8,content,20),(6.9,.3,'ZAR · '+str(i+1),11)]:
                shape=slide.shapes.add_textbox(Inches(.8),Inches(y),Inches(11.7),Inches(h));shape.text_frame.word_wrap=True;shape.text=body
                for paragraph in shape.text_frame.paragraphs:paragraph.font.size=Pt(size);paragraph.font.color.rgb=RGBColor(240,244,249)
            slide.notes_slide.notes_text_frame.text=layout+'\n'+heading+'\n'+content
        for spec,data in chart_images:
            slide=prs.slides.add_slide(prs.slide_layouts[6]);slide.shapes.add_picture(io.BytesIO(data),Inches(.8),Inches(.8),width=Inches(11.7));slide.notes_slide.notes_text_frame.text='CHART · '+spec.get('title','Gráfico')
        prs.save(output);mime='application/vnd.openxmlformats-officedocument.presentationml.presentation'
    elif kind=='md':output.write(full.encode());mime='text/markdown'
    else:raise ValueError('Formato soportado: pdf, docx, xlsx, pptx, md.')
    store=FileStore()
    try:item=store.save(title+'.'+kind,output.getvalue(),mime,type=kind,title=title,creator_agent='ArtifactOrchestrator',source_task=source_task,version=1,report_template=template,chart_count=len(chart_images),associated_contacts=contacts or [],associated_projects=projects or [],retrieval_text=full[:100000])
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
