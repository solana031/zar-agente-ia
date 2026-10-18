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


def test_update_existing_question_preserves_item_and_question_ids():
    svc=Mock();question={'itemId':'existing-item','title':'Original','questionItem':{'question':{'questionId':'existing-question','textQuestion':{}}}}
    with patch.object(native.gw,'forms_get',return_value={'items':[question]}),patch.object(native.gw,'forms_service',return_value=svc):
        native.apply_edits('FORM','same_form',[{'kind':'UPDATE_QUESTION','index':0,'title':'Updated','required':True}])
    update=svc.forms.return_value.batchUpdate.call_args.kwargs['body']['requests'][0]['updateItem']
    assert update['item']['itemId']=='existing-item';assert update['item']['questionItem']['question']['questionId']=='existing-question'
