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
STAGES = {'IDEA','RESEARCH','SOURCE_VERIFY','DRAFT_ES','REVIEW','EN_TRANSLATION','SEO','PREVIEW','READY'}


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
    return {k:v for k,v in data.items() if k!='owner'}


def initialize(scope):
    with holdings.transaction('reposnews-editorial'):
        data=read()
        if data.get('owner'):
            state(scope);return state(scope)
        from . import sites_company
        row=next((r for r in sites_company._read_registry(scope) if r.get('domain') in HOSTS),None)
        if not row: row=site_projects.create(scope,{'name':'ReposNews','topic':'Repositorios, herramientas y guías verificadas','domain':'www.reposnews.com'})
        site_projects.patch(scope,row['id'],source_kind='REPOSNEWS',state='PREVIEW',languages=['es','en'],canonical=ORIGIN+'/',relative_url='/reposnews-preview/es/',analytics_status='NOT_CONNECTED',content_review_required=True)
        data.update(owner=scope,project_id=row['id'],articles=json.loads(Path(__file__).with_name('reposnews_content.json').read_text(encoding='utf-8')),initialized_at=holdings._now(),domain_status='VERIFYING',legal_reviewed=False,publisher='pub-4119869448727531',adsense_status='ACTION_REQUIRED',domain_note='www configurado en IONOS; verificar certificado y destino real. Raíz pendiente de redirección.')
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
                        content=response.raw.read(256001).decode('utf-8')
                        if response.status_code!=200 or len(content)>256000 or '<a class="brand"' not in content or ORIGIN+'/es/' not in content:
                            raise ValueError('HTTPS no sirve todavía la portada ReposNews.')
                data['domain_status']='ACTIVE';data['domain_verified_at']=holdings._now()
            except (OSError,ValueError,UnicodeError,requests.RequestException) as exc:
                raise ValueError('Verificación DNS/HTTPS/portada pendiente.') from exc
            finally:
                if proxy: proxy.shutdown();proxy.server_close()
        elif op=='discover':
            query=str(payload.get('query') or 'topic:developer-tools archived:false').strip()
            if not query or len(query)>160: raise ValueError('Consulta de hasta 160 caracteres.')
            result=github('search/repositories',{'q':query,'sort':'updated','order':'desc','per_page':8})
            data['candidates']=[metadata(x) for x in result.get('items',[]) if not x.get('private')]
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
                for key,limit in [('title_es',180),('title_en',180),('body_es',24000),('body_en',24000)]:
                    value=str(payload.get(key,article[key])).strip()
                    if not value or len(value)>limit: raise ValueError('Campo editorial vacío o demasiado largo.')
                    article[key]=value
                stage=payload.get('state','REVIEW')
                if stage not in STAGES: raise ValueError('Etapa inválida.')
                article['state']=stage;article['updated_at']=holdings._now()
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
                    article['published']=True;article['published_at']=holdings._now()
                    jev_decision.decision_state(scope,d['id'],'USER_CONFIRMED_EDITORIAL_CHANGE')
                else: article['published']=False
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
    pages={'about','contact','privacy','cookies','repositories','guides','trends'}
    if slug and not article and slug not in pages: abort(404)
    query=str(request.args.get('q',''))[:120].casefold()
    if query: rows=[a for a in rows if query in ' '.join(str(a.get(k,'')) for k in ('repo','category','title_'+lang,'body_'+lang)).casefold()]
    base='/reposnews-preview/' if preview else '/'
    path=lang+'/'+('repositorios/' if lang=='es' else 'repositories/')+slug if article else lang+'/'+slug
    path=path.rstrip('/')+'/'
    title=article['title_'+lang] if article else {'es':'ReposNews · Repositorios, herramientas y guías','en':'ReposNews · Repositories, tools and guides'}[lang]
    description=article['summary_'+lang] if article else ('Análisis y guías sobre proyectos tecnológicos con fuentes verificadas.' if lang=='es' else 'Project analysis and practical guides backed by official sources.')
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
        urls=[ORIGIN+'/'+l+'/'+page for l in ['es','en'] for page in ['', 'about/','contact/','privacy/','cookies/','repositories/','guides/','trends/']]
        urls += [ORIGIN+'/'+l+'/'+('repositorios' if l=='es' else 'repositories')+'/'+a['id']+'/' for a in data.get('articles',[]) if a.get('published') for l in ['es','en']]
        return Response('<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'+''.join('<url><loc>'+html.escape(u)+'</loc></url>' for u in urls)+'</urlset>',mimetype='application/xml')
    if not path:
        lang=request.cookies.get('reposnews_lang')
        if lang not in {'es','en'}: lang=request.accept_languages.best_match(['es','en']) or 'es'
        return redirect('/'+lang+'/',code=302)
    match=re.fullmatch(r'(es|en)(?:/(?:(?:repositorios|repositories)/)?([a-z0-9-]{1,80}))?/?',path)
    if not match: abort(404) # Never exposes ZAR APIs, login, files or private static assets on this host.
    response=Response(render(match[1],match[2] or ''),mimetype='text/html')
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['Content-Security-Policy']="default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-src 'none'; base-uri 'none'; object-src 'none'"
    return response


def register(app, scope_fn):
    @app.get('/reposnews-preview/<lang>/')
    @app.get('/reposnews-preview/<lang>/<slug>')
    def reposnews_preview(lang,slug=''):
        if lang not in {'es','en'}: abort(404)
        state(scope_fn())
        response=Response(render(lang,slug,True),mimetype='text/html')
        response.headers['X-Robots-Tag']='noindex, nofollow';response.headers['Cache-Control']='private, no-store'
        return response
