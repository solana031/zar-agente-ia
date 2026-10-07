"""Scoped API for JEV, Media projects and Sites; uses existing stores/workers."""
import secrets
from flask import jsonify, request, session, send_file, Response, url_for
from . import holdings, jev_decision, media_company, sites_company, site_projects, adsense_adapter

def connector_failure(scope,action):
    name={'commerce_shopify_sync':'Shopify','agency_payment_probe':'Payment','agency_discover':'Google Maps'}.get(action)
    if name:
        from .business_connectors import verification,inventory
        row=next(x for x in inventory() if x['name']==name)
        with holdings.transaction(scope):
            d=holdings.read(scope);d.setdefault('verified_connectors',{})[name]=verification(name,'POR CONFIGURAR' if row['missing'] else 'ERROR')
            holdings.write(scope,d)


def view(scope):
    d=holdings.read(scope)
    media=[]
    for task in d['companies']['media'].get('queue',[]):
        record=media_company._read(scope,task['id'])
        media.append({'id':task['id'],'payload':record.get('payload',task.get('payload')),
            'status':record.get('status',task.get('status')),'error':record.get('error',task.get('error')),
            'result':media_company._result(task,record), 'publications':record.get('publications',[]),
            'voice_assets':record.get('voice_assets',{})})
    from .commerce_workspace import view as commerce_view
    from .agency_crm import view as agency_view
    from .identity_provisioning import view as identity_view
    from .identity_center import view as identity_center_view
    center=identity_center_view(scope)
    adsense={**d.get('adsense',{'state':'POR CONFIGURAR','metrics':None,'payments':[]})}
    capability=center['capabilities'].get('ADSENSE',{})
    adsense.update(account_state=capability.get('account_state','ERROR' if capability.get('status')=='ERROR' else 'NOT_VERIFIED'),oauth_capability=capability.get('status','NOT_CONNECTED'))
    return {'identity_center':center,'identity':identity_view(scope),'jev':d.get('jev_decisions',[])[-100:][::-1], 'media':media[-50:][::-1], 'commerce':commerce_view(scope),'agency':agency_view(scope),
        'sites':sites_company.list_sites(scope), 'adsense':adsense,
        'connectors':{k:{x:v.get(x) for x in ('state','checked_at','verification_scope')} for k,v in d.get('verified_connectors',{}).items()}}


def operate(scope, action, data):
    if action=='canva_status':
        from .canva_adapter import CanvaAdapter
        return CanvaAdapter().status(scope)
    if action=='semantic_tasks_status':
        from .semantic_tasks import tasks
        return {'tasks':tasks(scope)}
    if action.startswith('identity_workspace_'):
        from .identity_workspace import operate as workspace
        return workspace(scope,action.removeprefix('identity_workspace_'),data)
    if action.startswith('identity_mail_'):
        from .identity_mail import operate as mail
        return mail(scope,action.removeprefix('identity_mail_'),data)
    if action.startswith('identity_center_'):
        from .identity_center import operate as center
        return center(scope,action.removeprefix('identity_center_'),data)
    if action.startswith('identity_provision_'):
        from .identity_provisioning import operate as provision
        return provision(scope,action.removeprefix('identity_provision_'),data)
    if action in {'identity_email_verify','agency_send','agency_inbound_sync'}:
        from .agency_mail import verify,send,sync_inbound
        return verify(scope) if action=='identity_email_verify' else send(scope,data) if action=='agency_send' else sync_inbound(scope,data)
    if action=='agency_inbound':
        from .agency_events import inbound
        return inbound(scope,data)
    if action.startswith('agency_'):
        from .agency_crm import operate as agency_operate
        return agency_operate(scope,action.removeprefix('agency_'),data)
    if action.startswith('commerce_'):
        from .commerce_workspace import operate as commerce_operate
        return commerce_operate(scope,action.removeprefix('commerce_'),data)
    if action=='jev':
        if data.get('use_provider') is True and data.get('confirmed') is not True:
            raise ValueError('Confirma consulta al modelo TypeSafe con cuota del proveedor.')
        return jev_decision.proposal(scope,data.get('proposal'),use_provider=data.get('use_provider') is True)
    if action=='site_create': return site_projects.create(scope,data)
    if action=='site_analyze': return site_projects.analyze(scope,data['id'])
    if action=='site_build':
        from . import business_orchestration
        project=site_projects.get(scope,data['id'])
        if project.get('state')=='BUILDING': raise ValueError('Construcción ya en curso.')
        task=business_orchestration.mutate(scope,'task',{'agent':'SiteBuilderAgent','tool':'site_build',
            'request_id':data.get('request_id') or 'site-build:'+project['id'],'project_id':project['id']})
        return {'queued':True,'mode':task['mode'],'note':'BusinessOrchestrator debe estar SUPERVISED/ACTIVE; SHADOW conserva la tarea sin ejecutar.'}
    if action=='adsense_sync': return adsense_adapter.sync(scope,data.get('account'),data.get('domain'))
    if action=='adsense_received': return adsense_adapter.confirm_received(scope,data.get('reference'),data.get('bank_reference'),data.get('confirmed'))
    if action=='media_create':
        return media_company.queue_story(scope,data.get('story'),platform=data.get('platform','tiktok'),options=data)
    if action=='media_produce':
        from . import business_orchestration
        if data.get('confirmed') is not True: raise ValueError('Confirma producción con la cuota del proveedor configurado.')
        task=media_company._task(scope,data['id'])
        cost=(media_company._read(scope,data['id']).get('costs') or {}).get('estimated')
        decision=jev_decision.proposal(scope,{'source_agent':'DirectorAgent','task':'Producción DramaClaw','task_id':data['id'],
            'action':'Generate media using configured provider credits','resources':['dramaclaw'],'expected_cost':cost,'expected_revenue':None,'risk':.5,'urgency':.5})
        if decision['decision']=='REJECT': raise ValueError('JEV rechazó la propuesta.')
        result=media_company.produce_local(scope,data['id'])
        jev_decision.decision_state(scope,decision['id'],'USER_CONFIRMED_PROVIDER_GENERATION')
        return result
    if action=='media_edit': return media_company.edit_story(scope,data['id'],data.get('script') or data.get('notes'))
    if action=='media_control':
        from .media_projects import controls
        return controls(scope,data['id'],data['control'],data)
    if action=='probe':
        name=data.get('name'); state='POR CONFIGURAR';result={}
        if name=='DramaClaw DIRECT':
            result=media_company.status();state='LISTO' if result.get('ready') else 'ERROR' if result.get('dramaclaw_direct_configured') else 'POR CONFIGURAR'
        elif name=='ElevenLabs':
            from .media_adapters import VoiceAdapter
            result=VoiceAdapter().voices();state=result['state']
        elif name=='AdSense': result=adsense_adapter.sync(scope,data.get('account'));state='LISTO'
        else: raise ValueError('Usa Probar decisión para comprobar JEV con una inferencia explícita.')
        with holdings.transaction(scope):
            from .business_connectors import verification
            d=holdings.read(scope);d.setdefault('verified_connectors',{})[name]=verification(name,state,'API read access, not generation/billing guarantee')
            holdings.write(scope,d)
        return result
    raise ValueError('Operación no admitida.')


def register(app, scope_fn):
    @app.get('/api/holdings/workflows')
    def business_workflow_view():
        token=session.setdefault('business_csrf',secrets.token_urlsafe(32))
        return jsonify({'ok':True,'csrf':token,**view(scope_fn())})

    @app.post('/api/holdings/workflows/<action>')
    def business_workflow_action(action):
        token=session.get('business_csrf')
        if not token or not secrets.compare_digest(token,request.headers.get('X-ZAR-Business-CSRF','')):
            return jsonify({'ok':False,'error':'Protección CSRF: recarga Orquestación.'}),403
        scope=scope_fn()
        try:
            data=request.get_json(silent=True) or {}
            if action=='site_upload':
                if request.content_length is None or request.content_length > 21*1024*1024:
                    raise ValueError('Carga limitada a 20 MB más campos.')
                result=site_projects.create(scope,dict(request.form),[(x.filename,x.read(20*1024*1024+1)) for x in request.files.getlist('files')])
            elif action=='media_publish':
                if data.get('confirmed') is not True: raise ValueError('Confirma publicación de este vídeo/plataforma.')
                if holdings.read(scope).get('global_stop'): raise ValueError('STOP GLOBAL activo.')
                record=media_company._read(scope,data['id'])
                if not record.get('review_approved'): raise ValueError('Revisa y aprueba el vídeo antes de publicar.')
                from itsdangerous import URLSafeTimedSerializer
                media_company.video_path(scope,data['id'])
                signed=URLSafeTimedSerializer(app.secret_key,salt='media-export-v1').dumps({'scope':scope,'task':data['id'],'project':record['checkpoint']['project_id']})
                video_url=url_for('holdings_media_public_video_api',token=signed,_external=True) if data.get('platform')!='youtube' else ''
                result=media_company.publish(scope,data['id'],video_url,data['platform'],data.get('caption',''),confirmed=True)
            else: result=operate(scope,action,data)
            return jsonify({'ok':True,'result':result})
        except (ValueError,KeyError,StopIteration,TypeError,ArithmeticError) as exc:
            connector_failure(scope,action)
            if action=='probe' and isinstance(data,dict) and data.get('name') in {'ElevenLabs','DramaClaw DIRECT','AdSense'}:
                from .business_connectors import verification
                with holdings.transaction(scope):
                    d=holdings.read(scope);d.setdefault('verified_connectors',{})[data['name']]=verification(data['name'],'ERROR')
                    holdings.write(scope,d)
            return jsonify({'ok':False,'error':str(exc) or 'Registro no encontrado.'}),400
        except Exception:
            connector_failure(scope,action)
            if action=='probe' and isinstance(data,dict) and data.get('name') in {'ElevenLabs','DramaClaw DIRECT','AdSense'}:
                from .business_connectors import verification
                with holdings.transaction(scope):
                    d=holdings.read(scope);d.setdefault('verified_connectors',{})[data['name']]=verification(data['name'],'ERROR')
                    holdings.write(scope,d)
            return jsonify({'ok':False,'error':'Proveedor no disponible o contrato no confirmado. Estado conservado.'}),400

    @app.get('/api/holdings/workflows/media/<task_id>/audio/<asset>')
    def business_voice_asset(task_id,asset):
        scope=scope_fn();media_company._task(scope,task_id)
        row=media_company._read(scope,task_id).get('voice_assets',{}).get(asset)
        if not row or row['state']!='READY':return '',404
        return send_file(media_company._root(scope)/row['filename'],mimetype=row['mime'])

    @app.get('/api/holdings/workflows/media/<task_id>/subtitles')
    def business_subtitles(task_id):
        scope=scope_fn();media_company._task(scope,task_id)
        row=media_company._read(scope,task_id).get('subtitles')
        if not row:return '',404
        return Response(row['text'],mimetype='text/plain',headers={'Content-Disposition':'attachment; filename="subtitles.srt"'})
