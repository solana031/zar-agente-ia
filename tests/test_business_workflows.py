"""Focused offline tests; no provider generations, payments or publications."""
import io
import json
import os
import shutil
import unittest
import uuid
import zipfile
from pathlib import Path
from unittest.mock import patch
from app import holdings, jev_decision as jev, site_projects as sites, adsense_adapter as ads
from app import media_company as media, media_projects as projects, business_orchestration as control
from app.business_connectors import inventory, verification


class Response:
    ok=True
    status_code=200
    def __init__(self,data):self.data=data
    def json(self):return self.data


class GoogleSession:
    def __init__(self):self.calls=[]
    def get(self,url,**kw):
        self.calls.append((url,kw)); assert kw['allow_redirects'] is False
        if url.endswith('/accounts'):return Response({'accounts':[{'name':'accounts/pub-test'}]})
        if url.endswith('/reports:generate'):
            return Response({'headers':[{'name':'PAGE_VIEWS'},{'name':'ESTIMATED_EARNINGS'},{'name':'PAGE_VIEWS_CTR'}],
                'totals':{'cells':[{'value':'100'},{'value':'12.50'},{'value':''}]},
                'averages':{'cells':[{'value':''},{'value':''},{'value':'.02'}]},
                'startDate':{'year':2026,'month':9,'day':1},'endDate':{'year':2026,'month':9,'day':30}})
        if url.endswith('/payments'):return Response({'payments':[
            {'name':'accounts/pub-test/payments/unpaid','amount':'€10.00'},
            {'name':'accounts/pub-test/payments/2026-09-21','amount':'€80.00','date':{'year':2026,'month':9,'day':21}}]})
        if url.endswith('/sites'):return Response({'sites':[{'domain':'example.com','state':'READY'}]})
        raise AssertionError(url)


class FakeDrama:
    def __init__(self):self.briefs=[]
    def advance(self,cp,brief,persist,narrator=None):
        self.briefs.append(brief)
        cp.update(stage='done',status='done',progress=100,project_id='real-provider-project',tasks=[])
        persist(cp);return cp
    def download_final(self,cp,path):path.write_bytes(b'\x00\x00\x00\x18ftypisom'+b'0'*40)


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.root=Path(__file__).resolve().parents[1]
        self.tmp=self.root/('zar-test-'+uuid.uuid4().hex);self.tmp.mkdir()
        self.env=patch.dict(os.environ,{'ZAR_DATA_DIR':str(self.tmp)},clear=True);self.env.start()
        self.scope='workflow-test'
    def tearDown(self):
        self.env.stop();assert self.tmp.resolve().is_relative_to(self.root);shutil.rmtree(self.tmp)
    def proposal(self,**extra):
        return {'source_agent':'RevenueAgent','task':'Inspect','action':'Read ledger','expected_cost':0,
                'resources':['local_read'],'risk':.1,'urgency':.5,**extra}

    def test_jev_null_estimates_persistence_and_scopes(self):
        row=jev.proposal(self.scope,self.proposal())
        self.assertEqual(row['decision'],'APPROVE');self.assertIsNone(row['output']['expected_profit'])
        self.assertIsNone(row['output']['confidence'])
        self.assertEqual(holdings.read(self.scope)['jev_decisions'][0]['id'],row['id'])
        self.assertNotIn('jev_decisions',holdings.read('other'))
        row=jev.proposal(self.scope,self.proposal(expected_cost=None,risk=None))
        self.assertEqual(row['decision'],'DEFER')

    def test_jev_provider_cannot_unlock_financial_action(self):
        with patch.dict(os.environ,{'JEV_API_KEY':'OFFLINE_ONLY'}),patch.object(jev,'decide',return_value={'fallback':False,'state':'ONLINE','answers':{'route':{'choice':'APPROVE','confidence':.9}}}):
            row=jev.proposal(self.scope,self.proposal(action='pagar dominio',expected_cost=10,expected_revenue=30),use_provider=True)
            self.assertEqual(row['decision'],'ESCALATE');self.assertEqual(row['output']['expected_profit'],'20')
            self.assertEqual(next(x for x in inventory(holdings.read(self.scope)) if x['name']=='JEV')['state'],'LISTO')
            with patch.dict(os.environ,{'JEV_API_KEY':'CHANGED_OFFLINE_KEY'}):
                self.assertEqual(next(x for x in inventory(holdings.read(self.scope)) if x['name']=='JEV')['state'],'POR CONFIGURAR')

    def test_jev_rejects_nonfinite_and_unexpected_fields(self):
        for data in (self.proposal(expected_cost='NaN'),self.proposal(risk=float('inf')),self.proposal(api_key='secret')):
            with self.assertRaises((ValueError,ArithmeticError)):jev.proposal(self.scope,data)

    def test_site_code_project_and_seo(self):
        p=sites.create(self.scope,{'name':'My site','code':'<html><title>Test</title><h1>Hi</h1></html>'})
        self.assertEqual(p['state'],'READY');self.assertEqual(sites.get(self.scope,p['id'])['id'],p['id'])
        result=sites.analyze(self.scope,p['id']);self.assertTrue(result['checks']['title']);self.assertFalse(result['checks']['description'])
        from flask import Response as FlaskResponse
        header=sites.preview_headers(FlaskResponse()).headers['Content-Security-Policy']
        self.assertIn('sandbox allow-scripts',header);self.assertNotIn('allow-same-origin',header)

    def test_zip_rejects_traversal_and_secrets(self):
        for filename in ('../outside.html','.env','server.py','C:/file.html'):
            archive=io.BytesIO()
            with zipfile.ZipFile(archive,'w') as z:z.writestr(filename,'not extracted')
            with self.assertRaises(ValueError):sites.create(self.scope,{'name':'unsafe'},[('project.zip',archive.getvalue())])
        self.assertEqual(holdings.read(self.scope)['ledger'],[])

    def test_static_zip_and_domain_not_fetched(self):
        archive=io.BytesIO()
        with zipfile.ZipFile(archive,'w') as z:z.writestr('index.html','<h1>Hi</h1>');z.writestr('css/style.css','body{}')
        p=sites.create(self.scope,{'name':'import'},[('project.zip',archive.getvalue())])
        self.assertIn('css/style.css',p['files'])
        domain=sites.create(self.scope,{'name':'domain','domain':'example.com'})
        self.assertEqual(domain['state'],'DRAFT')
        with self.assertRaises(ValueError):sites.analyze(self.scope,domain['id'])

    def test_automaton_site_task_consults_jev_without_paid_search(self):
        p=sites.create(self.scope,{'name':'Idea','topic':'Astronomy'})
        control.mutate(self.scope,'mode',{'mode':'SHADOW'})
        control.mutate(self.scope,'task',{'agent':'SiteBuilderAgent','tool':'site_build','project_id':p['id']})
        control.tick(self.scope);self.assertEqual(sites.get(self.scope,p['id'])['state'],'DRAFT')
        control.mutate(self.scope,'mode',{'mode':'SUPERVISED'})
        with patch('app.web_search._public_search',return_value={'results':[]}),patch('app.sites_company.public_search_results',side_effect=AssertionError('No paid search')):
            control.tick(self.scope)
        self.assertEqual(sites.get(self.scope,p['id'])['state'],'READY')
        self.assertEqual(holdings.read(self.scope)['jev_decisions'][-1]['subsequent_state'],'DONE')

    def test_adsense_estimated_finalized_received_and_idempotency(self):
        session=GoogleSession()
        with patch.dict(os.environ,{'GOOGLE_ADSENSE_ACCESS_TOKEN':'OFFLINE_ONLY'}),patch.object(ads,'AdSenseAdapter',return_value=ads.AdSenseAdapter(session)):
            r=ads.sync(self.scope)
            self.assertEqual(r['classification'],'ESTIMATED');self.assertEqual(r['metrics']['PAGE_VIEWS_CTR'],'0.02')
            self.assertIsNone(r['metrics']['CLICKS']);self.assertIsNone(r['google_updated_at'])
            self.assertEqual(control.view(self.scope)['wallet']['balances'],{})
            paid=r['payments'][1]['reference'];unpaid=r['payments'][0]['reference']
            with self.assertRaises(ValueError):ads.confirm_received(self.scope,unpaid,'bank',True)
            with self.assertRaises(ValueError):ads.confirm_received(self.scope,paid,'bank',False)
            ads.confirm_received(self.scope,paid,'BANK-REFERENCE',True);ads.confirm_received(self.scope,paid,'BANK-REFERENCE',True)
            self.assertEqual(len(holdings.read(self.scope)['ledger']),1)
            self.assertEqual(float(control.view(self.scope)['wallet']['balances']['EUR']['available']),80)
            ads.sync(self.scope)
            self.assertEqual(holdings.read(self.scope)['adsense']['payments'][1]['classification'],'RECEIVED')

    def test_adsense_locale_currency_not_invented(self):
        for raw,expected in [('€1.234,57',('1234.57','EUR')),('$1,234.57',('1234.57','USD')),('£87.65',('87.65','GBP')),('n/a',(None,None))]:
            self.assertEqual(ads.parse_amount(raw),expected)

    def test_media_project_lifecycle_trace_and_options(self):
        fake=FakeDrama()
        task=media.queue_story(self.scope,'The full story',options={'title':'Film','language':'es','format':'16:9','subtitles':False,'music':True})
        record=media._read(self.scope,task['id']);self.assertEqual(record['project_state'],'DRAFT')
        with patch.object(media,'_client',return_value=fake):
            media.produce_local(self.scope,task['id']);media.process_one(self.scope)
        record=media._read(self.scope,task['id']);self.assertEqual(record['project_state'],'REVIEW')
        self.assertIn('The full story',fake.briefs[0]);self.assertIn('16:9',fake.briefs[0])
        self.assertIsNone(record['costs']['actual']);self.assertTrue(record['agent_trace'])
        projects.controls(self.scope,task['id'],'ready',{'confirmed':True})
        self.assertEqual(media._read(self.scope,task['id'])['project_state'],'READY')
        media.edit_story(self.scope,task['id'],'Revised script')
        record=media._read(self.scope,task['id']);self.assertEqual(record['project']['format'],'16:9')
        self.assertFalse(record['review_approved'])

    def test_invalid_media_options_do_not_create_task(self):
        with self.assertRaises(ValueError):media.queue_story(self.scope,'Story',options={'format':'wrong'})
        self.assertEqual(holdings.read(self.scope)['companies']['media']['queue'],[])

    def test_subtitles_and_voice_assets_are_honest_and_persisted(self):
        task=media.queue_story(self.scope,'Story',options={});task_id=task['id']
        record=media._read(self.scope,task_id);record['characters']=[{'name':'Luna','description':'Astronaut'}];media._save(self.scope,task_id,record)
        projects.controls(self.scope,task_id,'voice',{'character':'Luna','voice':'voice-id'})
        with self.assertRaises(ValueError):projects.controls(self.scope,task_id,'subtitles',{'text':'No timings'})
        projects.controls(self.scope,task_id,'subtitles',{'text':'1\n00:00:01,000 --> 00:00:02,000\nHello','size':28})
        with patch.object(projects.VoiceAdapter,'synthesize',return_value=(b'OFFLINE_AUDIO','audio/mpeg','ElevenLabs')):
            with self.assertRaises(ValueError):projects.controls(self.scope,task_id,'character_audio',{'character':'Luna','text':'Hello'})
            projects.controls(self.scope,task_id,'character_audio',{'character':'Luna','text':'Hello','confirmed':True})
        record=media._read(self.scope,task_id);self.assertFalse(record['subtitles']['burned_into_video']);self.assertTrue(record['audio_needs_render'])
        self.assertTrue(record['characters'][0]['voice_preview'])

    def test_workflow_api_csrf_and_http_upload(self):
        from flask import Flask
        from app.business_workflows import register
        app=Flask(__name__);app.secret_key='OFFLINE_TEST_ONLY';register(app,lambda:self.scope)
        with app.test_client() as client:
            self.assertEqual(client.post('/api/holdings/workflows/site_create',json={'name':'x'}).status_code,403)
            token=client.get('/api/holdings/workflows').json['csrf'];headers={'X-ZAR-Business-CSRF':token}
            r=client.post('/api/holdings/workflows/site_upload',data={'name':'uploaded','files':(io.BytesIO(b'<h1>Hi</h1>'),'index.html')},headers=headers)
            self.assertEqual(r.status_code,200);self.assertEqual(r.json['result']['state'],'READY')
            r=client.post('/api/holdings/workflows/jev',json={'proposal':self.proposal()},headers=headers)
            self.assertEqual(r.json['result']['decision'],'APPROVE')

    def test_subtitle_render_blocks_review_and_preserves_previous_revision(self):
        task=media.queue_story(self.scope,'Story',options={'subtitles':False})
        with patch.object(media,'_client',return_value=FakeDrama()):
            media.produce_local(self.scope,task['id']);media.process_one(self.scope)
        projects.controls(self.scope,task['id'],'subtitles',{'text':'1\n00:00:00,000 --> 00:00:01,000\nHello','size':30,'position':'top'})
        with self.assertRaises(ValueError):projects.controls(self.scope,task['id'],'ready',{'confirmed':True})
        with patch.object(projects.MediaRenderAdapter,'render',return_value={'clean_source':'archived.mp4','burned_into_video':True}) as render:
            projects.controls(self.scope,task['id'],'render_final',{})
            self.assertEqual(render.call_args.args[1]['position'],'top')
        projects.controls(self.scope,task['id'],'ready',{'confirmed':True})
        media.edit_story(self.scope,task['id'],'Revision')
        record=media._read(self.scope,task['id'])
        self.assertTrue(any(x.get('source')=='previous_revision' for x in record['renders']))
        self.assertFalse(media._path(self.scope,task['id']).with_suffix('.mp4').exists())

    def test_publishing_review_and_per_platform_idempotence(self):
        task=media.queue_story(self.scope,'Story',options={})
        with patch.object(media,'_client',return_value=FakeDrama()):
            media.produce_local(self.scope,task['id']);media.process_one(self.scope)
        with self.assertRaises(ValueError):media.publish(self.scope,task['id'],'','youtube',confirmed=True)
        projects.controls(self.scope,task['id'],'ready',{'confirmed':True})
        with patch('app.media_adapters.PublishingAdapter.youtube',return_value={'ok':True,'platform':'youtube','id':'offline-id','pending_publish':False}) as upload:
            media.publish(self.scope,task['id'],'','youtube',confirmed=True)
            media.publish(self.scope,task['id'],'','youtube',confirmed=True)
            self.assertEqual(upload.call_count,1)
        with patch.object(media,'tiktok_direct_post',return_value={'ok':True,'data':{'publish_id':'offline-tiktok'}}):
            media.publish(self.scope,task['id'],'https://offline.invalid/video','tiktok',confirmed=True)
        self.assertEqual(len(media._read(self.scope,task['id'])['publications']),2)


if __name__=='__main__':unittest.main()
