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


def sheets_write(spreadsheet_id, range_a1, values):
    svc = sheets_service()
    body = {'range': range_a1, 'majorDimension':'ROWS', 'values': values}
    out = svc.spreadsheets().values().update(spreadsheetId=spreadsheet_id, range=range_a1, valueInputOption='USER_ENTERED', body=body).execute()
    return {'ok': True, 'updated': out, 'url': f'https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit'}


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
