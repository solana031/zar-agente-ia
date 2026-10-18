from unittest.mock import Mock,patch
import pytest
from flask import Flask
from app import holdings,notification_center as center,workspace_creator as creator,workspace_native as native,reposnews as rn


@pytest.fixture
def setup(tmp_path,monkeypatch):
    monkeypatch.setenv('ZAR_DATA_DIR',str(tmp_path));rn.write({'owner':'another-user','articles':[]})


def test_notifications_share_human_action_store_and_read_state_survives(setup):
    for _ in range(2):center.emit('owner','DOC_READY','same-file','Doc listo','Contenido verificado','https://docs.google.com/document/d/example/edit',status='COMPLETED')
    rows=holdings.read('owner')['identity_center']['human_actions'];assert len(rows)==1
    view=center.view('owner');assert view['unread']==1
    for field in ('id','type','title','message','created_at','read_at','status','priority','entity_type','entity_id','actions','deep_link'):assert field in view['items'][0]
    center.mark('owner',{'id':rows[0]['id']});assert center.view('owner')['unread']==0
    center.mark('owner',{'id':rows[0]['id'],'unread':True});assert center.view('owner')['unread']==1
    assert center.view('different')['items']==[]


def test_workspace_request_dedup_and_edit_previous_keeps_file_id(setup):
    with patch.object(creator,'start_worker'):
        data={'type':'DOC','title':'Report','request':'Create report','request_id':'fixture-request-123'}
        a=creator.enqueue('owner',data);b=creator.enqueue('owner',data);assert a['id']==b['id']
        creator.update_job('owner',a['id'],state='COMPLETED',file_id='same_google_file_id')
        edited=creator.enqueue('owner',dict(data,request_id='fixture-request-456',edit_previous=True))
    assert edited['file_id']=='same_google_file_id';assert edited['editing'];assert len(creator.jobs('owner'))==2


def test_invalid_content_and_overflow_rejected_before_google_calls():
    for kind,plan in [('DOC',{'sections':[{'heading':'','body':'x'}]}),('SLIDES',{'slides':[{'title':'Title','body':'x'*751}]}),('FORM',{'items':[{'title':'','kind':'TEXT'}]}),('SHEET',{'sheets':[{'name':'RAW_DATA','headers':['one'],'rows':[[1,2]]}]})]:
        with pytest.raises(ValueError):creator.validate_plan(kind,plan)


def test_custom_design_and_slide_geometry_are_native_and_bounded():
    style=creator.design({'theme':'CUSTOM','design':{'background':'#FFFFFF','accent':'#123456','font':'Georgia'}})
    req=native.slide_requests([{'layout':'IMAGE_LEFT','title':'Título','body':'Contenido','image_url':'https://example.org/image.png','source_note':'Official source'}],style,'fixture')
    images=[x['createImage'] for x in req if 'createImage' in x];assert len(images)==1
    for x in req:
        element=x.get('createShape',x.get('createImage',{})).get('elementProperties')
        if not element:continue
        t=element['transform'];size=element['size'];assert t['translateX']+size['width']['magnitude']<=720;assert t['translateY']+size['height']['magnitude']<=405
    assert all(x['updateTextStyle']['style']['fontFamily']=='Georgia' for x in req if 'updateTextStyle' in x)


@pytest.mark.parametrize('kind',['DOC','SLIDES','SHEET','FORM'])
def test_edit_adapters_never_create_another_file(kind):
    style=creator.design({'theme':'ZAR'});plan={'design':style,'sections':[{'heading':'New','body':'Added content'}],'slides':[{'layout':'TITLE_BODY','title':'New','body':'Added'}],
        'sheets':[{'name':'SUMMARY','headers':['Metric','Value'],'rows':[['Count',1]]}],'items':[{'title':'Another question','kind':'TEXT'}]}
    with patch.object(native,'docs_build'),patch.object(native.gw,'slides_service',return_value=Mock()),patch.object(native.gw,'forms_service',return_value=Mock()),\
         patch.object(native.gw,'forms_get',return_value={'items':[{}]}),patch.object(native.gw,'sheets_upgrade_workbook',return_value={'charts':[]}),\
         patch.object(native.gw,'_sheet_metadata',return_value={'sheets':[{'properties':{'title':'SUMMARY','sheetId':1}}]}),\
         patch.object(native.gw,'docs_create') as doc,patch.object(native.gw,'slides_create') as slides,patch.object(native.gw,'sheets_create') as sheet,patch.object(native.gw,'forms_create') as form:
        result=native.build({'type':kind,'title':'Edit'},plan,'same_google_file_id',Mock())
    for call in (doc,slides,sheet,form):call.assert_not_called()
    assert result['file_id']=='same_google_file_id'


def test_formula_errors_fail_validation():
    service=Mock();service.spreadsheets.return_value.get.return_value.execute.return_value={'sheets':[{'data':[{'rowData':[{'values':[{'effectiveValue':{'errorValue':{'type':'REF'}}}]}]}]}]}
    with patch.object(native.gw,'sheets_service',return_value=service),pytest.raises(ValueError,match='SHEET_FORMULA_ERROR'):native.validate_remote('SHEET','fixture',{})


def test_sheet_cover_rows_shift_formulas_ranges_and_normalize_summary():
    plan={'sheets':[{'name':'RAW_DATA','subtitle':'Source','headers':['ID','Value'],'rows':[['a',4]],'summary':['One article']},
        {'name':'SUMMARY','headers':['Count'],'rows':[['=SUM(RAW_DATA!B2:B2)+A2']]}],
        'charts':[{'sheet_title':'RAW_DATA','range_a1':'RAW_DATA!A1:B2','anchor_cell':'E2'}],
        'named_ranges':[{'name':'DATA','range_a1':'RAW_DATA!A2:B2'}],
        'conditional_formats':[{'sheet':'SUMMARY','range_a1':'A2:A9','formula':'=A2>RAW_DATA!B2'}]}
    actual=native.sheet_layout(plan)
    assert actual['sheets'][1]['rows']==[['=SUM(RAW_DATA!B4:B4)+A3']]
    assert actual['sheets'][0]['summary']==[{'label':'One article','value':''}]
    assert actual['charts'][0]['range_a1']=='RAW_DATA!A3:B4'
    assert actual['named_ranges'][0]['range_a1']=='RAW_DATA!A4:B4'
    assert actual['conditional_formats'][0]['formula']=='=A3>INDIRECT("RAW_DATA!B4")'
    assert actual['conditional_formats'][0]['range_a1']=='A3:A10'
    assert plan['sheets'][1]['rows']==[['=SUM(RAW_DATA!B2:B2)+A2']]


def test_spanish_sheet_formulas_use_local_separators_without_changing_strings():
    plan={'sheets':[{'name':'RAW_DATA','subtitle':'Real data','headers':['Status'],'rows':[['READY']],
        'summary':[{'label':'Count','value':'=COUNTIF(A2:A2,"READY, OK")'}]},
        {'name':'SUMMARY','headers':['Count'],'rows':[['=COUNTIF(RAW_DATA!A2:A2,"READY")*1.5']]}]}
    actual=native.sheet_layout(plan,'es_ES')
    assert actual['sheets'][1]['rows']==[['=COUNTIF(RAW_DATA!A4:A4;"READY")*1,5']]
    assert actual['sheets'][0]['summary'][0]['value']=='=COUNTIF(A4:A4;"READY, OK")'


def test_partial_sheet_edit_keeps_offsets_of_untouched_source_tables():
    plan={'_existing_sheet_offsets':{'RAW_DATA':2},'sheets':[{'name':'CALCULATIONS','subtitle':'Counts','headers':['State','Articles'],
        'rows':[['READY_PRIVATE','=COUNTIF(RAW_DATA!C2:C12,"READY_PRIVATE")']]}]}
    actual=native.sheet_layout(plan,'es_ES')
    assert actual['sheets'][0]['rows'][0][1]=='=COUNTIF(RAW_DATA!C4:C14;"READY_PRIVATE")'


def test_sheet_updates_clear_only_the_engines_known_requested_tables():
    previous=[{'file_id':'same_file','plan':{'sheets':[{'name':'SUMMARY','subtitle':'KPIs','headers':['Metric','Value'],'rows':[[1,2]]*5,'summary':['Total']},
        {'name':'UNRELATED','headers':['Keep'],'rows':[['Personal data']]}]}},
        {'file_id':'other_file','plan':{'sheets':[{'name':'SUMMARY','headers':['Other'],'rows':[[1]]*100}]}}]
    plan={'sheets':[{'name':'SUMMARY'}]}
    assert creator.managed_sheet_ranges(previous,'same_file',plan)==["'SUMMARY'!A1:B10"]
    assert creator.managed_sheet_ranges(previous,'unknown_file',plan)==[]


def test_editorial_counts_reset_old_currency_formats_but_money_keeps_its_unit():
    svc=Mock();meta={'sheets':[{'properties':{'title':'SUMMARY','sheetId':1}}]}
    with patch.object(native.gw,'sheets_service',return_value=svc),patch.object(native.gw,'_sheet_metadata',return_value=meta):
        native.gw.sheets_add_professional_table('same_file','SUMMARY','KPIs',['Total artículos','Valor','Horas Totales','Importe'],[[11,11,4,40]])
    requests=svc.spreadsheets.return_value.batchUpdate.call_args.kwargs['body']['requests']
    formats=[r['repeatCell']['cell']['userEnteredFormat']['numberFormat']['type'] for r in requests if r.get('repeatCell',{}).get('fields')=='userEnteredFormat.numberFormat']
    assert formats==['NUMBER','NUMBER','NUMBER','CURRENCY']


def test_notification_endpoints_require_session_and_csrf(setup):
    app=Flask(__name__);app.secret_key='fixture';center.register(app,lambda:'owner');client=app.test_client()
    assert client.get('/api/notifications').status_code==401
    with client.session_transaction() as s:s['zar_auth']=True
    result=client.get('/api/notifications');assert result.status_code==200
    assert client.post('/api/notifications/read',json={'all':True}).status_code==403
    assert client.post('/api/notifications/read',json={'all':True},headers={'X-ZAR-Business-CSRF':result.json['csrf']}).status_code==200


def test_revoked_google_auth_preserves_job_until_reconnection(setup):
    with patch.object(creator,'start_worker'):row=creator.enqueue('owner',{'type':'DOC','title':'Demo','request':'Create a report'})
    with patch('app.cloud_auth.get_credentials',return_value=None),patch.object(native,'build') as build:
        creator.run('owner',row)
    build.assert_not_called();job=creator.jobs('owner')[0]
    assert job['state']=='WAITING_GOOGLE_AUTH';assert job['error']=='GOOGLE_AUTH_REQUIRED';assert not job.get('file_id')


def test_exact_text_replacement_edits_the_same_native_document():
    svc=Mock();svc.documents.return_value.batchUpdate.return_value.execute.return_value={'replies':[{'replaceAllText':{'occurrencesChanged':1}}]}
    with patch.object(native.gw,'docs_service',return_value=svc):native.apply_edits('DOC','same_file',[{'kind':'REPLACE_TEXT','old':'Original','new':'Updated'}])
    call=svc.documents.return_value.batchUpdate.call_args.kwargs
    assert call['documentId']=='same_file';assert call['body']['requests'][0]['replaceAllText']['replaceText']=='Updated'


def test_doc_append_preserves_cover_without_inserting_a_second_one():
    svc=Mock();svc.documents.return_value.get.return_value.execute.return_value={'body':{'content':[{'endIndex':90}]},'headers':{'header':{}}}
    with patch.object(native.gw,'docs_service',return_value=svc):
        native.docs_build('same_file',{'title':'Original','file_id':'same_file'},{'design':creator.design({'theme':'ZAR'}),'sections':[{'heading':'Appendix','body':'Requested addition'}]})
    requests=svc.documents.return_value.batchUpdate.call_args.kwargs['body']['requests']
    assert requests[0]['insertText']['text']=='\nAppendix\nRequested addition\n\n'
    assert not any('insertPageBreak' in r for r in requests)


@pytest.mark.parametrize('content,removed',[('',True),('Existing user content',False)])
def test_only_empty_google_starter_can_be_removed(content,removed):
    svc=Mock();svc.presentations.return_value.get.return_value.execute.return_value={'slides':[{'objectId':'p','pageElements':[{'shape':{'placeholder':{'type':'TITLE'},'text':{'textElements':[{'textRun':{'content':content}}]}}}]}]}
    with patch.object(native.gw,'slides_service',return_value=svc):
        native.build({'type':'SLIDES','title':'Existing','file_id':'same_file'},{'slides':[{'title':'New','body':'Requested'}],'design':creator.design({'theme':'ZAR'}),'remove_empty_starter':True},'same_file',Mock())
    requests=svc.presentations.return_value.batchUpdate.call_args.kwargs['body']['requests']
    assert any('deleteObject' in r for r in requests)==removed


def test_update_existing_question_preserves_item_and_question_ids():
    svc=Mock();question={'itemId':'existing-item','title':'Original','questionItem':{'question':{'questionId':'existing-question','textQuestion':{}}}}
    with patch.object(native.gw,'forms_get',return_value={'items':[question]}),patch.object(native.gw,'forms_service',return_value=svc):
        native.apply_edits('FORM','same_form',[{'kind':'UPDATE_QUESTION','index':0,'title':'Updated','required':True}])
    update=svc.forms.return_value.batchUpdate.call_args.kwargs['body']['requests'][0]['updateItem']
    assert update['item']['itemId']=='existing-item';assert update['item']['questionItem']['question']['questionId']=='existing-question'


def test_new_form_has_the_requested_drive_filename_and_keeps_its_id():
    drive=Mock();remember=Mock()
    with patch.object(native.gw,'forms_create',return_value={'formId':'new_form_id'}),patch.object(native.gw,'drive_service',return_value=drive),patch.object(native.gw,'forms_service',return_value=Mock()),patch.object(native.gw,'forms_get',return_value={'items':[]}):
        result=native.build({'type':'FORM','title':'ZAR DEMO — Feedback'},{'items':[{'title':'Feedback','kind':'TEXT'}]},None,remember)
    remember.assert_called_once_with('new_form_id')
    assert result['file_id']=='new_form_id'
    assert drive.files.return_value.update.call_args.kwargs=={'fileId':'new_form_id','body':{'name':'ZAR DEMO — Feedback'}}
