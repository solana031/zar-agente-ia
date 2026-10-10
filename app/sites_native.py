"""Native, original static demo; no provider calls, adverts or fabricated metrics."""
import html
import json
import re
from pathlib import Path
from . import holdings, site_projects, sites_company
from . import jev_decision

ARTICLES = [
    ('ordenar-archivos', 'Ordenar archivos sin perder información', [
        ('Empieza por una carpeta de entrada', 'Reúne los documentos pendientes en una carpeta temporal. Conserva los originales y evita cambiar su nombre hasta saber para qué sirven. Dedica diez minutos a separar trabajo, administración y material personal.'),
        ('Usa nombres que puedas buscar', 'Un nombre como 2026-10_proyecto_resumen facilita reconocer fecha y contenido. Utiliza un criterio consistente, sin incluir contraseñas ni datos sensibles en nombres compartidos. Añade etiquetas cuando un documento pertenezca a varios temas.'),
        ('Comprueba antes de eliminar', 'Compara contenido, tamaño y fecha antes de decidir que dos archivos son duplicados. Mueve los candidatos a una carpeta de revisión. Mantén una copia de seguridad y verifica que puedes recuperar un archivo antes de hacer limpieza definitiva.')]),
    ('planificar-semana', 'Planificar una semana con menos interrupciones', [
        ('Elige tres resultados', 'Anota tres resultados concretos que importen esta semana. Un resultado describe algo terminado, por ejemplo un borrador revisado, en lugar de una actividad indefinida. Divide cada resultado en una siguiente acción pequeña.'),
        ('Reserva bloques realistas', 'Coloca las acciones en el calendario dejando margen para imprevistos. Agrupa las tareas breves que requieren herramientas parecidas. Los bloques son una hipótesis: ajusta su duración según lo que observes durante la semana.'),
        ('Cierra el ciclo', 'Al final del día registra qué quedó terminado y qué te bloqueó. Reubica conscientemente lo pendiente en lugar de acumularlo. El viernes revisa si tus prioridades reflejaban tus necesidades y cambia una sola cosa para la semana siguiente.')]),
    ('notas-utiles', 'Convertir notas dispersas en decisiones útiles', [
        ('Separa hechos y propuestas', 'En cada nota distingue lo observado de lo que propones hacer. Anota fecha y fuente cuando sea relevante. Una cifra sin contexto puede confundir; conserva la referencia al documento que la respalda.'),
        ('Escribe una siguiente acción', 'Termina la nota con una acción, una persona responsable o una pregunta abierta. Si todavía no puedes decidir, escribe qué información falta. Mantén un pequeño índice de temas para encontrar notas relacionadas.'),
        ('Revisa y archiva', 'Programa una revisión breve de las notas activas. Enlaza las conclusiones a sus fuentes y conserva versiones cuando cambien decisiones. Archiva lo resuelto sin borrar el historial; no todas las notas necesitan convertirse en tareas.')])]

STYLE = '''*{box-sizing:border-box}body{margin:0;background:#10100f;color:#eee7dc;font:17px/1.75 system-ui,sans-serif}a{color:#e0bf84;overflow-wrap:anywhere}.wrap{max-width:1060px;margin:auto;padding:24px}nav{display:flex;flex-wrap:wrap;gap:16px;border-bottom:1px solid #443628;padding-bottom:16px}header{padding:44px 0 24px}h1{font-size:clamp(32px,6vw,60px);line-height:1.13;letter-spacing:-.035em}h2{line-height:1.3}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,270px),1fr));gap:18px}.card,article section{background:#191714;border:1px solid #443628;border-radius:16px;padding:22px}article{max-width:780px}article section{margin:16px 0}footer{margin-top:40px;padding-top:20px;border-top:1px solid #443628;color:#b8aea1}svg{width:100%;max-height:160px}small{color:#b8aea1}button{font:inherit}'''

def plan(data):
    return {'engine':'ZAR NATIVE','state':'READY','topic':str(data.get('topic') or 'Productividad digital')[:1000],
            'language':str(data.get('language') or 'es')[:30], 'country':str(data.get('country') or 'ES')[:40],
            'audience':str(data.get('audience') or 'Personas que quieren organizar su trabajo digital')[:300],
            'pages':['index.html',*[slug+'.html' for slug,_,_ in ARTICLES],'about.html','contact.html','privacy.html'],
            'seo_plan':['Un H1 por página','Metadatos únicos','Enlaces internos','Sitemap','Datos estructurados'],
            'monetization_plan':{'status':'ACTION_REQUIRED','steps':['Revisar y ampliar contenido','Completar datos de contacto y privacidad','Obtener aprobación de AdSense'],'automatic_revenue':False},
            'content_mode':'ORIGINAL_DEMO_ES','note':'Demo editorial original en español; no es investigación de nicho ni contenido generado por IA.'}

def document(name, filename, title, description, body, base, published=False):
    esc=html.escape
    canonical=base+filename
    schema=json.dumps({'@context':'https://schema.org','@type':'WebPage','name':title,'url':canonical},ensure_ascii=False).replace('<','\\u003c')
    return f'''<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{esc(title)} · {esc(name)}</title><meta name="description" content="{esc(description,quote=True)}"><meta name="robots" content="{'index,follow' if published else 'noindex,nofollow'}"><link rel="canonical" href="{esc(canonical,quote=True)}"><meta property="og:title" content="{esc(title,quote=True)}"><meta property="og:description" content="{esc(description,quote=True)}"><meta property="og:url" content="{esc(canonical,quote=True)}"><meta property="og:type" content="website"><meta name="twitter:card" content="summary"><script type="application/ld+json">{schema}</script><style>{STYLE}</style></head><body><div class="wrap"><nav aria-label="Navegación"><a href="./">{esc(name)}</a><a href="about.html">Acerca de</a><a href="contact.html">Contacto</a><a href="privacy.html">Privacidad · revisión pendiente</a></nav><main><header><small>GUÍAS PRÁCTICAS · DEMO EDITORIAL</small><h1>{esc(title)}</h1><p>{esc(description)}</p></header>{body}</main><footer>Contenido original de demostración · sin anuncios activos · <a href="./">Inicio</a></footer></div></body></html>'''

def build_demo(scope, data, base_url):
    # Always creates a separate project; never overwrites imported/user content.
    config=plan(data)
    row=site_projects.create(scope,{'name':str(data.get('name') or 'Guías de productividad digital')[:120],'topic':config['topic']})
    base=base_url.rstrip('/')+'/holdings/site/'+row['slug']+'/'
    root=sites_company._public_root()/row['slug'];root.mkdir(parents=True,exist_ok=True)
    name=row['name'];esc=html.escape
    cards=''.join(f'<article class="card"><h2><a href="{slug}.html">{esc(title)}</a></h2><p>{esc(parts[0][1][:160])}…</p></article>' for slug,title,parts in ARTICLES)
    illustration='<svg role="img" aria-label="Ilustración original: tres bloques de trabajo organizado" viewBox="0 0 600 140"><rect x="10" y="20" width="170" height="100" rx="16" fill="#785c36"/><rect x="215" y="20" width="170" height="100" rx="16" fill="#a78b58"/><rect x="420" y="20" width="170" height="100" rx="16" fill="#d8be8a"/></svg>'
    docs={'index.html':('Productividad digital, paso a paso','Guías breves para organizar archivos, planificar tu semana y convertir notas en acciones.',illustration+'<section class="grid">'+cards+'</section>'),
          'about.html':('Acerca de este proyecto','Un sitio pequeño para probar un flujo editorial y de publicación real.','<article><p>Esta web es una demostración de ZAR Sites. Sus guías han sido redactadas para este proyecto y proponen hábitos prácticos, sin prometer resultados medibles ni presentar estadísticas inventadas.</p><p>El operador debe revisar el contenido, completar su identidad y ampliar la cobertura antes de solicitar monetización.</p></article>'),
          'contact.html':('Contacto','Información de contacto del proyecto.','<article><p>Contacto operativo: <a href="mailto:zaragente031@gmail.com">zaragente031@gmail.com</a>.</p><p>No incluyas información confidencial en consultas. Este sitio no incorpora un formulario ni almacena mensajes.</p></article>'),
          'privacy.html':('Privacidad · borrador para revisión','Documento pendiente de revisión humana; no constituye asesoramiento jurídico.','<article><h2>Servicios activos en esta demo</h2><p>No se han añadido anuncios, analítica, formularios ni cookies publicitarias. El hosting puede tratar registros técnicos de solicitudes.</p><h2>Antes de monetizar</h2><p>ACTION_REQUIRED: identificar al responsable, revisar finalidades y bases aplicables, proveedores, conservación, derechos y contacto. Si se activan anuncios o cookies, evaluar e implementar el consentimiento correspondiente antes de cargar esos servicios.</p><p>Este borrador no es una política legal definitiva.</p></article>')}
    for slug,title,parts in ARTICLES:
        docs[slug+'.html']=(title,parts[0][1][:155],'<article>'+''.join(f'<section><h2>{esc(h)}</h2><p>{esc(t)}</p></section>' for h,t in parts)+'<p><a href="./">Ver las demás guías</a></p></article>')
    for filename,(title,description,body) in docs.items():
        (root/filename).write_text(document(name,filename,title,description,body,base),encoding='utf-8')
    (root/'sitemap.xml').write_text('<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'+''.join('<url><loc>'+esc(base+f)+'</loc></url>' for f in docs)+'</urlset>',encoding='utf-8')
    (root/'robots.txt').write_text('User-agent: *\nDisallow: /holdings/site/'+row['slug']+'/\nSitemap: '+base+'sitemap.xml\n',encoding='utf-8')
    row=site_projects.patch(scope,row['id'],source_kind='NATIVE_DEMO',state='PREVIEW',relative_url='/holdings/site/'+row['slug']+'/',canonical=base,files=[*docs,'robots.txt','sitemap.xml'],plan=config,adsense_status='ACTION_REQUIRED',ad_slots={'header':None,'in_article':None,'sidebar':None,'footer':None,'auto_ads':None},metrics=None,content_review_required=True)
    return {'project':row,'readiness':readiness(scope,row['id'])}

def readiness(scope, project_id):
    row=site_projects.get(scope,project_id);root=sites_company._public_root()/row['slug']
    checks={'home':(root/'index.html').exists(),'articles':len([f for f in row.get('files',[]) if f.endswith('.html') and f not in {'index.html','about.html','contact.html','privacy.html'}])>=3,
            'about':(root/'about.html').exists(),'contact':(root/'contact.html').exists(),'privacy_reviewed':row.get('privacy_reviewed') is True,
            'content_reviewed':row.get('content_review_required') is False,'sitemap':(root/'sitemap.xml').exists(),'robots':(root/'robots.txt').exists(),
            'published':row.get('state')=='PUBLISHED','https_url':str(row.get('canonical','')).startswith('https://'),'publisher_id':bool(re.fullmatch(r'pub-\d{16}',sites_company._publisher_id()))}
    return {'status':'READY_FOR_REVIEW' if all(checks.values()) else 'ACTION_REQUIRED','checks':checks,'last_checked':holdings._now(),
            'blockers':[k for k,v in checks.items() if not v],'approval_guaranteed':False,'content_sufficiency':'HUMAN_REVIEW_REQUIRED','note':'Checklist técnico; no demuestra elegibilidad ni aprobación de Google. ads.txt exige publisher ID real y despliegue en la raíz del dominio.'}

def publish(scope, project_id, confirmed=False):
    if confirmed is not True: raise ValueError('Confirma publicación de esta demo en la URL pública de ZAR.')
    if holdings.read(scope).get('global_stop'): raise ValueError('STOP GLOBAL activo.')
    decision=jev_decision.proposal(scope,{'source_agent':'SiteBuilderAgent','task':'Publicar demo editorial','action':'publish native site','resources':['local_static_host'],'expected_cost':0,'expected_revenue':None,'risk':.3,'urgency':.5})
    if decision['decision']=='REJECT': raise ValueError('JEV rechazó publicación.')
    row=site_projects.get(scope,project_id)
    if row.get('source_kind')!='NATIVE_DEMO': raise ValueError('Publicación nativa limitada a demos originales; importaciones conservadas.')
    root=sites_company._public_root()/row['slug']
    for f in row['files']:
        if f.endswith('.html'):
            path=root/f;path.write_text(path.read_text(encoding='utf-8').replace('content="noindex,nofollow"','content="index,follow"'),encoding='utf-8')
    (root/'robots.txt').write_text('User-agent: *\nAllow: /\nSitemap: '+row['canonical']+'sitemap.xml\n',encoding='utf-8')
    result=site_projects.patch(scope,project_id,state='PUBLISHED',published_at=holdings._now(),deployment={'provider':'RAILWAY_EXISTING','url':row['canonical'],'status':'PUBLISHED','source':'native_static_files'},content_review_required=True)
    jev_decision.decision_state(scope,decision['id'],'USER_CONFIRMED_NATIVE_PUBLICATION')
    return result
