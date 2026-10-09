"""Offline Media persistence and authorization regression tests."""
import importlib
import threading
from pathlib import Path
from unittest.mock import patch
import pytest
from app import holdings, media_company as media

@pytest.fixture
def scope(monkeypatch, tmp_path):
    monkeypatch.setenv('ZAR_DATA_DIR', str(tmp_path))
    monkeypatch.setenv('DRAMACLAW_API_URL', 'https://drama.invalid')
    monkeypatch.delenv('ZAR_ACCESS_PASSWORD', raising=False)
    media._HEALTH.clear()
    return 'media-test'

class FakeClient:
    def __init__(self): self.briefs=[]; self.submissions=0
    def health(self): return {'ready':True}
    def advance(self,cp,brief,persist,narrator=None):
        self.briefs.append(brief)
        if not cp:
            cp.update(project_id='project-1',stage='ingest',status='running',progress=10,tasks=[{'task_id':'job-1'}])
            persist(cp); self.submissions+=1
        else: cp.update(stage='done',status='done',progress=100,video_url='https://drama.invalid/final.mp4')
        return cp
    def download_final(self,cp,path): path.write_bytes(b'\x00\x00\x00\x18ftypisom'+b'0'*20)

def configured(monkeypatch):
    client=FakeClient(); monkeypatch.setattr(media,'_client',lambda:client); return client

def test_production_options_are_not_ingested_as_story_paragraphs(scope,monkeypatch):
    client=configured(monkeypatch)
    story='Una semilla brota al amanecer.'
    task=media.queue_story(scope,story,options={'duration':5,'format':'9:16','max_scenes':1})
    media.produce_local(scope,task['id'])
    media.process_one(scope)
    assert client.briefs == [story]
    record=media._read(scope,task['id'])
    assert record['project']['max_scenes'] == 1

def finished(scope,monkeypatch):
    c=configured(monkeypatch); task=media.queue_story(scope,'Historia completa')
    media.produce_local(scope,task['id']); media.process_one(scope); media.process_one(scope)
    return task,c

def test_full_brief_progress_refresh_restart_final_mp4(scope,monkeypatch):
    c=configured(monkeypatch); brief='  Inicio\n'+('á detalle\n'*2000)+'FIN  '
    t=media.queue_story(scope,brief); assert t['payload']['master_brief']==brief
    assert media.produce_local(scope,t['id'])['status']=='PRODUCING' and not c.submissions
    media.process_one(scope); first=media.jobs(scope)['tasks'][-1]
    assert first['result']['progress']==10 and not first['result'].get('preview_url')
    importlib.reload(media); monkeypatch.setattr(media,'_client',lambda:c)
    assert media.jobs(scope)['tasks'][-1]['result']['task_ids'][0]['task_id']=='job-1'
    media.produce_local(scope,t['id']); media.process_one(scope)
    assert media.jobs(scope)['tasks'][-1]['status']=='PRODUCED'
    assert c.briefs==[brief,brief] and c.submissions==1
    assert media.video_path(scope,t['id']).read_bytes()[4:8]==b'ftyp'

def test_error_no_fallback_or_secrets(scope,monkeypatch):
    c=configured(monkeypatch); t=media.queue_story(scope,'Historia'); media.produce_local(scope,t['id'])
    def fail(*a,**kw): raise RuntimeError('SECRET_PROVIDER_TOKEN')
    monkeypatch.setattr(c,'advance',fail); media.process_one(scope)
    r=media._read(scope,t['id']); assert r['status']=='ERROR' and 'SECRET' not in r['error']
    assert not list(media._root(scope).glob('*.mp4'))

def test_lock_pause_queue_do_not_generate(scope,monkeypatch):
    c=configured(monkeypatch); t=media.queue_story(scope,'Historia')
    holdings.set_company_state(scope,'media','start'); media.process_one(scope); assert not c.submissions
    media.produce_local(scope,t['id'])
    with media._job_lock(scope,t['id']) as locked:
        assert locked; media.process_one(scope); assert not c.submissions
    holdings.set_global_stop(scope,True); media.process_one(scope); assert not c.submissions
    with pytest.raises(ValueError,match='detenido'): media.produce_local(scope,t['id'])

def test_edit_regenerates_without_reusing_old_mp4(scope,monkeypatch):
    t,c=finished(scope,monkeypatch); media.edit_story(scope,t['id'],'Nuevo final')
    r=media._read(scope,t['id']); assert r['payload']['original_master_brief']=='Historia completa'
    assert r['payload']['master_brief'].endswith('Nuevo final') and r['history'][0]['project_id']=='project-1'
    assert not media._path(scope,t['id']).with_suffix('.mp4').exists()
    media.produce_local(scope,t['id']); media.process_one(scope); assert c.submissions==2
    with pytest.raises(ValueError,match='activa'): media.edit_story(scope,t['id'],'No duplicar')

def test_publish_confirmation_ownership_no_duplicates(scope,monkeypatch):
    t,c=finished(scope,monkeypatch); sent=[]
    monkeypatch.setattr(media,'tiktok_direct_post',lambda url,caption,confirmed,privacy:sent.append(url) or {'ok':True,'publish_id':'social-1'})
    assert media.publish(scope,t['id'],'','tiktok')['requires_review'] and not sent
    with pytest.raises(ValueError): media.video_path('other-user',t['id'])
    assert media.publish(scope,t['id'],'https://zar.invalid/signed.mp4','tiktok',confirmed=True)['ok']
    media.publish(scope,t['id'],'https://zar.invalid/signed.mp4','tiktok',confirmed=True); assert len(sent)==1

def test_app_jobs_video_and_signed_social_export(scope,monkeypatch):
    with patch.object(threading.Thread,'start'): main=importlib.import_module('app.main')
    monkeypatch.setattr(main,'_user_scope_id',lambda:scope)
    t,c=finished(scope,monkeypatch); web=main.app.test_client()
    assert web.get('/health').json['ok'] and web.get('/api/holdings/media/jobs').json['tasks'][-1]['status']=='PRODUCED'
    assert web.get('/api/holdings/media/video/'+t['id']).mimetype=='video/mp4'
    sent=[]; monkeypatch.setattr(media,'tiktok_direct_post',lambda url,caption,confirmed,privacy:sent.append(url) or {'ok':True})
    payload={'task_id':t['id'],'platform':'tiktok','confirmed':'false'}
    assert web.post('/api/holdings/media/publish',json=payload).json['requires_review'] and not sent
    payload.update(confirmed=True,video_url='https://evil.invalid/fake.mp4')
    assert web.post('/api/holdings/media/publish',json=payload).json['ok'] and 'evil' not in sent[0]
    from urllib.parse import urlsplit
    monkeypatch.setenv('ZAR_ACCESS_PASSWORD','TEST_ONLY')
    assert web.get('/api/holdings/media/video/'+t['id']).status_code==401
    assert web.get(urlsplit(sent[0]).path).mimetype=='video/mp4'
    assert web.get('/media-public/forged.mp4').status_code==404

def test_version_consistency():
    root=Path(__file__).parents[1]
    assert {root.joinpath(p).read_text().strip() for p in ('VERSION','VERSION.txt','app/VERSION.txt')}=={'33.3.23'}

def test_reels_resume_existing_container_once(scope,monkeypatch):
    t,c=finished(scope,monkeypatch)
    monkeypatch.setattr(media,'instagram_reel',lambda *a,**kw:{'ok':True,'pending_publish':True,'container_id':'container-1'})
    monkeypatch.setenv('INSTAGRAM_ACCESS_TOKEN','TEST_ONLY');monkeypatch.setenv('INSTAGRAM_IG_USER_ID','user-1')
    media.publish(scope,t['id'],'https://zar.invalid/signed.mp4','instagram',confirmed=True)
    class Response:
        ok=True
        def __init__(self,data):self.data=data
        def json(self):return self.data
    sent=[]
    monkeypatch.setattr(media.requests,'get',lambda *a,**kw:Response({'status_code':'FINISHED'}))
    monkeypatch.setattr(media.requests,'post',lambda url,**kw:sent.append((url,kw)) or Response({'id':'published-1'}))
    media.process_one(scope);media.process_one(scope)
    assert len(sent)==1 and sent[0][1]['params']['creation_id']=='container-1'
    assert media._read(scope,t['id'])['status']=='PUBLISHED'

def test_tiktok_tracks_actual_completion_without_reposting(scope,monkeypatch):
    t,c=finished(scope,monkeypatch)
    monkeypatch.setattr(media,'tiktok_direct_post',lambda *a,**kw:{'ok':True,'data':{'publish_id':'video-1'}})
    monkeypatch.setenv('TIKTOK_ACCESS_TOKEN','TEST_ONLY')
    media.publish(scope,t['id'],'https://zar.invalid/signed.mp4','tiktok',confirmed=True)
    assert media._read(scope,t['id'])['status']=='PUBLISHING'
    class Response:
        ok=True
        def json(self):return {'data':{'status':'PUBLISH_COMPLETE'}}
    sent=[];monkeypatch.setattr(media.requests,'post',lambda url,**kw:sent.append(url) or Response())
    media.process_one(scope);media.process_one(scope)
    assert sent==['https://open.tiktokapis.com/v2/post/publish/status/fetch/']
    assert media._read(scope,t['id'])['status']=='PUBLISHED'
