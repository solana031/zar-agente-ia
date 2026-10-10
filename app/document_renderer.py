"""One print-friendly visual language for ZAR PDF artifacts."""
import io, html, re
from datetime import datetime, timezone
from urllib.parse import urlparse

def render_pdf(title, text, template, sources=(), charts=()):
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, KeepTogether
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    styles=getSampleStyleSheet()
    ink=colors.HexColor('#27221c'); gold=colors.HexColor('#88663e'); pale=colors.HexColor('#f5f1ea')
    styles.add(ParagraphStyle(name='ZTitle',fontName='Helvetica-Bold',fontSize=26,leading=31,textColor=ink,spaceAfter=14))
    styles.add(ParagraphStyle(name='ZBody',fontName='Helvetica',fontSize=10,leading=15,textColor=ink,spaceAfter=8,splitLongWords=True))
    styles.add(ParagraphStyle(name='ZSmall',parent=styles['ZBody'],fontSize=8,leading=12,textColor=gold))
    for name,size in [('Heading1',17),('Heading2',13),('Heading3',11)]:
        styles[name].fontName='Helvetica-Bold';styles[name].fontSize=size;styles[name].leading=size+5;styles[name].textColor=gold;styles[name].spaceBefore=16;styles[name].spaceAfter=8
    urls=[]
    def inline(value):
        def link(match):
            url=match.group();urls.append({'title':'Referencia '+str(len(urls)+1),'url':url})
            return 'Referencia web (ver fuentes)'
        return html.escape(re.sub(r'https?://[^\s<>]+',link,value))
    lines=str(text).splitlines();story=[Paragraph('ZAR / '+html.escape(template.replace('_',' ')),styles['ZSmall']),Spacer(1,12),Paragraph(html.escape(title),styles['ZTitle']),Paragraph(datetime.now(timezone.utc).strftime('%d.%m.%Y')+' Â· Documento elaborado por ZAR',styles['ZSmall']),Spacer(1,18)]
    highlights=[x.lstrip('-* ').strip() for x in lines if x.strip() and not x.startswith('#') and '\t' not in x][:3]
    if highlights:
        summary=Table([[Paragraph('CLAVES DEL CONTENIDO',styles['Heading3'])]]+[[Paragraph(inline(x if len(x)<=240 else x[:237]+'…'),styles['ZBody'])] for x in highlights],colWidths=[480])
        summary.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,-1),pale),('LEFTPADDING',(0,0),(-1,-1),14),('RIGHTPADDING',(0,0),(-1,-1),14),('TOPPADDING',(0,0),(-1,-1),8),('BOTTOMPADDING',(0,0),(-1,-1),6)]));story.extend([summary,Spacer(1,14)])
    i=0
    while i<len(lines):
        line=lines[i].strip();i+=1
        if not line:continue
        if '\t' in line:
            rows=[line.split('\t')]
            while i<len(lines) and '\t' in lines[i]:rows.append(lines[i].split('\t'));i+=1
            width=max(map(len,rows));cells=[[Paragraph(inline(c),styles['ZBody']) for c in row]+['']*(width-len(row)) for row in rows]
            table=Table(cells,colWidths=[480/width]*width,repeatRows=1,hAlign='LEFT')
            table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),pale),('LINEBELOW',(0,0),(-1,0),.5,gold),('VALIGN',(0,0),(-1,-1),'TOP'),('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white,colors.HexColor('#faf8f5')]),('TOPPADDING',(0,0),(-1,-1),8),('BOTTOMPADDING',(0,0),(-1,-1),8)]));story.extend([table,Spacer(1,12)]);continue
        if line.startswith('#'):
            level=min(3,len(line)-len(line.lstrip('#')));story.append(Paragraph(inline(line.lstrip('# ')),styles['Heading'+str(level)]))
        else:story.append(Paragraph(inline(line),styles['ZBody']))
    for spec,data in charts:story.extend([Spacer(1,12),Paragraph(html.escape(spec.get('title','GrÃ¡fico')),styles['Heading2']),Image(io.BytesIO(data),width=480,height=278)])
    references=list(sources)+urls
    if references:
        story.append(Paragraph('Fuentes y referencias',styles['Heading1']))
        seen=set()
        for source in references:
            url=str(source.get('url') or '');name=str(source.get('title') or 'Fuente')
            if not url or url in seen:continue
            seen.add(url);label='['+str(len(seen))+'] '+html.escape(name)
            if urlparse(url).scheme in {'http','https'}:label='<link href="'+html.escape(url,quote=True)+'" color="#88663e">'+label+'</link>'
            story.append(Paragraph(label,styles['ZBody']))
    output=io.BytesIO()
    def footer(canvas,doc):
        canvas.setStrokeColor(gold);canvas.setLineWidth(.4);canvas.line(48,38,547,38);canvas.setFont('Helvetica',8);canvas.setFillColor(gold);canvas.drawString(48,25,'ZAR Â· '+template.replace('_',' '));canvas.drawRightString(547,25,'PÃ¡gina '+str(doc.page))
    SimpleDocTemplate(output,title=title,author='ZAR',leftMargin=48,rightMargin=48,topMargin=44,bottomMargin=54).build(story,onFirstPage=footer,onLaterPages=footer)
    return output.getvalue()
