"""Dispatch to existing Workspace adapters under the selected ZAR OAuth identity."""
from . import cloud_auth,holdings,google_workspace as workspace,google_calendar,google_contacts,google_tasks
from .identity_center import ensure

def operate(scope,action,data):
    d=holdings.read(scope);expected=ensure(d)['google'].get('email');creds=cloud_auth.get_credentials(user_id=scope)
    if not expected or not creds or cloud_auth.get_account_email(creds)!=expected:raise ValueError('Conecta y verifica OAuth de la identidad principal de ZAR.')
    reads={'drive_list':lambda:workspace.drive_list(data.get('query'),min(50,int(data.get('limit',20)))),
           'drive_download':lambda:workspace.drive_download(data['id']),
           'calendar_read':lambda:google_calendar.upcoming_events(),
           'contacts_read':lambda:google_contacts.list_connections(),
           'tasks_read':lambda:google_tasks.list_tasks()}
    writes={'drive_folder':lambda:workspace.drive_folder(data['name'],data.get('parent')),
            'drive_upload':lambda:workspace.drive_upload(data['name'],data['data'],data.get('mime','application/octet-stream'),data.get('parent')),
            'drive_move':lambda:workspace.drive_move(data['id'],data['parent']),
            'drive_share':lambda:workspace.drive_share(data['id'],data['email'],data.get('role','reader')),
            'docs_create':lambda:workspace.docs_create(data['name'],data.get('text','')),
            'docs_edit':lambda:workspace.docs_append(data['id'],data['text']),
            'sheets_create':lambda:workspace.sheets_create(data['name']),
            'sheets_edit':lambda:workspace.sheets_write(data['id'],data['range'],data['values']),
            'slides_create':lambda:workspace.slides_create(data['name']),
            'calendar_create':lambda:google_calendar.create_event(data['name'],data['start'],data['end'],data.get('text','')),
            'contacts_create':lambda:google_contacts.create_contact(data['name'],data.get('email',''),data.get('phone',''),data.get('company',''))}
    if action in reads:return reads[action]()
    if action not in writes:raise ValueError('Acción Workspace no soportada.')
    if d.get('global_stop') or data.get('confirmed') is not True:raise ValueError('Confirma el cambio revisado; STOP global bloquea escrituras.')
    return writes[action]()
