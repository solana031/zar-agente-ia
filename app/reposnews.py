"""A small bilingual editorial publication, isolated from the private ZAR host."""
import html
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote
import requests
from flask import abort, redirect, render_template, request, Response
from markupsafe import Markup
from . import holdings, site_projects

ORIGIN = 'https://www.reposnews.com'
HOSTS = {'reposnews.com','www.reposnews.com'}
STAGES = {'IDEA','RESEARCH','DRAFT','SOURCE_VERIFY','DRAFT_ES','REVIEW','EN_TRANSLATION','SEO','PREVIEW','READY','SCHEDULED','PUBLISHED','ARCHIVED'}


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
            'LEGAL':bool(data.get('legal_reviewed')),'COOKIES':True,'NAVIGATION':True,
            'MOBILE':True,'SITEMAP':True,'ROBOTS':True,'ADS.TXT':data.get('domain_status')=='ACTIVE',
            'ORIGINAL_CONTENT':bool(data.get('articles'))}
    return {'checks':checks,'status':'READY_TO_SUBMIT' if all(checks.values()) else 'ACTION_REQUIRED',
            'blockers':[k for k,v in checks.items() if not v],
            'submission':'NOT_SUBMITTED','cmp':'NOT_ACTIVE · Google-certified CMP required before serving ads',
            'analytics':'NOT_CONNECTED','site_in_adsense':'NOT_VERIFIED'}


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
    return {k:v for k,v in data.items() if k!='owner'}|{'readiness':readiness(data)}


def initialize(scope):
    with holdings.transaction('reposnews-editorial'):
        data=read()
        if data.get('owner'):
            state(scope)
            data['articles']=[article_defaults(a) for a in data.get('articles',[])]
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
    with holdings.transaction('reposnews-editorial'):
        state(scope);data=read()
        if not data.get('owner'): raise ValueError('Crea primero el proyecto ReposNews.')
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
            keys={'controller':180,'address':500,'tax_id':80,'registration':300,'privacy_contact':180}
            legal={k:str(payload.get(k,'')).strip()[:limit] for k,limit in keys.items()}
            if payload.get('reviewed') is True and not all(legal.get(k) for k in ('controller','address','tax_id','privacy_contact')):
                raise ValueError('Completa titular, domicilio, identificación fiscal y contacto; revisa su aplicabilidad antes de aprobar.')
            data['legal']=legal;data['legal_reviewed']=payload.get('reviewed') is True;data['legal_updated_at']=holdings._now()
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
                    if article['state']!='READY' or not article.get('sources') or not all(article.get(k) for k in ('title_es','title_en','body_es','body_en')): raise ValueError('Revisa fuentes y ambas versiones hasta READY.')
                    from . import jev_decision
                    d=jev_decision.proposal(scope,{'source_agent':'SiteBuilderAgent','task':'Publicar artículo ReposNews ES/EN','action':'publish article','resources':['reposnews.com'],'expected_cost':0,'expected_revenue':None,'risk':.3,'urgency':.5})
                    if d['decision']=='REJECT': raise ValueError('JEV rechazó publicación.')
                    article['published_snapshot']={k:v for k,v in article.items() if k!='published_snapshot'}
                    article['published']=True;article['published_at']=holdings._now();article['state']='PUBLISHED';article['status']='PUBLISHED'
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
        if line.startswith('## '): out.append('<h2>'+html.escape(line[3:])+'</h2>')
        elif line.strip(): out.append('<p>'+html.escape(line)+'</p>')
    if in_code: out.append('<pre><code>'+html.escape('\n'.join(code))+'</code></pre>')
    return Markup(''.join(out))


def render(lang='es', slug='', preview=False):
    data=read();all_rows=data.get('articles',[])
    rows=all_rows if preview else [a.get('published_snapshot',a) for a in all_rows if a.get('published')]
    article=next((a for a in rows if a['id']==slug),None) if slug else None
    pages={'about','contact','privacy','cookies','legal','repositories','guides','trends'}
    if slug and not article and slug not in pages: abort(404)
    query=str(request.args.get('q',''))[:120].casefold()
    if query: rows=[a for a in rows if query in ' '.join(str(a.get(k,'')) for k in ('repo','category','title_'+lang,'body_'+lang)).casefold()]
    base='/reposnews-preview/' if preview else '/'
    path=lang+'/'+('repositorios/' if lang=='es' else 'repositories/')+slug if article else lang+'/'+slug
    path=path.rstrip('/')+'/'
    title=article['title_'+lang] if article else {'es':'ReposNews · Repositorios, herramientas y guías','en':'ReposNews · Repositories, tools and guides'}[lang]
    description=article['summary_'+lang] if article else ('Análisis y guías sobre proyectos tecnológicos con fuentes verificadas.' if lang=='es' else 'Project analysis and practical guides backed by official sources.')
    if slug in pages: title={'about':('Sobre ReposNews','About ReposNews'),'contact':('Contacto','Contact'),'privacy':('Privacidad','Privacy'),'cookies':('Cookies','Cookies'),'legal':('Aviso legal','Legal notice'),'repositories':('Repositorios','Repositories'),'guides':('Guías','Guides'),'trends':('Actividad','Activity')}[slug][0 if lang=='es' else 1]+' · ReposNews'
    return render_template('reposnews.html',lang=lang,rows=rows,article=article,body=body_html(article['body_'+lang]) if article else None,slug=slug,preview=preview,base=base,title=title,description=description,origin=ORIGIN,path=path,data=data,query=query)


def public_dispatch():
    host=request.host.split(':')[0].lower()
    if host not in HOSTS: return None
    if host=='reposnews.com': return redirect(ORIGIN+request.path,code=308)
    path=request.path.strip('/')
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
    @app.get('/reposnews-preview/<lang>/')
    @app.get('/reposnews-preview/<lang>/<slug>')
    def reposnews_preview(lang,slug=''):
        if lang not in {'es','en'}: abort(404)
        try: state(scope_fn())
        except ValueError: abort(403)
        response=Response(render(lang,slug,True),mimetype='text/html')
        response.headers['X-Robots-Tag']='noindex, nofollow';response.headers['Cache-Control']='private, no-store'
        return response
