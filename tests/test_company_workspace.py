import uuid
import shutil
import unittest
from pathlib import Path
from unittest.mock import patch
from flask import Flask
from app import company_workspace as cw
from app.user_scope import set_current_user, reset_current_user

class CompanyWorkspaceTest(unittest.TestCase):
    def setUp(self):
        self.root=Path(__file__).resolve().parent / ('cw-test-'+uuid.uuid4().hex);self.root.mkdir()
        self.token=set_current_user('alice');self.app=Flask(__name__);self.app.secret_key='test';self.app.register_blueprint(cw.blueprint)
        self.client=self.app.test_client()
        self.items=[{'id':'invoice','owner_id':'alice','name':'factura.txt','analysis':{'summary':'Factura de proveedor','full_text':'Documento fuente'},'updated_at':'1'}]
        self.patches=[patch.object(cw.file_store,'files_dir',side_effect=lambda:self.mkdir()),patch.object(cw.file_store,'persistent_storage'),patch.object(cw.file_store,'list_files',side_effect=lambda:self.items)]
        for p in self.patches:p.start()
    def mkdir(self):
        from app.user_scope import safe_slug
        p=self.root/safe_slug()/'files';p.mkdir(parents=True,exist_ok=True);return p
    def tearDown(self):
        for p in reversed(self.patches):p.stop()
        reset_current_user(self.token);shutil.rmtree(self.root)
    def get(self):return self.client.get('/api/company-workspace').get_json()
    def post(self,body,state):return self.client.post('/api/company-workspace',json={**body,'revision':state['workspace']['revision']},headers={'X-ZAR-Business-CSRF':state['csrf']})
    def test_refresh_rebuild_and_later_upload_preserve_annotations(self):
        s=self.get();self.assertEqual(s['workspace']['sources'][0]['kind'],'factura')
        r=self.post({'action':'source','id':'invoice','kind':'contabilidad','included':False,'note':'Revisada'},s);self.assertEqual(r.status_code,200)
        s=self.get();self.post({'action':'profile','profile':{'name':'Mi empresa','notes':'Contexto'}},s)
        self.items.append({'id':'closure','owner_id':'alice','name':'cierre.pdf'})
        s=self.get();self.assertEqual(len(s['workspace']['sources']),2)
        result=self.post({'action':'rebuild'},s).get_json()['workspace']
        self.assertEqual(result['profile']['name'],'Mi empresa')
        old=next(x for x in result['sources'] if x['id']=='invoice');self.assertFalse(old['included']);self.assertEqual(old['note'],'Revisada');self.assertEqual(old['kind'],'contabilidad')
        self.items=[];s=self.get();self.assertFalse(s['workspace']['sources'][0]['available'])
    def test_csrf_conflict_user_isolation_and_corrupt_file(self):
        s=self.get();self.assertEqual(self.client.post('/api/company-workspace',json={'action':'rebuild'}).status_code,403)
        self.post({'action':'profile','profile':{'name':'A'}},s)
        self.assertEqual(self.post({'action':'rebuild'},s).status_code,409)
        token=set_current_user('bob')
        try:self.assertEqual(self.get()['workspace']['sources'],[]);self.assertEqual(self.get()['workspace']['profile'],{})
        finally:reset_current_user(token)
        cw.path().write_text('{bad',encoding='utf8')
        self.assertEqual(self.client.get('/api/company-workspace').status_code,400)
        self.assertEqual(cw.path().read_text(),'{bad')
    def test_local_text_fallback_without_model_or_analysis_mutation(self):
        doc=self.root/'empresa.txt';doc.write_text('Empresa existente\nActividad: comercio local',encoding='utf8')
        self.items=[{'id':'base','owner_id':'alice','name':'empresa.txt','analysis':{}}]
        with patch.object(cw.file_store.FileStore,'path',return_value=doc):
            row=self.get()['workspace']['sources'][0]
        self.assertEqual(row['status'],'disponible')
        self.assertIn('comercio local',row['summary'])
        self.assertEqual(self.items[0]['analysis'],{})

if __name__=='__main__':unittest.main()
