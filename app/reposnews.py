"""A small bilingual editorial publication, isolated from the private ZAR host."""
import html
import json
import os
import re
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote
import requests
from flask import abort, redirect, render_template, request, Response, send_file
from markupsafe import Markup
from . import holdings, site_projects

ORIGIN = 'https://www.reposnews.com'
HOSTS = {'reposnews.com','www.reposnews.com'}
STAGES = {'IDEA','RESEARCH','DRAFT','SOURCE_VERIFY','DRAFT_ES','REVIEW','EN_TRANSLATION','SEO','PREVIEW','READY','SCHEDULED','PUBLISHED','ARCHIVED'}


def legal_status(data):
    legal=data.get('legal',{})
    economic=legal.get('activity_mode')!='NONCOMMERCIAL'
    fields={
        'controller':('REQUIRED','Nombre legal del titular y responsable del tratamiento; publicación tras aprobación'),
        'privacy_contact':('REQUIRED','Contacto para consultas y derechos; puede ser el email operativo existente'),
        'activity_mode':('REQUIRED','Confirmar actividad económica/monetización prevista o exclusivamente no comercial; dato administrativo'),
        'entity_type':('REQUIRED','Persona física o entidad; determina aplicabilidad del registro; dato administrativo'),
        'address':('REQUIRED' if economic else 'OPTIONAL','Domicilio administrativo privado; no se muestra en las páginas públicas'),
        'tax_id':('REQUIRED' if economic else 'NOT_APPLICABLE','Identificación fiscal para actividad económica, artículo 10 LSSI; no subir documentos'),
        'registration':('REQUIRED' if legal.get('entity_type')=='REGISTERED_ENTITY' else 'NOT_APPLICABLE','Datos registrales únicamente si existe entidad inscrita'),
        'processing_basis':('REQUIRED','Base jurídica de conexión/seguridad y atención de consultas actuales; revisión del titular'),
        'retention':('REQUIRED','Plazos o criterios reales para logs y correo; no inventar años'),
        'providers_reviewed':('REQUIRED','Confirmar revisión de encargados, contratos y transferencias de Railway/Google; checkbox privado')}
    missing=[k for k,(level,_) in fields.items() if level=='REQUIRED' and not legal.get(k)]
    if legal.get('activity_mode') not in {'ECONOMIC','NONCOMMERCIAL'}: missing=list(dict.fromkeys(missing+['activity_mode']))
    if legal.get('entity_type') not in {'PERSON','REGISTERED_ENTITY'}: missing=list(dict.fromkeys(missing+['entity_type']))
    if legal.get('privacy_contact') and not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',legal['privacy_contact']): missing=list(dict.fromkeys(missing+['privacy_contact']))
    return {'status':'LEGAL_INCOMPLETE' if missing else 'LEGAL_READY' if data.get('legal_reviewed') else 'LEGAL_REVIEW_REQUIRED',
            'fields':{k:{'level':level,'purpose':purpose,'complete':bool(legal.get(k))} for k,(level,purpose) in fields.items()},
            'missing_required':missing,'missing_optional':[k for k,(level,_) in fields.items() if level=='OPTIONAL' and not legal.get(k)],
            'sources':['https://www.boe.es/buscar/act.php?id=BOE-A-2002-13758#a10','https://www.aepd.es/preguntas-frecuentes/2-tus-obligaciones-como-responsable-del-tratamiento/6-el-deber-de-informacion']}


def publication_plan(data, ids):
    ids=list(dict.fromkeys(ids or []))
    if not ids or len(ids)>10: raise ValueError('Selecciona de 1 a 10 guías.')
    articles=[next((a for a in data.get('articles',[]) if a['id']==id),None) for id in ids]
    if not all(articles): raise ValueError('Guía seleccionada no encontrada.')
    seo=all(a.get('state')=='READY' and a.get('sources') and all(a.get(k) for k in ('title_es','title_en','summary_es','summary_en','body_es','body_en')) and all(a.get('seo',{}).get(l,{}).get('canonical') for l in ('es','en')) for a in articles)
    legal=legal_status(data)['status']
    projection={'articles':[{k:a.get(k) for k in ('id','state','updated_at','title_es','title_en','summary_es','summary_en','body_es','body_en','sources','seo')} for a in articles], 'legal':data.get('legal'), 'legal_reviewed':data.get('legal_reviewed')}
    digest=hashlib.sha256(json.dumps(projection,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    return {'ids':ids,'article_count':len(ids),'languages':['es','en'],'urls':[a['seo'][l]['canonical'] for a in articles for l in ('es','en')],
            'titles':[a['title_es'] for a in articles],'seo':'PASS' if seo else 'WARNING','legal':legal,
            'editorial_ready':bool(seo),'ready_to_publish':bool(seo and legal=='LEGAL_READY'),
            'sitemap':'WILL_ADD_SELECTED_ES_EN_URLS','homepage':'WILL_SHOW_NEW_GUIDES_EDITORIAL_SELECTION',
            'published_now':False,'confirmation_required':True,'digest':digest,'date':holdings._now()}


def article_defaults(article):
    a=dict(article);now=holdings._now()
    for key,value in {'slug_es':a['id'],'slug_en':a['id'],'created_at':now,'updated_at':now,
                      'last_reviewed':None,'source_checked_at':a.get('checked_at'),'status':a.get('state','DRAFT'),
                      'repository_url':'https://github.com/'+a['repo'],'official_docs':a.get('website'),
                      'translation_status':'REVIEW_REQUIRED','history':[]}.items():
        a.setdefault(key,value)
    a.setdefault('seo',{l:{'title':a['title_'+l],'description':a['summary_'+l],'canonical':ORIGIN+'/'+l+'/'+('repositorios/' if l=='es' else 'repositories/')+a['slug_'+l]+'/'} for l in ('es','en')})
    if not a['history']: a['history']=[{'at':a['created_at'],'fields':['initial_import'],'reason':'Importación de guía original revisada; no publicada.'}]
    return a


def readiness(data):
    checks={'DOMAIN':data.get('domain_status')=='ACTIVE','HTTPS':data.get('domain_status')=='ACTIVE',
            'CONTENT':any(a.get('published') for a in data.get('articles',[])),
            'ABOUT':True,'CONTACT':True,'PRIVACY':bool(data.get('legal_reviewed')),
            'LEGAL':legal_status(data)['status']=='LEGAL_READY','COOKIES':True,'NAVIGATION':True,
            'MOBILE':True,'SITEMAP':True,'ROBOTS':True,'ADS.TXT':data.get('domain_status')=='ACTIVE',
            'ORIGINAL_CONTENT':bool(data.get('articles')),
            'ADSENSE_ACCOUNT':data.get('adsense_verification',{}).get('web_enabled') is True,
            'ADSENSE_SITE':data.get('adsense_verification',{}).get('site_status') in {'REQUIRES_REVIEW','REVIEW_REQUESTED','READY'}}
    checks['PRIVACY']=checks['LEGAL'];checks['PUBLIC_CONTENT']=checks.pop('CONTENT')
    return {'checks':checks,'status':'READY_TO_SUBMIT' if all(checks.values()) else 'ACTION_REQUIRED',
            'blockers':[k for k,v in checks.items() if not v],
            'submission':'NOT_SUBMITTED','cmp':'NOT_ACTIVE · Google-certified CMP required before serving ads',
            'analytics':'NOT_CONNECTED','site_in_adsense':data.get('adsense_verification',{}).get('site_status','NOT_VERIFIED'),
            'content_assessment':'Tres guías originales permiten un lanzamiento editorial pequeño; Google no fija aquí un mínimo numérico ni garantiza aprobación.',
            'search_console':data.get('search_console_status','NOT_VERIFIED')}


def summary():
    data=read();articles=data.get('articles',[])
    return {'stored':len(articles),'ready':sum(a.get('state')=='READY' for a in articles),
            'published':sum(bool(a.get('published')) for a in articles),
            'persistent':bool(data.get('initialized_at')),'initialized_at':data.get('initialized_at'),
            'domain':data.get('domain_status','VERIFYING')}


def bootstrap():
    """One idempotent import into the operational account, on the persistent volume."""
    from .user_scope import user_id_for_email
    scope=read().get('owner') or user_id_for_email('zaragente031@gmail.com')
    initialize(scope)
    return scope


def _path():
    return Path(os.environ.get('ZAR_DATA_DIR','/data'))/'reposnews'/'editorial.json'


def read():
    try: return json.loads(_path().read_text(encoding='utf-8'))
    except FileNotFoundError: return {'articles':[], 'candidates':[], 'domain_status':'VERIFYING','analytics':'NOT_CONNECTED'}


def write(data):
    path=_path();path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8');tmp.replace(path)


def state(scope):
    data=read()
    if data.get('owner') and data['owner']!=scope: raise ValueError('Este proyecto pertenece a otra sesión autorizada.')
    return {k:v for k,v in data.items() if k!='owner'}|{'readiness':readiness(data),'legal_status':legal_status(data)}


def legal_diagnostic(scope):
    """Owner-only, read-only discovery. Return presence flags, never legal values."""
    state(scope)
    root=_path().parent.parent
    paths=set(_path().parent.glob('*'))
    users=root/'users'
    if users.exists():
        paths.update(users.glob('*/holdings/sites/registry.json'))
        paths.update(users.glob('*/reposnews/*'))
    results=[]
    keys=('controller','address','tax_id','registration','privacy_contact','activity_mode','entity_type','processing_basis','retention','providers_reviewed')
    for path in sorted(paths):
        if not path.is_file() or path.stat().st_size>5_000_000: continue
        try: document=json.loads(path.read_text(encoding='utf-8'))
        except (ValueError,OSError): continue
        def visit(value, context=False):
            if isinstance(value,dict):
                context=context or value.get('domain') in HOSTS or value.get('name')=='ReposNews' or path.parent.name=='reposnews'
                if context and isinstance(value.get('legal'),dict):
                    legal=value['legal']
                    results.append({'source':str(path.relative_to(root)), 'canonical':path==_path(),
                                    'owner_matches':value.get('owner',scope)==scope,
                                    'fields':{k:bool(legal.get(k)) for k in keys},
                                    'reviewed':value.get('legal_reviewed') is True})
                for child in value.values():
                    if isinstance(child,(dict,list)): visit(child,context)
            elif isinstance(value,list):
                for child in value: visit(child,context)
        visit(document)
    return {'status':'DIAGNOSED','files_examined':len(paths),'copies':results,'values_redacted':True,
            'canonical_scope_matches':read().get('owner')==scope}


def initialize(scope):
    with holdings.transaction('reposnews-editorial'):
        data=read()
        if data.get('owner'):
            state(scope)
            data['articles']=[article_defaults(a) for a in data.get('articles',[])]
            data['search_console_status']='VERIFIED · sc-domain:reposnews.com · solana031@gmail.com · 2026-10-13'
            data['search_console_sitemap']='SUBMITTED · https://www.reposnews.com/sitemap.xml · indexing UNKNOWN'
            data.setdefault('legal',{}).setdefault('privacy_contact','zaragente031@gmail.com')
            data.setdefault('adsense_verification',{'account':'OPEN','publisher':'MATCHED','product':'YOUTUBE_INACTIVE','web_enabled':False,'site_status':'WEB_UPGRADE_REQUIRED','checked_at':'2026-10-13','source':'Existing owner dashboard + https://support.google.com/adsense/answer/9247020','submitted':False,'upgrade_form':'PREPARED_NOT_SUBMITTED · https://www.reposnews.com/'})
            if data.get('publisher')=='pub-4119869448727531' and data.get('adsense_verification',{}).get('site_status')=='WEB_UPGRADE_REQUIRED':
                data['adsense_verification'].update(web_enabled=True,site_status='REVIEW_REQUESTED',submitted=True,checked_at='2026-10-13',source='Owner dashboard: site verified and review requested with explicit approval',upgrade_form='COMPLETED')
            candidate_file=Path(__file__).with_name('reposnews_candidates.json')
            if candidate_file.exists(): data.setdefault('next_editorial_candidates',json.loads(candidate_file.read_text(encoding='utf-8')))
            priorities={'astral-sh/ruff':(1,'Continuidad práctica de uv: calidad y formato de código Python.'),'jqlang/jq':(2,'Herramienta transversal para inspeccionar respuestas JSON de APIs.'),'vitejs/vite':(3,'Primeros pasos frontend que complementan la guía de FastAPI.')}
            for candidate in data.get('next_editorial_candidates',[]):
                if candidate['repo'] in priorities: candidate['editorial_priority'],candidate['priority_reason']=priorities[candidate['repo']]
            review_file=Path(__file__).with_name('reposnews_review.json')
            if review_file.exists():
                for review in json.loads(review_file.read_text(encoding='utf-8')):
                    article=next((a for a in data['articles'] if a['id']==review['id']),None)
                    if not article: continue
                    digest=hashlib.sha256((article['body_es']+'\n'+article['body_en']).encode()).hexdigest()
                    if digest!=review['body_digest']: continue # Preserve later human edits; do not certify a different manuscript.
                    if article.get('final_review',{}).get('checked_at')==review['checked_at']: continue
                    article['final_review']=review;article['source_checked_at']=review['checked_at'];article['last_reviewed']=review['checked_at'];article['latest_release']=review['release']
                    article['history']=(article.get('history',[])+[{'at':holdings._now(),'fields':['final_review','source_checked_at','latest_release'],'reason':'Revisión final de fuentes oficiales; 6 enlaces verificados, ES/EN conservados.'}])[-60:]
            write(data);return state(scope)
        from . import sites_company
        row=next((r for r in sites_company._read_registry(scope) if r.get('domain') in HOSTS),None)
        if not row: row=site_projects.create(scope,{'name':'ReposNews','topic':'Repositorios, herramientas y guías verificadas','domain':'www.reposnews.com'})
        site_projects.patch(scope,row['id'],source_kind='REPOSNEWS',state='PREVIEW',languages=['es','en'],canonical=ORIGIN+'/',relative_url='/reposnews-preview/es/',analytics_status='NOT_CONNECTED',content_review_required=True)
        data.update(owner=scope,project_id=row['id'],articles=json.loads(Path(__file__).with_name('reposnews_content.json').read_text(encoding='utf-8')),initialized_at=holdings._now(),domain_status='VERIFYING',legal_reviewed=False,publisher='pub-4119869448727531',adsense_status='ACTION_REQUIRED',domain_note='www configurado en IONOS; verificar certificado y destino real. Raíz pendiente de redirección.')
        data['articles']=[article_defaults(a) for a in data['articles']]
        data['consent']={'analytics':'DISABLED','ads':'DISABLED','cmp':'NOT_CONFIGURED','functional_cookie':'reposnews_lang · 365 days · SameSite=Lax; Secure'}
        write(data)
        return state(scope)


def github(path, params=None):
    with requests.Session() as client:
        client.trust_env=False
        try:
            response=client.get('https://api.github.com/'+path,params=params,headers={'Accept':'application/vnd.github+json','User-Agent':'ReposNews-readonly/1'},timeout=(5,12),allow_redirects=False)
        except requests.RequestException as exc:
            raise ValueError('GitHub no está accesible; no se inventan datos.') from exc
        if response.status_code in (403,429): raise ValueError('GitHub limita temporalmente las consultas. No se reintenta en bucle.')
        if response.status_code!=200: raise ValueError('GitHub no devolvió datos verificables: HTTP '+str(response.status_code))
        return response.json()


def metadata(row):
    return {k:row.get(k) for k in ('full_name','description','html_url','homepage','language','stargazers_count','forks_count','pushed_at','archived','default_branch')}|{'license':(row.get('license') or {}).get('spdx_id'),'checked_at':holdings._now(),'trend':'NOT_MEASURED'}


def operate(scope, op, payload):
    if op=='init': return initialize(scope)
    if op=='legal_diagnostic': return legal_diagnostic(scope)
    with holdings.transaction('reposnews-editorial'):
        state(scope);data=read()
        if not data.get('owner'): raise ValueError('Crea primero el proyecto ReposNews.')
        if op=='dry_run': return publication_plan(data,payload.get('ids'))
        if op=='publish_batch':
            plan=publication_plan(data,payload.get('ids'))
            if payload.get('confirmed') is not True or payload.get('approved_digest')!=plan['digest']:
                raise ValueError('Confirmación explícita del resumen vigente requerida.')
            if not plan['ready_to_publish']: raise ValueError('Completa revisión legal y editorial antes de publicar.')
            if holdings.read(scope).get('global_stop'): raise ValueError('STOP GLOBAL activo.')
            from . import jev_decision
            proposal=jev_decision.proposal(scope,{'source_agent':'SiteBuilderAgent','task':'Publicación conjunta ReposNews ES/EN','action':'publish articles','resources':plan['urls'],'expected_cost':0,'risk':.3,'urgency':.5})
            if proposal['decision']=='REJECT': raise ValueError('JEV rechazó publicación.')
            for a in data['articles']:
                if a['id'] not in plan['ids']: continue
                a.update(published=True,published_at=holdings._now(),state='PUBLISHED',status='PUBLISHED')
                a['published_snapshot']={k:v for k,v in a.items() if k not in {'published_snapshot','history'}}
                a['history']=(a.get('history',[])+[{'at':holdings._now(),'fields':['published','state'],'reason':'Publicación conjunta ES/EN confirmada'}])[-60:]
            jev_decision.decision_state(scope,proposal['id'],'USER_CONFIRMED_EDITORIAL_CHANGE')
            write(data);return state(scope)
        if op=='verify':
            from . import browser_network
            proxy=None
            try:
                browser_network.public_addresses('www.reposnews.com')
                proxy=browser_network.start_proxy()
                with requests.Session() as client:
                    client.trust_env=False
                    client.proxies={'https':'http://127.0.0.1:'+str(proxy.server_address[1])}
                    with client.get(ORIGIN+'/es/',timeout=(5,12),allow_redirects=False,stream=True) as response:
                        raw=bytearray()
                        for chunk in response.iter_content(8192):
                            raw.extend(chunk)
                            if len(raw)>256000: raise ValueError('Respuesta demasiado grande.')
                        content=raw.decode('utf-8')
                        if response.status_code!=200 or len(content)>256000 or '<a class="brand"' not in content or ORIGIN+'/es/' not in content:
                            raise ValueError('HTTPS no sirve todavía la portada ReposNews.')
                data['domain_status']='ACTIVE';data['domain_verified_at']=holdings._now()
            except (OSError,ValueError,UnicodeError,requests.RequestException) as exc:
                raise ValueError('Verificación DNS/HTTPS/portada pendiente.') from exc
            finally:
                if proxy: proxy.shutdown();proxy.server_close()
        elif op=='legal_save':
            keys={'controller':180,'address':500,'tax_id':80,'registration':300,'privacy_contact':180,'activity_mode':30,'entity_type':30,'processing_basis':1500,'retention':1500}
            legal={k:str(payload.get(k,'')).strip()[:limit] for k,limit in keys.items()}
            legal['providers_reviewed']=payload.get('providers_reviewed') is True
            candidate=data|{'legal':legal,'legal_reviewed':payload.get('reviewed') is True}
            missing=legal_status(candidate)['missing_required']
            data['legal']=legal;data['legal_reviewed']=payload.get('reviewed') is True and not missing;data['legal_updated_at']=holdings._now()
            data['legal_save_notice']='Guardado privado. Faltan: '+', '.join(missing) if missing else 'Datos guardados. '+('LEGAL_READY' if data['legal_reviewed'] else 'Pendiente de aprobación del titular.')
        elif op=='discover':
            query=str(payload.get('query') or 'topic:developer-tools archived:false').strip()
            if not query or len(query)>160: raise ValueError('Consulta de hasta 160 caracteres.')
            result=github('search/repositories',{'q':query,'sort':'updated','order':'desc','per_page':8})
            data['candidates']=[metadata(x) for x in result.get('items',[]) if not x.get('private')]
            for candidate in data['candidates']:
                candidate['signals']={'recent_push':candidate.get('pushed_at'),'stars_total':candidate.get('stargazers_count'),'forks_total':candidate.get('forks_count'),'growth':'NOT_MEASURED'}
                candidate['angle']='Qué resuelve, instalación oficial y límites antes de producción'
                candidate['why_interesting']=candidate.get('description') or 'Actividad pública reciente; relevancia editorial pendiente de revisión.'
            data['discovery']={'query':query,'sort':'RECENT_ACTIVITY','growth':'NOT_MEASURED','note':'Actividad reciente observada; no ranking de velocidad de estrellas.','checked_at':holdings._now()}
        elif op=='research':
            repo=str(payload.get('repo') or '')
            if not re.fullmatch(r'[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}',repo): raise ValueError('Repositorio owner/name requerido.')
            row=github('repos/'+repo);current=metadata(row)
            article=next((a for a in data['articles'] if a['repo'].lower()==repo.lower()),None)
            if article:
                previous=article.get('observed',{})
                current['previous_snapshot']=previous
                article['update_available']=any(current.get(k)!=previous.get(k) for k in ('pushed_at','archived','default_branch'))
                article['latest_observation']=current
            data['research']=current|{'sources':['https://github.com/'+repo,'https://github.com/'+repo+'/releases'],'next_stage':'SOURCE_VERIFY','commands_verified':False}
        elif op in {'save','publish','unpublish'}:
            article=next((a for a in data['articles'] if a['id']==payload.get('id')),None)
            if not article: raise ValueError('Artículo no encontrado.')
            if op=='save':
                before=dict(article)
                for key,limit in [('title_es',180),('title_en',180),('summary_es',500),('summary_en',500),('body_es',24000),('body_en',24000)]:
                    value=str(payload.get(key,article[key])).strip()
                    if not value or len(value)>limit: raise ValueError('Campo editorial vacío o demasiado largo.')
                    article[key]=value
                stage=payload.get('state','REVIEW')
                if stage not in STAGES: raise ValueError('Etapa inválida.')
                if stage in {'PUBLISHED','ARCHIVED'}: raise ValueError('Usa publicación o retirada con confirmación separada.')
                article['state']=stage;article['status']=stage;article['updated_at']=holdings._now()
                article['history']=(article.get('history',[])+[{'at':article['updated_at'],'fields':[k for k in ('title_es','title_en','summary_es','summary_en','body_es','body_en','state') if before.get(k)!=article.get(k)],'reason':str(payload.get('reason') or 'Edición de borrador privado')[:500]}])[-60:]
                article['seo']={l:{'title':article['title_'+l],'description':article['summary_'+l],'canonical':article['seo'][l]['canonical']} for l in ('es','en')}
                # Edits stay private until a fresh publication confirmation.
            else:
                if payload.get('confirmed') is not True: raise ValueError('Publicación exige confirmación separada.')
                if holdings.read(scope).get('global_stop'): raise ValueError('STOP GLOBAL activo.')
                if op=='publish':
                    if legal_status(data)['status']!='LEGAL_READY': raise ValueError('Revisión legal pendiente.')
                    if article['state']!='READY' or not article.get('sources') or not all(article.get(k) for k in ('title_es','title_en','body_es','body_en')): raise ValueError('Revisa fuentes y ambas versiones hasta READY.')
                    from . import jev_decision
                    d=jev_decision.proposal(scope,{'source_agent':'SiteBuilderAgent','task':'Publicar artículo ReposNews ES/EN','action':'publish article','resources':['reposnews.com'],'expected_cost':0,'expected_revenue':None,'risk':.3,'urgency':.5})
                    if d['decision']=='REJECT': raise ValueError('JEV rechazó publicación.')
                    article['published']=True;article['published_at']=holdings._now();article['state']='PUBLISHED';article['status']='PUBLISHED'
                    article['published_snapshot']={k:v for k,v in article.items() if k not in {'published_snapshot','history'}}
                    jev_decision.decision_state(scope,d['id'],'USER_CONFIRMED_EDITORIAL_CHANGE')
                else: article['published']=False;article['state']='ARCHIVED';article['status']='ARCHIVED'
                article['history']=(article.get('history',[])+[{'at':holdings._now(),'fields':['published','state'],'reason':'Confirmación explícita: '+op+' ES + EN'}])[-60:]
        elif op=='status': return state(scope)
        else: raise ValueError('Operación ReposNews no admitida.')
        write(data);return state(scope)


def body_html(body):
    out=[];in_code=False;code=[]
    for line in str(body).splitlines():
        if line.startswith('```'):
            if in_code: out.append('<div class="code"><button type="button" data-copy>Copiar / Copy</button><pre><code>'+html.escape('\n'.join(code))+'</code></pre></div>');code=[]
            in_code=not in_code;continue
        if in_code: code.append(line);continue
        if line.startswith('## '):
            heading=line[3:];anchor=re.sub(r'[^a-z0-9]+','-',heading.casefold()).strip('-')
            out.append('<h2 id="'+anchor+'">'+html.escape(heading)+'</h2>')
        elif line.strip(): out.append('<p>'+html.escape(line)+'</p>')
    if in_code: out.append('<pre><code>'+html.escape('\n'.join(code))+'</code></pre>')
    return Markup(''.join(out))


def render(lang='es', slug='', preview=False):
    data=read();all_rows=data.get('articles',[])
    rows=all_rows if preview else [a.get('published_snapshot',a) for a in all_rows if a.get('published')]
    categories=sorted({a['category'] for a in rows})
    article=next((a for a in rows if a['id']==slug),None) if slug else None
    pages={'about','contact','privacy','cookies','legal','repositories','guides','trends'}
    if slug and not article and slug not in pages: abort(404)
    query=str(request.args.get('q',''))[:120].casefold()
    if query: rows=[a for a in rows if query in ' '.join(str(a.get(k,'')) for k in ('repo','category','title_'+lang,'body_'+lang)).casefold()]
    category=str(request.args.get('category',''))[:80]
    if category: rows=[a for a in rows if a['category']==category]
    base='/reposnews-preview/' if preview else '/'
    path=lang+'/'+('repositorios/' if lang=='es' else 'repositories/')+slug if article else lang+'/'+slug
    path=path.rstrip('/')+'/'
    title=article['title_'+lang] if article else {'es':'ReposNews · Repositorios, herramientas y guías','en':'ReposNews · Repositories, tools and guides'}[lang]
    description=article['summary_'+lang] if article else ('Análisis y guías sobre proyectos tecnológicos con fuentes verificadas.' if lang=='es' else 'Project analysis and practical guides backed by official sources.')
    if slug in pages: title={'about':('Sobre ReposNews','About ReposNews'),'contact':('Contacto','Contact'),'privacy':('Privacidad','Privacy'),'cookies':('Cookies','Cookies'),'legal':('Aviso legal','Legal notice'),'repositories':('Repositorios','Repositories'),'guides':('Guías','Guides'),'trends':('Actividad','Activity')}[slug][0 if lang=='es' else 1]+' · ReposNews'
    return render_template('reposnews.html',lang=lang,rows=rows,article=article,body=body_html(article['body_'+lang]) if article else None,slug=slug,preview=preview,base=base,title=title,description=description,origin=ORIGIN,path=path,official_covers={'uv':'uv-official.svg','fastapi':'fastapi-official.png','playwright':'playwright-official.svg'},public_legal=public_legal_profile(data),query=query,category=category,categories=categories,legal_status={'status':legal_status(data)['status']})


def public_legal_profile(data):
    """Public allowlist; private identity and contact fields never reach templates."""
    legal=data.get('legal') or {}
    approved=legal_status(data)['status']=='LEGAL_READY'
    def safe(value):
        text=str(value or '')
        for key in ('address','tax_id','registration','privacy_contact'):
            private=str(legal.get(key) or '').strip()
            if private: text=re.sub(re.escape(private),'',text,flags=re.IGNORECASE)
        text=re.sub(r'\b(?:[0-9]{8}[A-Za-z]|[XYZxyz][0-9]{7}[A-Za-z])\b','',text)
        return text.strip()
    return {'controller':safe(legal.get('controller')) if approved else '',
            'email':'zaragente031@gmail.com',
            'processing_basis':safe(legal.get('processing_basis')) if approved else '',
            'retention':safe(legal.get('retention')) if approved else '',
            'ready':approved}


def media(asset):
    if asset not in {'editorial.css','favicon.svg','home.png','uv.png','playwright.png','fastapi.png','uv-official.svg','fastapi-official.png','playwright-official.svg'}: abort(404)
    response=send_file(Path(__file__).parent/'static'/'reposnews'/asset,max_age=86400)
    response.headers['X-Content-Type-Options']='nosniff'
    return response


def public_dispatch():
    host=request.host.split(':')[0].lower()
    if host not in HOSTS: return None
    if host=='reposnews.com': return redirect(ORIGIN+request.path,code=308)
    path=request.path.strip('/')
    if path.startswith('media/reposnews/'): return media(path.removeprefix('media/reposnews/'))
    if path in {'robots.txt','sitemap.xml','ads.txt'}:
        data=read()
        if path=='robots.txt': return Response('User-agent: *\nAllow: /\nSitemap: '+ORIGIN+'/sitemap.xml\n',mimetype='text/plain')
        if path=='ads.txt':
            if data.get('domain_status')!='ACTIVE': return Response('Domain verification pending',status=404,mimetype='text/plain')
            return Response('google.com, '+data['publisher']+', DIRECT, f08c47fec0942fa0\n',mimetype='text/plain')
        urls=[ORIGIN+'/'+l+'/'+page for l in ['es','en'] for page in ['', 'about/','contact/','privacy/','cookies/','legal/','repositories/','guides/','trends/']]
        urls += [ORIGIN+'/'+l+'/'+('repositorios' if l=='es' else 'repositories')+'/'+a['id']+'/' for a in data.get('articles',[]) if a.get('published') for l in ['es','en']]
        return Response('<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'+''.join('<url><loc>'+html.escape(u)+'</loc></url>' for u in urls)+'</urlset>',mimetype='application/xml')
    if not path:
        lang=request.cookies.get('reposnews_lang')
        if lang not in {'es','en'}: lang=request.accept_languages.best_match(['es','en']) or 'es'
        return redirect('/'+lang+'/',code=302)
    match=re.fullmatch(r'(es|en)(?:/(?:(?:repositorios|repositories)/)?([a-z0-9-]{1,80}))?/?',path)
    if not match: abort(404) # Never exposes ZAR APIs, login, files or private static assets on this host.
    slug=match[2] or ''
    if any(a.get('published') and a['id']==slug for a in read().get('articles',[])):
        canonical='/'+match[1]+'/'+('repositorios/' if match[1]=='es' else 'repositories/')+slug+'/'
        if request.path!=canonical: return redirect(canonical,code=308)
    response=Response(render(match[1],match[2] or ''),mimetype='text/html')
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['Content-Security-Policy']="default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-src 'none'; base-uri 'none'; object-src 'none'"
    return response


def register(app, scope_fn):
    app.add_url_rule('/media/reposnews/<asset>','reposnews_media',media)
    @app.get('/reposnews-preview/<lang>/')
    @app.get('/reposnews-preview/<lang>/<slug>')
    def reposnews_preview(lang,slug=''):
        if lang not in {'es','en'}: abort(404)
        try: state(scope_fn())
        except ValueError: abort(403)
        response=Response(render(lang,slug,True),mimetype='text/html')
        response.headers['X-Robots-Tag']='noindex, nofollow';response.headers['Cache-Control']='private, no-store'
        return response
