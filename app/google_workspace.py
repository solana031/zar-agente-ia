import os
from googleapiclient.discovery import build
from .cloud_auth import get_credentials


def _creds():
    c = get_credentials(auto_refresh=True)
    if not c:
        raise RuntimeError('Google no está conectado o necesita reautorización.')
    return c


def drive_service():
    return build('drive', 'v3', credentials=_creds(), cache_discovery=False)


def docs_service():
    return build('docs', 'v1', credentials=_creds(), cache_discovery=False)


def sheets_service():
    return build('sheets', 'v4', credentials=_creds(), cache_discovery=False)


def slides_service():
    return build('slides', 'v1', credentials=_creds(), cache_discovery=False)


def forms_service():
    return build('forms', 'v1', credentials=_creds(), cache_discovery=False)


def workspace_status():
    c = _creds()
    return {
        'ok': True,
        'connected': bool(c.valid or c.refresh_token),
        'services': ['Drive', 'Docs', 'Sheets', 'Slides', 'Forms'],
    }


def drive_list(query=None, max_results=20):
    svc = drive_service()
    q = query or "trashed = false"
    resp = svc.files().list(q=q, pageSize=max_results, fields='files(id,name,mimeType,modifiedTime,webViewLink,size,parents)', orderBy='modifiedTime desc').execute()
    return resp.get('files', [])


def drive_search(name, max_results=20):
    escaped = (name or '').replace("'", "\\'")
    q = f"name contains '{escaped}' and trashed = false"
    return drive_list(q, max_results)


def docs_create(title, text=''):
    svc = docs_service()
    doc = svc.documents().create(body={'title': title}).execute()
    doc_id = doc['documentId']
    if text:
        svc.documents().batchUpdate(documentId=doc_id, body={'requests':[{'insertText':{'endOfSegmentLocation':{},'text':text}}]}).execute()
    doc['url'] = f'https://docs.google.com/document/d/{doc_id}/edit'
    return doc


def docs_append(document_id, text):
    svc = docs_service()
    doc = svc.documents().get(documentId=document_id).execute()
    content = doc.get('body', {}).get('content', [])
    end_index = 1
    for el in content:
        end_index = max(end_index, el.get('endIndex', end_index))
    # Insert before terminal newline.
    index = max(1, end_index - 1)
    svc.documents().batchUpdate(documentId=document_id, body={'requests':[{'insertText':{'location':{'index':index},'text':text}}]}).execute()
    return {'ok': True, 'documentId': document_id, 'url': f'https://docs.google.com/document/d/{document_id}/edit'}


def sheets_create(title):
    svc = sheets_service()
    sh = svc.spreadsheets().create(body={'properties':{'title':title}}).execute()
    sid = sh['spreadsheetId']
    sh['url'] = sh.get('spreadsheetUrl') or f'https://docs.google.com/spreadsheets/d/{sid}/edit'
    return sh


def _normalize_spreadsheet_id(spreadsheet_id):
    """Accept a raw Sheets ID or a Google Sheets URL and return the ID."""
    import re
    value = str(spreadsheet_id or '').strip()
    m = re.search(r'/spreadsheets/d/([a-zA-Z0-9_-]+)', value)
    if m:
        return m.group(1)
    return value.strip().rstrip('/').split('?', 1)[0]


def _clean_sheet_range(range_a1, default_sheet_title=None):
    """Normalize common natural-language/URL range artifacts and qualify A1 ranges."""
    import re
    value = str(range_a1 or '').strip()
    value = value.replace('%3A', ':').replace('%3a', ':')
    value = value.rstrip('?,;').strip()
    # If the model supplied a bare A1 range, qualify it with the first sheet.
    if default_sheet_title and '!' not in value and re.match(r'^[A-Za-z]{1,3}\$?\d+(?::[A-Za-z]{1,3}\$?\d+)?$', value):
        safe_title = str(default_sheet_title).replace("'", "''")
        value = f"'{safe_title}'!{value}"
    return value or (f"'{str(default_sheet_title).replace(chr(39), chr(39)*2)}'!A1" if default_sheet_title else 'A1')


def _sheet_metadata(spreadsheet_id):
    svc = sheets_service()
    return svc.spreadsheets().get(
        spreadsheetId=spreadsheet_id,
        fields='spreadsheetId,spreadsheetUrl,sheets(properties(sheetId,title,index))'
    ).execute()


def sheets_write(spreadsheet_id, range_a1, values):
    """Write/update an existing Google Sheet robustly.

    The previous implementation passed the model's range verbatim. This made
    edits fragile when the model returned a Sheets URL, URL-encoded colon, or a
    bare A1 range. Resolve the spreadsheet first, normalize those forms, and
    qualify a bare range with the first worksheet tab.
    """
    sid = _normalize_spreadsheet_id(spreadsheet_id)
    if not sid:
        raise ValueError('Falta el ID de la hoja de cálculo de Google Sheets.')
    meta = _sheet_metadata(sid)
    sheets = meta.get('sheets') or []
    if not sheets:
        raise RuntimeError('La hoja de cálculo no contiene ninguna pestaña editable.')
    first_title = ((sheets[0].get('properties') or {}).get('title')) or 'Hoja 1'
    rng = _clean_sheet_range(range_a1, first_title)

    # Sanitize values so nested/non-JSON scalar objects from the model cannot
    # trigger a Google API 400 during an otherwise valid edit.
    def scalar(v):
        if v is None or isinstance(v, (str, int, float, bool)):
            return v
        return str(v)
    clean_values = [[scalar(cell) for cell in (row if isinstance(row, list) else [row])] for row in (values or [])]
    if not clean_values:
        raise ValueError('No hay valores que escribir en Google Sheets.')

    svc = sheets_service()
    body = {'range': rng, 'majorDimension': 'ROWS', 'values': clean_values}
    try:
        out = svc.spreadsheets().values().update(
            spreadsheetId=sid,
            range=rng,
            valueInputOption='USER_ENTERED',
            body=body
        ).execute()
    except Exception as exc:
        # Retry once with the original caller range when qualification itself
        # is the issue (for example a quoted sheet title already supplied).
        original = str(range_a1 or '').strip().replace('%3A', ':').replace('%3a', ':').rstrip('?,;')
        if original and original != rng:
            out = svc.spreadsheets().values().update(
                spreadsheetId=sid,
                range=original,
                valueInputOption='USER_ENTERED',
                body={**body, 'range': original}
            ).execute()
        else:
            raise RuntimeError(f'Google Sheets rechazó la edición en {rng}: {exc}') from exc
    try:
        _style_written_range(sid, rng, clean_values)
    except Exception:
        # Formatting is best-effort; a successful data write must not be reported as failed.
        pass
    return {'ok': True, 'updated': out, 'spreadsheetId': sid, 'range': rng,
            'url': meta.get('spreadsheetUrl') or f'https://docs.google.com/spreadsheets/d/{sid}/edit'}

def sheets_read(spreadsheet_id, range_a1):
    svc = sheets_service()
    out = svc.spreadsheets().values().get(spreadsheetId=spreadsheet_id, range=range_a1).execute()
    return {'ok': True, 'values': out.get('values', []), 'range': out.get('range'), 'url': f'https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit'}


def slides_create(title):
    svc = slides_service()
    pres = svc.presentations().create(body={'title': title}).execute()
    pid = pres['presentationId']
    pres['url'] = f'https://docs.google.com/presentation/d/{pid}/edit'
    return pres


def slides_insert_text(presentation_id, page_id, text, x=1000000, y=1000000, width=6000000, height=1500000):
    svc = slides_service()
    element_id = 'zarTextBox'
    requests = [
        {'createShape': {'objectId': element_id, 'shapeType': 'TEXT_BOX', 'elementProperties': {'pageObjectId': page_id, 'size': {'width': {'magnitude': width, 'unit':'EMU'}, 'height': {'magnitude': height, 'unit':'EMU'}}, 'transform': {'scaleX': 1, 'scaleY': 1, 'translateX': x, 'translateY': y, 'unit':'EMU'}}}},
        {'insertText': {'objectId': element_id, 'insertionIndex': 0, 'text': text}},
    ]
    svc.presentations().batchUpdate(presentationId=presentation_id, body={'requests':requests}).execute()
    return {'ok': True, 'presentationId': presentation_id, 'url': f'https://docs.google.com/presentation/d/{presentation_id}/edit'}


def forms_create(title, description=''):
    svc = forms_service()

    # Google Forms solo permite establecer el título durante forms.create.
    # La descripción se añade después mediante batchUpdate.
    body = {
        'info': {
            'title': title
        }
    }

    form = svc.forms().create(body=body).execute()
    form_id = form['formId']

    if description:
        update_body = {
            'requests': [{
                'updateFormInfo': {
                    'info': {
                        'description': description
                    },
                    'updateMask': 'description'
                }
            }]
        }
        result = svc.forms().batchUpdate(
            formId=form_id,
            body=update_body
        ).execute()
        form = result.get('form') or form

    form['formId'] = form_id
    form['url'] = f'https://docs.google.com/forms/d/{form_id}/edit'
    return form


def forms_get(form_id):
    svc = forms_service()
    return svc.forms().get(formId=form_id).execute()


def forms_add_question(form_id, question, required=False, paragraph=False):
    svc = forms_service()
    # Google Forms v1: createItem adds a new QuestionItem via batchUpdate.
    item = {
        'title': question,
        'questionItem': {
            'question': {
                'required': bool(required),
                'textQuestion': {'paragraph': bool(paragraph)}
            }
        }
    }
    body = {
        'includeFormInResponse': True,
        'requests': [{
            'createItem': {
                'item': item,
                'location': {'index': 0}
            }
        }]
    }
    result = svc.forms().batchUpdate(formId=form_id, body=body).execute()
    form = result.get('form') or {}
    out = result.get('replies', [{}])[0].get('createItem', {}) if result.get('replies') else {}
    form['questionId'] = out.get('questionId', [])
    form['itemId'] = out.get('itemId')
    form['url'] = f'https://docs.google.com/forms/d/{form_id}/edit'
    return form


# ---------------- Workspace Pro formatting/builders ----------------

def _col_letter(n):
    out = ''
    n = int(n)
    while n > 0:
        n, r = divmod(n - 1, 26)
        out = chr(65 + r) + out
    return out or 'A'


def _parse_a1_start(range_a1):
    import re
    raw = str(range_a1 or 'A1')
    sheet = None
    if '!' in raw:
        sheet, raw = raw.rsplit('!', 1)
        sheet = sheet.strip("'").replace("''", "'")
    m = re.search(r'\$?([A-Za-z]+)\$?(\d+)', raw)
    if not m:
        return sheet, 1, 1
    letters = m.group(1).upper()
    col = 0
    for ch in letters:
        col = col * 26 + (ord(ch) - 64)
    return sheet, int(m.group(2)), col


def _style_written_range(spreadsheet_id, range_a1, values):
    """Apply conservative professional formatting after a successful write."""
    if not values:
        return
    meta = _sheet_metadata(spreadsheet_id)
    props = [x.get('properties') or {} for x in (meta.get('sheets') or [])]
    sheet_name, start_row, start_col = _parse_a1_start(range_a1)
    target = next((x for x in props if x.get('title') == sheet_name), props[0] if props else {})
    sheet_id = target.get('sheetId')
    if sheet_id is None:
        return
    nrows = len(values)
    ncols = max((len(r) for r in values), default=1)
    end_row = start_row - 1 + nrows
    end_col = start_col - 1 + ncols
    grid = {'sheetId': sheet_id, 'startRowIndex': start_row-1, 'endRowIndex': end_row,
            'startColumnIndex': start_col-1, 'endColumnIndex': end_col}
    req = [
        {'repeatCell': {'range': grid, 'cell': {'userEnteredFormat': {
            'verticalAlignment': 'MIDDLE', 'wrapStrategy': 'WRAP',
            'textFormat': {'fontFamily': 'Arial', 'fontSize': 10},
            'borders': {
                'top': {'style':'SOLID','color':{'red':0.86,'green':0.86,'blue':0.86}},
                'bottom': {'style':'SOLID','color':{'red':0.86,'green':0.86,'blue':0.86}},
                'left': {'style':'SOLID','color':{'red':0.90,'green':0.90,'blue':0.90}},
                'right': {'style':'SOLID','color':{'red':0.90,'green':0.90,'blue':0.90}},
            }}}, 'fields':'userEnteredFormat(verticalAlignment,wrapStrategy,textFormat,borders)'}},
        {'autoResizeDimensions': {'dimensions': {'sheetId': sheet_id, 'dimension':'COLUMNS',
            'startIndex': start_col-1, 'endIndex': end_col}}},
    ]
    # First row of every written table becomes a clear header when it looks tabular.
    first = values[0] if values else []
    nonempty = [x for x in first if str(x or '').strip()]
    if ncols > 1 and len(nonempty) >= 2:
        req.append({'repeatCell': {'range': {'sheetId':sheet_id,'startRowIndex':start_row-1,'endRowIndex':start_row,
            'startColumnIndex':start_col-1,'endColumnIndex':end_col}, 'cell': {'userEnteredFormat': {
                'backgroundColor': {'red':0.12,'green':0.17,'blue':0.24},
                'textFormat': {'bold':True,'foregroundColor':{'red':1,'green':1,'blue':1},'fontSize':10},
                'horizontalAlignment':'CENTER'}}, 'fields':'userEnteredFormat(backgroundColor,textFormat,horizontalAlignment)'}})
        if start_row == 1:
            req.append({'updateSheetProperties': {'properties': {'sheetId':sheet_id,'gridProperties':{'frozenRowCount':1}},
                'fields':'gridProperties.frozenRowCount'}})
    # Emphasize rows that are clearly summaries/totals.
    for offset,row in enumerate(values):
        first_cell = str((row or [''])[0] or '').strip().lower()
        if first_cell.startswith(('total','resumen','subtotal','saldo','diferencia')):
            rr = start_row-1+offset
            req.append({'repeatCell': {'range': {'sheetId':sheet_id,'startRowIndex':rr,'endRowIndex':rr+1,
                'startColumnIndex':start_col-1,'endColumnIndex':end_col}, 'cell': {'userEnteredFormat': {
                    'backgroundColor': {'red':0.94,'green':0.95,'blue':0.97},
                    'textFormat': {'bold':True}}}, 'fields':'userEnteredFormat(backgroundColor,textFormat)'}})
    sheets_service().spreadsheets().batchUpdate(spreadsheetId=spreadsheet_id, body={'requests':req}).execute()


def sheets_add_professional_table(spreadsheet_id, sheet_title, table_title, headers, rows, start_cell='A1', subtitle='', summary=None):
    sid = _normalize_spreadsheet_id(spreadsheet_id)
    meta = _sheet_metadata(sid)
    svc = sheets_service()
    props = [x.get('properties') or {} for x in (meta.get('sheets') or [])]
    target = next((x for x in props if x.get('title') == sheet_title), None)
    if target is None:
        add = svc.spreadsheets().batchUpdate(spreadsheetId=sid, body={'requests':[{'addSheet':{'properties':{'title':sheet_title[:100] or 'Datos'}}}]}).execute()
        target = ((add.get('replies') or [{}])[0].get('addSheet') or {}).get('properties') or {}
    sheet_id = target['sheetId']
    _, r0, c0 = _parse_a1_start(start_cell)
    headers = [str(x) for x in (headers or [])]
    clean_rows = [[x if x is None or isinstance(x,(str,int,float,bool)) else str(x) for x in (row or [])] for row in (rows or [])]
    width = max(len(headers), max((len(x) for x in clean_rows), default=0), 1)
    values = [[table_title]]
    if subtitle:
        values.append([subtitle])
    header_offset = len(values)
    values.append(headers)
    values.extend(clean_rows)
    summary = summary or []
    if summary:
        values.append([])
        values.extend([[str(x.get('label','')), x.get('value','')] for x in summary])
    end_col = c0 + width - 1
    range_name = f"'{sheet_title.replace(chr(39), chr(39)*2)}'!{_col_letter(c0)}{r0}:{_col_letter(end_col)}{r0+len(values)-1}"
    svc.spreadsheets().values().update(spreadsheetId=sid, range=range_name, valueInputOption='USER_ENTERED',
        body={'majorDimension':'ROWS','values':values}).execute()
    req = [
        {'mergeCells': {'range': {'sheetId':sheet_id,'startRowIndex':r0-1,'endRowIndex':r0,
            'startColumnIndex':c0-1,'endColumnIndex':end_col}, 'mergeType':'MERGE_ALL'}},
        {'repeatCell': {'range': {'sheetId':sheet_id,'startRowIndex':r0-1,'endRowIndex':r0,
            'startColumnIndex':c0-1,'endColumnIndex':end_col}, 'cell': {'userEnteredFormat': {
                'backgroundColor': {'red':0.08,'green':0.12,'blue':0.18},
                'textFormat': {'bold':True,'fontSize':14,'foregroundColor':{'red':1,'green':1,'blue':1}},
                'horizontalAlignment':'LEFT','verticalAlignment':'MIDDLE'}},
            'fields':'userEnteredFormat(backgroundColor,textFormat,horizontalAlignment,verticalAlignment)'}},
    ]
    if subtitle:
        req += [
            {'mergeCells': {'range': {'sheetId':sheet_id,'startRowIndex':r0,'endRowIndex':r0+1,
                'startColumnIndex':c0-1,'endColumnIndex':end_col}, 'mergeType':'MERGE_ALL'}},
            {'repeatCell': {'range': {'sheetId':sheet_id,'startRowIndex':r0,'endRowIndex':r0+1,
                'startColumnIndex':c0-1,'endColumnIndex':end_col}, 'cell': {'userEnteredFormat': {
                    'backgroundColor': {'red':0.94,'green':0.95,'blue':0.97},
                    'textFormat': {'italic':True,'foregroundColor':{'red':0.28,'green':0.32,'blue':0.38}}}},
                'fields':'userEnteredFormat(backgroundColor,textFormat)'}}]
    hrow = r0 - 1 + header_offset
    header_range = {
        'sheetId': sheet_id,
        'startRowIndex': hrow,
        'endRowIndex': hrow + 1,
        'startColumnIndex': c0 - 1,
        'endColumnIndex': end_col,
    }
    data_range = {
        'sheetId': sheet_id,
        'startRowIndex': hrow + 1,
        'endRowIndex': hrow + 1 + len(clean_rows),
        'startColumnIndex': c0 - 1,
        'endColumnIndex': end_col,
    }
    req.append({
        'repeatCell': {
            'range': header_range,
            'cell': {'userEnteredFormat': {
                'backgroundColor': {'red':0.18,'green':0.27,'blue':0.38},
                'textFormat': {'bold':True,'foregroundColor':{'red':1,'green':1,'blue':1}},
                'horizontalAlignment':'CENTER',
            }},
            'fields':'userEnteredFormat(backgroundColor,textFormat,horizontalAlignment)',
        }
    })
    if clean_rows:
        req.append({
            'repeatCell': {
                'range': data_range,
                'cell': {'userEnteredFormat': {
                    'wrapStrategy':'WRAP',
                    'verticalAlignment':'MIDDLE',
                    'borders': {'bottom': {'style':'SOLID','color':{'red':0.86,'green':0.86,'blue':0.86}}},
                }},
                'fields':'userEnteredFormat(wrapStrategy,verticalAlignment,borders)',
            }
        })
    req.append({'autoResizeDimensions': {'dimensions': {
        'sheetId':sheet_id,'dimension':'COLUMNS','startIndex':c0-1,'endIndex':end_col
    }}})
    svc.spreadsheets().batchUpdate(spreadsheetId=sid, body={'requests':req}).execute()
    return {'ok':True,'spreadsheetId':sid,'sheet':sheet_title,'range':range_name,
            'url':meta.get('spreadsheetUrl') or f'https://docs.google.com/spreadsheets/d/{sid}/edit'}


def sheets_build_workbook(title, sheets):
    svc = sheets_service()
    tabs = sheets or [{'name':'Resumen','table_title':title,'headers':['Dato','Valor'],'rows':[]}]
    names=[]
    for i,tab in enumerate(tabs):
        name=str(tab.get('name') or ('Resumen' if i==0 else f'Hoja {i+1}'))[:100]
        if name in names: name=f'{name[:90]} {i+1}'
        names.append(name)
    body={'properties':{'title':title},'sheets':[{'properties':{'title':n}} for n in names]}
    sh=svc.spreadsheets().create(body=body).execute(); sid=sh['spreadsheetId']
    for name,tab in zip(names,tabs):
        sheets_add_professional_table(sid,name,str(tab.get('table_title') or name),tab.get('headers') or [],tab.get('rows') or [],
            'A1',str(tab.get('subtitle') or ''),tab.get('summary') or [])
    return {'ok':True,'spreadsheetId':sid,'url':sh.get('spreadsheetUrl') or f'https://docs.google.com/spreadsheets/d/{sid}/edit'}


def docs_build_report(title, subtitle, sections):
    svc=docs_service(); doc=svc.documents().create(body={'title':title}).execute(); did=doc['documentId']
    text=title+'\n'+(subtitle+'\n' if subtitle else '')+'\n'
    spans=[]; pos=len(title)+2+(len(subtitle)+1 if subtitle else 0)
    for sec in sections or []:
        heading=str(sec.get('heading') or '').strip(); body=str(sec.get('body') or '').strip()
        if heading:
            spans.append((pos,pos+len(heading),'HEADING_1'))
            text += heading+'\n'; pos += len(heading)+1
        if body:
            text += body+'\n\n'; pos += len(body)+2
    req=[{'insertText':{'endOfSegmentLocation':{},'text':text}},
         {'updateParagraphStyle':{'range':{'startIndex':1,'endIndex':1+len(title)},'paragraphStyle':{'namedStyleType':'TITLE'},'fields':'namedStyleType'}}]
    if subtitle:
        st=2+len(title); req.append({'updateParagraphStyle':{'range':{'startIndex':st,'endIndex':st+len(subtitle)},'paragraphStyle':{'namedStyleType':'SUBTITLE'},'fields':'namedStyleType'}})
    # Recompute headings from final inserted text using deterministic search offsets.
    cursor=1+len(title)+1+(len(subtitle)+1 if subtitle else 0)+1
    for sec in sections or []:
        heading=str(sec.get('heading') or '').strip(); body=str(sec.get('body') or '').strip()
        if heading:
            req.append({'updateParagraphStyle':{'range':{'startIndex':cursor,'endIndex':cursor+len(heading)},'paragraphStyle':{'namedStyleType':'HEADING_1'},'fields':'namedStyleType'}})
            cursor += len(heading)+1
        if body: cursor += len(body)+2
    svc.documents().batchUpdate(documentId=did,body={'requests':req}).execute()
    return {'ok':True,'documentId':did,'url':f'https://docs.google.com/document/d/{did}/edit'}


def slides_build_deck(title, subtitle, slides):
    svc=slides_service(); pres=svc.presentations().create(body={'title':title}).execute(); pid=pres['presentationId']
    existing=[x.get('objectId') for x in (pres.get('slides') or []) if x.get('objectId')]
    req=[]
    for oid in existing: req.append({'deleteObject':{'objectId':oid}})
    deck=[{'title':title,'body':subtitle or ''}]+[{'title':str(x.get('title') or ''),'body':'\n'.join('• '+str(b) for b in (x.get('bullets') or [])) or str(x.get('body') or '')} for x in (slides or [])]
    for i,item in enumerate(deck):
        page=f'zarSlide{i+1}'; title_id=f'zarTitle{i+1}'; body_id=f'zarBody{i+1}'
        req.append({'createSlide':{'objectId':page,'slideLayoutReference':{'predefinedLayout':'BLANK'}}})
        req.append({'createShape':{'objectId':title_id,'shapeType':'TEXT_BOX','elementProperties':{'pageObjectId':page,
            'size':{'width':{'magnitude':8000000,'unit':'EMU'},'height':{'magnitude':900000,'unit':'EMU'}},
            'transform':{'scaleX':1,'scaleY':1,'translateX':650000,'translateY':500000,'unit':'EMU'}}}})
        req.append({'insertText':{'objectId':title_id,'text':item['title']}})
        req.append({'updateTextStyle':{'objectId':title_id,'textRange':{'type':'ALL'},'style':{'bold':True,'fontSize':{'magnitude':26 if i else 30,'unit':'PT'},'foregroundColor':{'opaqueColor':{'rgbColor':{'red':0.12,'green':0.17,'blue':0.24}}}},'fields':'bold,fontSize,foregroundColor'}})
        if item['body']:
            req.append({'createShape':{'objectId':body_id,'shapeType':'TEXT_BOX','elementProperties':{'pageObjectId':page,
                'size':{'width':{'magnitude':7900000,'unit':'EMU'},'height':{'magnitude':4000000,'unit':'EMU'}},
                'transform':{'scaleX':1,'scaleY':1,'translateX':700000,'translateY':1650000,'unit':'EMU'}}}})
            req.append({'insertText':{'objectId':body_id,'text':item['body']}})
            req.append({'updateTextStyle':{'objectId':body_id,'textRange':{'type':'ALL'},'style':{'fontSize':{'magnitude':16 if i else 18,'unit':'PT'},'foregroundColor':{'opaqueColor':{'rgbColor':{'red':0.25,'green':0.28,'blue':0.32}}}},'fields':'fontSize,foregroundColor'}})
    svc.presentations().batchUpdate(presentationId=pid,body={'requests':req}).execute()
    return {'ok':True,'presentationId':pid,'url':f'https://docs.google.com/presentation/d/{pid}/edit'}
