import unittest
from unittest.mock import Mock,patch
from app.workspace_artifacts import form_requests,build_form


class NativeWorkspaceArtifacts(unittest.TestCase):
    def test_blank_slides_creation_preserves_existing_contract(self):
        from app import google_workspace as gw
        svc=Mock();svc.presentations.return_value.create.return_value.execute.return_value={'presentationId':'fixture'}
        with patch.object(gw,'slides_service',return_value=svc):
            self.assertEqual(gw.slides_create('Vacía')['presentationId'],'fixture')

    def test_deck_theme_is_applied_before_native_batch(self):
        from app import google_workspace as gw
        svc=Mock();svc.presentations.return_value.create.return_value.execute.return_value={'presentationId':'fixture'}
        with patch.object(gw,'slides_service',return_value=svc),patch('app.workspace_artifacts.record',side_effect=lambda r,*a:r):
            result=gw.slides_build_deck('Portada','Subtítulo',[{'title':'Contenido','body':'Texto'}],theme='EDITORIAL')
        self.assertEqual(result['slides'],2)
        requests=svc.presentations.return_value.batchUpdate.call_args.kwargs['body']['requests']
        styles=[x['updateTextStyle']['style'] for x in requests if 'updateTextStyle' in x]
        self.assertTrue(styles);self.assertTrue(all(x['fontFamily']=='Georgia' for x in styles))

    def test_docs_theme_and_spacing_are_native_requests(self):
        from app import google_workspace as gw
        svc=Mock();svc.documents.return_value.create.return_value.execute.return_value={'documentId':'fixture'}
        with patch.object(gw,'docs_service',return_value=svc),patch('app.workspace_artifacts.record',side_effect=lambda r,*a:r):
            result=gw.docs_build_report('Título','Subtítulo',[{'heading':'Sección','body':'Contenido'}],theme='EDITORIAL')
        self.assertEqual(result['documentId'],'fixture')
        requests=svc.documents.return_value.batchUpdate.call_args.kwargs['body']['requests']
        self.assertTrue(any(r.get('updateTextStyle',{}).get('textStyle',{}).get('weightedFontFamily',{}).get('fontFamily')=='Georgia' for r in requests))

    def test_form_types_and_order(self):
        rows=[{'title':'Inicio','kind':'HEADING'}, {'title':'Nombre','kind':'TEXT','required':True},
              {'title':'Opciones','kind':'CHECKBOX','options':['Uno','Dos']}, {'title':'Opinión','kind':'SCALE','low':0,'high':10},
              {'title':'Fecha','kind':'DATE'}, {'title':'Siguiente','kind':'SECTION'}]
        requests=form_requests(rows)
        self.assertEqual([r['createItem']['location']['index'] for r in requests],list(range(6)))
        self.assertTrue(requests[1]['createItem']['item']['questionItem']['question']['required'])
        self.assertIn('pageBreakItem',requests[-1]['createItem']['item'])

    def test_invalid_form_never_creates_external_document(self):
        with patch('app.google_workspace.forms_create') as create:
            for items in ([],[{'title':'','kind':'TEXT'}],[{'title':'Q','kind':'RADIO','options':[]}],[{'title':'Q','kind':'SCALE','high':99}]):
                with self.assertRaises(ValueError):build_form('Test','',items)
        create.assert_not_called()

    def test_native_form_is_validated_without_publish_or_share(self):
        service=Mock();result={'formId':'fixture','url':'https://docs.google.com/forms/d/fixture/edit'}
        with patch('app.google_workspace.forms_create',return_value=result),patch('app.google_workspace.forms_service',return_value=service),patch('app.google_workspace.forms_get',return_value={'items':[{}]}),patch('app.workspace_artifacts.record',side_effect=lambda r,*a:r):
            built=build_form('Encuesta','Descripción',[{'title':'Pregunta','kind':'TEXT'}])
        self.assertEqual(built['validation'],'API_ITEM_COUNT_VERIFIED')
        body=service.forms.return_value.batchUpdate.call_args.kwargs['body']
        self.assertEqual(list(body['requests'][0]),['createItem'])
        self.assertNotIn('publishSettings',str(body))

if __name__=='__main__':unittest.main()
