"""Focused persistence/planner/artifacts/mail checks; zero real provider writes."""
import os,sys,uuid,shutil,unittest,subprocess,json,base64
from pathlib import Path
from unittest.mock import Mock,patch
root=Path(__file__).resolve().parents[1];temp=root/('zar-338-'+uuid.uuid4().hex);temp.mkdir()
environment=patch.dict(os.environ,{'ZAR_DATA_DIR':str(temp),'RAILWAY_ENVIRONMENT_ID':''});environment.start()
with patch('threading.Thread.start'):
 from app import main,file_store,holdings,semantic_tasks as tasks,contact_resolver,artifact_engine,identity_center,identity_mail,gmail,business_orchestration,business_connectors,orchestration_map
 from app.user_scope import set_current_user

class Release338(unittest.TestCase):
 def setUp(self):self.scope='fixture_'+uuid.uuid4().hex;set_current_user(self.scope);self.store=file_store.FileStore()
 def test_restart_storage_and_search(self):
  item=self.store.save('report.txt',b'persisted content','text/plain',retrieval_text='ayudas emprendedores',associated_contacts=['Belloso'])
  self.assertEqual(self.store.search('emprendedores')[0]['id'],item['id'])
  code="from app.user_scope import set_current_user;set_current_user("+repr(self.scope)+");from app.file_store import FileStore;assert FileStore().read("+repr(item['id'])+")==b'persisted content';print('PASS child-process persistence')"
  result=subprocess.run([sys.executable,'-c',code],cwd=root,capture_output=True,text=True);self.assertEqual(result.returncode,0,result.stderr)
 def test_ownership(self):
  item=self.store.save('private.txt',b'private fixture','text/plain');set_current_user('another_fixture')
  self.assertEqual(self.store.list(),[])
  with self.assertRaises(ValueError):self.store.read(item['id'])
 def test_recovery_known_previous_scope(self):
  item=self.store.save('original.txt',b'recovery fixture','text/plain');old=self.scope;set_current_user(old+'_google')
  r=self.store.reconcile(previous_scope=old);self.assertEqual(r['recovered'],1);self.assertEqual(self.store.read(item['id']),b'recovery fixture')
  self.assertEqual(self.store.reconcile(previous_scope=old)['recovered'],0)
 def test_orphan_and_missing_metadata(self):
  folder=file_store.files_dir()/'documentos';folder.mkdir();(folder/'orphan.txt').write_text('real orphan')
  self.assertEqual(self.store.reconcile()['recovered'],1);item=self.store.list()[0];self.store.path(item['id']).unlink()
  self.assertEqual(file_store.public_item(item)['availability'],'MISSING_BINARY');self.assertEqual(self.store.reconcile()['missing_binaries'],1)
 def test_ephemeral_storage_rejected(self):
  with patch.dict(os.environ,{'RAILWAY_ENVIRONMENT_ID':'fixture','RAILWAY_VOLUME_MOUNT_PATH':''}):
   with self.assertRaises(ValueError):self.store.save('blocked.txt',b'no ephemeral storage')
 def test_semantic_plan_disambiguates_mail(self):
  p=tasks.plan('Investiga ayudas para jóvenes emprendedores, después haz un informe, envíaselo por email a Belloso.')
  self.assertEqual([s['kind'] for s in p['subtasks']],['RESEARCH','CREATE_REPORT','RESOLVE_CONTACT','DRAFT_EMAIL','ATTACH_ARTIFACT','SEND_EMAIL']);self.assertEqual(p['entities']['recipient'],'Belloso');self.assertNotIn('READ_MAIL',p['required_tools'])
  for text,kind in [('mira mi correo','READ_MAIL'),('manda esto por correo','SEND_EMAIL'),('busca el correo de Belloso','RESOLVE_CONTACT'),('adjunta el informe al correo','ATTACH_ARTIFACT')]:self.assertIn(kind,tasks.plan(text)['required_tools'])
  self.assertIsNone(tasks.plan('Mi correo tiene una dirección nueva'))
 def test_contacts_unique_ambiguous_alias(self):
  row={'resourceName':'people/fixture','name':'Juan Belloso','email':'fixture@example.test','raw':{}}
  with patch('app.google_contacts.search_contacts',return_value=[row]),patch('app.knowledge.search_hybrid',return_value=[]):self.assertEqual(contact_resolver.resolve(self.scope,'Belloso')['status'],'RESOLVED')
  with patch('app.google_contacts.search_contacts',return_value=[row,dict(row,email='another@example.test',resourceName='people/other')]),patch('app.knowledge.search_hybrid',return_value=[]):self.assertEqual(contact_resolver.resolve(self.scope,'Belloso')['status'],'WAITING')
  contact_resolver.remember(self.scope,{'display_name':'Juan Belloso','emails':['fixture@example.test'],'aliases':['Bello']},files=['fixture-file'])
  with patch('app.google_contacts.search_contacts',return_value=[]),patch('app.knowledge.search_hybrid',return_value=[]):self.assertEqual(contact_resolver.resolve(self.scope,'Bello')['contact']['files'],['fixture-file'])
 def test_real_artifacts_persist(self):
  for kind,magic in [('pdf',b'%PDF'),('docx',b'PK'),('xlsx',b'PK'),('pptx',b'PK')]:
   a=artifact_engine.create('Informe fixture '+kind,'# Hallazgos\nDato contrastado\n# Próximos pasos\nRevisar requisitos',kind,[{'title':'Fuente fixture','url':'https://example.test/source'}],source_task='fixture-task')
   self.assertTrue(self.store.read(a['artifact_id']).startswith(magic));self.assertEqual(self.store.metadata(a['artifact_id'])['source_task'],'fixture-task')
   self.assertTrue(self.store.search('contrastado'))
 def test_pipeline_review_and_resume(self):
  task=tasks.create(self.scope,'Investiga ayudas y después haz un informe y mándaselo a Belloso.')
  contact={'contact_id':'people/fixture','display_name':'Belloso','emails':['fixture@example.test'],'phones':[],'aliases':[],'source':'FIXTURE','confidence':1}
  with patch('app.web_search.google_web_search',return_value={'ok':True,'provider':'Google Search grounding','text':'# Hallazgos\nDatos fixture verificados','sources':[{'title':'Fixture','url':'https://example.test'}]}) as research,patch.object(contact_resolver,'resolve',return_value={'status':'RESOLVED','contact':contact}),patch.object(identity_mail,'operate',return_value={'status':'CONFIRMED','message_id':'fixture-message'}) as send:
   first=tasks.run(self.scope,task['id']);self.assertEqual(first['status'],'WAITING');send.assert_not_called();artifact=first['outputs']['CREATE_REPORT']['artifact_id'];self.assertTrue(self.store.path(artifact).is_file())
   last=tasks.run(self.scope,task['id'],confirmed=True);self.assertEqual(last['status'],'DONE');research.assert_called_once();send.assert_called_once();self.assertEqual(send.call_args.args[2]['artifact_ids'],[artifact])
 def test_mail_attachments_and_cc_bcc(self):
  item=self.store.save('fixture.txt',b'attachment bytes','text/plain')
  with patch.object(identity_mail,'require_mail'),patch.object(gmail,'gmail_status',return_value={'email':'fixture-zar@example.test'}),patch.object(gmail,'send_with_attachments',return_value={'id':'fixture-message'}) as send:
   row=identity_mail.operate(self.scope,'send',{'to':'fixture@example.test','cc':'cc@example.test','bcc':'bcc@example.test','subject':'Fixture','body':'Fixture','artifact_ids':[item['id']],'confirmed':True,'transaction_id':'fixture_transaction'})
   self.assertEqual(row['artifact_ids'],[item['id']]);self.assertEqual(base64.b64decode(send.call_args.args[3][0]['data']),b'attachment bytes');self.assertEqual(send.call_args.kwargs['cc'],'cc@example.test')
 def test_workspace_exports(self):
  from app import google_workspace as w
  for target in ['docs','sheets','slides']:
   artifact=artifact_engine.create('Workspace '+target,'# Datos\nFuente fixture',kind='md')
   with patch.object(w,'docs_create',return_value={'documentId':'fixture-doc','url':'https://docs.google.com/document/d/fixture-doc'}),patch.object(w,'sheets_create',return_value={'spreadsheetId':'fixture-sheet','url':'https://docs.google.com/spreadsheets/d/fixture-sheet'}),patch.object(w,'slides_create',return_value={'presentationId':'fixture-slides','url':'https://docs.google.com/presentation/d/fixture-slides'}),patch.object(w,'docs_service',return_value=Mock()),patch.object(w,'sheets_service',return_value=Mock()),patch.object(w,'slides_service',return_value=Mock()),patch.object(w,'sheets_write'):
    r=artifact_engine.workspace_export(artifact['artifact_id'],target,confirmed=True);self.assertTrue(r['url']);self.assertTrue(self.store.metadata(artifact['artifact_id'])['drive_id'])
    self.assertEqual(artifact_engine.workspace_export(artifact['artifact_id'],target,confirmed=True),r)
 def test_workspace_partial_export_does_not_duplicate(self):
  from app import google_workspace as w
  artifact=artifact_engine.create('Partial workspace','# Datos',kind='md');svc=Mock();svc.documents.return_value.batchUpdate.return_value.execute.side_effect=RuntimeError('Formatting unavailable')
  with patch.object(w,'docs_create',return_value={'documentId':'fixture-partial'} ) as create,patch.object(w,'docs_service',return_value=svc):
   with self.assertRaises(RuntimeError):artifact_engine.workspace_export(artifact['artifact_id'],'docs',True)
   with self.assertRaises(ValueError):artifact_engine.workspace_export(artifact['artifact_id'],'docs',True)
   self.assertEqual(create.call_count,1);self.assertEqual(self.store.metadata(artifact['artifact_id'])['workspace_exports']['docs']['status'],'CREATED')
 def test_research_fallback_reads_evidence(self):
  from app.research_agent import investigate
  with patch('app.web_search.google_web_search',return_value={'ok':True,'provider':'DuckDuckGo','text':'Search links only','sources':[{'title':'Fixture','url':'https://example.test'}]}),patch('app.web_search.fetch_webpage',return_value={'ok':True,'text':'Persistent volumes retain their files between application restarts and deployments, according to this fixture.'}) as read:
   result=investigate('Persistent volumes');self.assertIn('Extracto verificado',result['text']);self.assertIn('retain their files',result['text']);self.assertEqual(read.call_count,1)
  with patch('app.web_search.google_web_search',return_value={'ok':True,'sources':[{'title':'Fixture','url':'https://example.test'}]}),patch('app.web_search.fetch_webpage',return_value={'ok':False}):
   with self.assertRaises(ValueError):investigate('Unreadable sources')
 def test_canva_and_identity_policy(self):
  identity_center.register_google(self.scope,'zaragente031@gmail.com');p=identity_center.provider_plan(self.scope,'CANVA');self.assertEqual(p['identity'],'zaragente031@gmail.com');self.assertNotEqual(p['status'],'ACTIVE')
  policy=business_orchestration.ensure({});d=holdings.read(self.scope);self.assertEqual(d['account_identity_policy']['official_github_owner'],'solana031@gmail.com');self.assertEqual(d['account_identity_policy']['official_railway_owner'],'solana031@gmail.com')
  for service in ['GITHUB','RAILWAY']:
   with self.assertRaises(ValueError):identity_center.provider_plan(self.scope,service)
 def test_api_guard_and_chat_no_inbox(self):
  main.app.config.update(TESTING=True,SECRET_KEY='offline');c=main.app.test_client();self.assertEqual(c.post('/api/semantic/tasks',json={'message':'Fixture'}).status_code,403)
  j=c.get('/api/semantic/tasks').json;r=c.post('/api/semantic/tasks',headers={'X-ZAR-Business-CSRF':j['csrf']},json={'message':'busca el correo de Belloso'});self.assertEqual(r.status_code,200);self.assertEqual(r.json['task']['required_tools'],['RESOLVE_CONTACT'])
  with main.app.test_request_context('/api/chat'),patch.object(main,'_launch_semantic_task'),patch.object(main,'_remember_turn'):
   reply=main._process_chat_message('Investiga ayudas, haz un informe y envíaselo a Belloso.');self.assertIn('Abrir tarea',reply);self.assertNotIn('inbox',reply.lower())
try:result=unittest.TextTestRunner(verbosity=1).run(unittest.defaultTestLoader.loadTestsFromTestCase(Release338))
finally:
 environment.stop();assert temp.resolve().is_relative_to(root);shutil.rmtree(temp)
if not result.wasSuccessful():raise SystemExit(1)
