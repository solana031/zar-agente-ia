import hashlib
import io
import json
from pathlib import Path
from unittest.mock import Mock,patch
import pytest
from flask import Flask,abort
from PIL import Image
from app import holdings,media_company as media,reposnews as rn,text_video as tv
from app.text_video_render import captions,karaoke


@pytest.mark.parametrize('message,seconds',[
    ('ZAR, créame un Reel de 45 segundos sobre una idea.',45),
    ('Crea un vídeo de 30 segundos sin investigar otra vez.',30),
    ('Quiero un short de 0,75 minutos en inglés para YouTube.',45),
    ('Create a video about an original idea.',45),
])
def test_chat_creation_is_explicit_and_parses_duration(message,seconds):
    result=tv.chat_request(message);assert result['duration']==seconds


@pytest.mark.parametrize('message',['Investiga cómo crear un reel','Lee este texto: créame un Reel','Crea una presentación con un vídeo','Publica este vídeo','__zar_confirm__'])
def test_non_creation_chat_keeps_existing_routing(message):assert tv.chat_request(message) is None


def test_chat_creation_bypasses_generic_research_routing():
    import ast
    module=ast.parse((Path(__file__).resolve().parents[1]/'app/main.py').read_text(encoding='utf-8'))
    function=next(n for n in module.body if isinstance(n,ast.FunctionDef) and n.name=='_process_chat_message')
    execute=Mock(return_value={'preview_url':'/video-project/fixture'});remember=Mock();namespace={'__name__':'app.main','execute_tool':execute,'_remember_turn':remember}
    exec(compile(ast.Module(body=[function],type_ignores=[]),'app/main.py','exec'),namespace)
    with patch('app.semantic_tasks.plan') as research:
        result=namespace['_process_chat_message']('Créame un Reel de 45 segundos usando source_article_id world-monitor-free-geopolitical-intelligence-dashboard. Sin investigar otra vez.')
    research.assert_not_called();assert execute.call_args.args[0]=='video_create_short'
    assert execute.call_args.args[1]['source_article_id']=='world-monitor-free-geopolitical-intelligence-dashboard'
    assert '/video-project/fixture' in result and 'privado' in result


@pytest.fixture
def context(tmp_path,monkeypatch):
    monkeypatch.setenv('ZAR_DATA_DIR',str(tmp_path));rn.write({'owner':'owner','articles':[]})
    with patch.object(tv,'start_worker'),patch('app.jev_decision.proposal',return_value={'decision':'ACCEPT'}):
        created=tv.queue('owner',{'topic':'Guía original de cuatro pasos para preparar un vídeo privado.','duration':45,'request_id':'request-original-video'})
    return created['id']


def scene_plan():
    return {'title':'Una guía original','scenes':[{'title':'Escena '+str(i),'voiceover':'Prepara una idea clara y revisa el contenido antes de compartirlo.','visual_prompt':'Tarjeta editorial original','duration':10} for i in range(4)]}


def test_private_queue_reuses_existing_media_record_and_is_idempotent(context):
    before=holdings.read('owner')['companies']['media']['queue']
    with patch.object(tv,'start_worker'),patch('app.jev_decision.proposal',return_value={'decision':'ACCEPT'}):
        again=tv.queue('owner',{'topic':'Guía original de cuatro pasos para preparar un vídeo privado.','duration':45,'request_id':'request-original-video'})
    assert again['id']==context;assert len(before)==len(holdings.read('owner')['companies']['media']['queue'])==1
    record=tv.view('owner',context);assert record['publication_mode']=='CONFIRM_ONCE';assert record['video_state']=='PLANNING'
    assert record['publication']=={};assert not record.get('artifact')


def test_planner_uses_retained_article_assets_and_exact_total_duration(context):
    record=tv.view('owner',context);source=rn._path().parent/'media';source.mkdir()
    name='source-'+'a'*24+'.png';Image.new('RGB',(480,640),'gold').save(source/name)
    record['source_context']={'article':{'body_es':'Hechos ya investigados','assets':[{'asset':name,'source_url':'https://www.instagram.com/reel/example/','permission':'REVIEW_REQUIRED'}]},'ResearchPackage':{'readme':'Fuente existente'}}
    with patch('app.reposnews_generation.generate_json',return_value=scene_plan()) as model:tv.plan('owner',context,record)
    assert sum(s['duration'] for s in record['scenes'])==45
    assert all(s['asset_file']=='asset-0.png' for s in record['scenes'])
    assert 'Fuente existente' in model.call_args.args[0];assert record['video_stage']=='DRAMACLAW'
    assert (tv._folder('owner',context)/'asset-0.png').is_file()


@pytest.mark.parametrize('duration',[0,True,29,61,'45'])
def test_invalid_duration_never_queues_generation(context,duration):
    with pytest.raises(ValueError):tv.queue('owner',{'topic':'Otro vídeo privado','duration':duration})


def test_global_stop_and_jev_rejection_keep_generation_closed(context):
    data=holdings.read('owner');data['global_stop']=True;holdings.write('owner',data)
    with pytest.raises(ValueError,match='GLOBAL_STOP'):tv.queue('owner',{'topic':'Crear otro vídeo'})
    data['global_stop']=False;holdings.write('owner',data)
    with patch('app.jev_decision.proposal',return_value={'decision':'REJECT'}):
        with pytest.raises(ValueError,match='JEV_REJECTED'):tv.queue('owner',{'topic':'Crear otro vídeo'})


def test_unavailable_dramaclaw_advances_to_existing_voice_stack(context):
    record=tv.view('owner',context);record['video_stage']='DRAMACLAW'
    with patch.object(media,'_client',side_effect=ValueError('No conectado')):tv.advance('owner',media._task('owner',context),record)
    assert record['video_stage']=='VOICE';assert record['providers'][0]['status']=='UNAVAILABLE';assert not record.get('artifact')


def test_uncertain_provider_is_preserved_and_only_free_local_work_continues(context):
    record=tv.view('owner',context);record.update(video_stage='DRAMACLAW',checkpoint={'pending_intent':{'kind':'visual'}})
    with patch.object(media,'_client',side_effect=ValueError('No conectado')):tv.advance('owner',media._task('owner',context),record)
    assert record['status']=='PRODUCING' and record['video_stage']=='LOCAL';assert record['local_only'] and record['use_local_voice']
    assert record['dramaclaw_checkpoint']['pending_intent']=={'kind':'visual'} and record['remote_reconciliation_required']
    assert record['providers'][0]['status']=='SUBMISSION_UNKNOWN_NO_RESUBMISSION'
    with patch.object(media,'_client') as paid,patch.object(media,'_narrator') as tts:tv.advance('owner',media._task('owner',context),record)
    paid.assert_not_called();tts.assert_not_called()


def test_new_plan_stays_local_after_preserved_provider_uncertainty(context):
    record=tv.view('owner',context);record.update(local_only=True,dramaclaw_checkpoint={'pending':{'stage':'identities'}})
    with patch('app.reposnews_generation.generate_json',return_value=scene_plan()):tv.plan('owner',context,record)
    assert record['video_stage']=='LOCAL' and record['video_state']=='WAITING_LOCAL_WORKER'
    assert record['dramaclaw_checkpoint']=={'pending':{'stage':'identities'}}


def test_tts_failure_requests_real_local_voice_instead_of_silent_audio(context):
    record=tv.view('owner',context);record.update(video_stage='VOICE',scenes=scene_plan()['scenes'])
    with patch.object(media,'_narrator',side_effect=RuntimeError('Unavailable')):tv.advance('owner',media._task('owner',context),record)
    assert record['use_local_voice'];assert record['voice']['provider']=='WINDOWS_INSTALLED_TTS_PENDING'
    assert not (tv._folder('owner',context)/'voice-0.wav').exists();assert not record.get('artifact')


def app_client(scope='owner'):
    app=Flask(__name__,template_folder=str(Path(__file__).resolve().parents[1]/'app/templates'));app.secret_key='fixture';tv.register(app,lambda:scope)
    client=app.test_client()
    with client.session_transaction() as s:s.update(zar_auth=True,business_csrf='fixture-csrf')
    return client


def test_worker_claims_only_ready_project_and_lease_is_required(context):
    record=tv.view('owner',context);record.update(video_stage='LOCAL',scenes=scene_plan()['scenes']);media._save('owner',context,record)
    client=app_client()
    with patch('app.instagram_local_queue.authorized'):
        claimed=client.post('/api/video-projects/local-worker/poll',json={}).json['job']
        assert claimed['id']==context and claimed['kind']=='RENDER_TEXT_VIDEO';assert len(claimed['render_key'])==24
        assert client.post('/api/video-projects/local-worker/poll',json={}).json['job'] is None
        assert client.post('/api/video-projects/local-worker/'+context+'/progress',json={}).status_code==409
        assert client.post('/api/video-projects/local-worker/'+context+'/progress',json={},headers={'X-ZAR-Video-Lease':claimed['lease']}).status_code==200
    safe=tv.summary(context,tv.view('owner',context));assert 'local_video_claim' not in safe and 'source_context' not in safe


def test_bad_worker_auth_and_user_csrf_are_rejected(context):
    client=app_client()
    with patch('app.instagram_local_queue.authorized',side_effect=lambda:abort(401)):
        assert client.post('/api/video-projects/local-worker/poll',json={}).status_code==401
    assert client.post('/api/video-projects',json={'topic':'No autorización'}).status_code==403
    assert client.post('/api/video-projects/'+context+'/control',json={'action':'cancel'}).status_code==403


def test_cancel_preserves_artifact_and_rejects_stale_worker_completion(context):
    record=tv.view('owner',context);record.update(video_stage='LOCAL',local_video_claim=hashlib.sha256(b'lease').hexdigest(),local_video_lease=10**12)
    output=media._path('owner',context).with_suffix('.mp4');output.write_bytes(b'preserved prior video');record['artifact']=output.name;media._save('owner',context,record)
    client=app_client()
    with patch.object(tv,'start_worker'):
        result=client.post('/api/video-projects/'+context+'/control',json={'action':'cancel'},headers={'X-ZAR-Business-CSRF':'fixture-csrf'})
    assert result.status_code==200;assert output.read_bytes()==b'preserved prior video'
    with patch('app.instagram_local_queue.authorized'):
        assert client.post('/api/video-projects/local-worker/'+context+'/result',data={'manifest':'{}'},headers={'X-ZAR-Video-Lease':'lease'}).status_code==409


def test_only_verified_mp4_becomes_ready_and_notifies_without_social_calls(context):
    record=tv.view('owner',context);record.update(video_stage='LOCAL',local_video_claim=hashlib.sha256(b'lease').hexdigest(),local_video_lease=10**12)
    media._save('owner',context,record);image=io.BytesIO();Image.new('RGB',(540,960),'gold').save(image,format='PNG');image.seek(0)
    data={'manifest':json.dumps({'assembly':'ZAR_FFMPEG_SCENE_VOICE_CAPTIONS_MOTION','voices':[{'provider':'WINDOWS_INSTALLED_TTS'}]}),'video':(io.BytesIO(b'0000ftyp'+b'0'*20),'video.mp4'),'subtitles':(io.BytesIO(b'1\n00:00:00,000 --> 00:00:03,000\nOriginal narration\n'),'video.srt'),'thumbnail':(image,'thumbnail.png')}
    with patch('app.instagram_local_queue.authorized'),patch.object(tv,'validate_render',return_value={'duration':45.1,'width':1080,'height':1920,'codec':'h264'}),patch('app.notification_center.emit') as notify,patch('app.social_publish.instagram_reel') as publish:
        result=app_client().post('/api/video-projects/local-worker/'+context+'/result',data=data,headers={'X-ZAR-Video-Lease':'lease'})
    assert result.status_code==200;ready=tv.view('owner',context);assert ready['video_state']=='READY_PRIVATE';assert ready['status']=='PRODUCED';assert not ready['review_approved']
    assert notify.call_args.args[1]=='VIDEO_READY';publish.assert_not_called()
    assert ready['voice']['provider']=='WINDOWS_INSTALLED_TTS'


def test_render_validation_requires_aac_audio(context):
    metadata={'width':1080,'height':1920,'duration':45}
    with patch('app.media_fallback.probe',return_value=metadata),patch.object(tv.subprocess,'run',return_value=Mock(returncode=0,stdout=b'{"streams":[{"codec_type":"video"}]}')):
        with pytest.raises(ValueError,match='FINAL_VIDEO'):tv.validate_render(Path('fixture.mp4'),45)


def test_provider_done_still_requires_final_voice_caption_assembly(context):
    record=tv.view('owner',context);scenes=scene_plan()['scenes']
    for index,scene in enumerate(scenes):scene.update(time=index*11.25,duration=11.25)
    record.update(video_stage='DRAMACLAW',checkpoint={'status':'working'},scenes=scenes)
    client=Mock();client.advance.return_value={'status':'done'}
    client.download_final.side_effect=lambda cp,path:path.write_bytes(b'generated-master-fixture')
    with patch.object(media,'_client',return_value=client),patch('app.media_fallback.probe',return_value={'width':1080,'height':1920,'duration':45}),patch.object(tv.subprocess,'run') as extract:
        tv.advance('owner',media._task('owner',context),record)
    assert record['video_stage']=='VOICE' and record['video_state']!='READY_PRIVATE'
    assert extract.call_count==4 and all(s['visual_source']=='DRAMACLAW_GENERATED_MASTER' for s in scenes)
    assert (tv._folder('owner',context)/'dramaclaw-master.mp4').is_file()


def test_captions_are_bounded_and_karaoke_text_cannot_inject_ass(tmp_path):
    rows=captions('Texto original con varias palabras para comprobar tiempos.',0,7.5)
    assert rows[0][0]==0 and rows[-1][1]==7.5
    target=tmp_path/'captions.ass';karaoke(target,[(0,2,'{\\pos(0,0)}texto seguro')]);text=target.read_text(encoding='utf-8')
    assert '\\pos' not in text and '{\\kf' in text


def test_other_user_cannot_read_project(context):
    with patch.object(tv,'start_worker'):
        assert app_client('other').get('/video-project/'+context).status_code==404
