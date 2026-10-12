"""Scoped editorial drafts. Public changes require a separate confirmation."""
import html
import json
import re
import uuid
from . import holdings, site_projects, sites_company, sites_native


def _project(scope, project_id):
    row = site_projects.get(scope, project_id)
    if row.get('source_kind') != 'NATIVE_DEMO':
        raise ValueError('Editor limitado a proyectos nativos; importaciones intactas.')
    return row


def view(scope, project_id):
    row = _project(scope, project_id)
    return {'project_id': row['id'], 'articles': row.get('editorial_articles', []),
            'analytics': 'NOT_CONNECTED', 'revenue': None,
            'publication_requires_confirmation': True,
            'plan': [{'topic': row.get('topic') or row['name'], 'keyword': 'guía práctica',
                      'internal_links': [f for f in row.get('files', []) if f.endswith('.html')],
                      'status': 'SUGGESTION_NOT_PUBLISHED'}]}


def operate(scope, op, data):
    with holdings.transaction(scope):
        row = _project(scope, data['id'])
        root = sites_company._public_root() / row['slug']
        articles = [dict(a) for a in row.get('editorial_articles', [])]
        article_id = str(data.get('article_id') or '')
        if article_id and not re.fullmatch(r'[a-f0-9]{16}', article_id):
            raise ValueError('Artículo inválido.')
        article = next((a for a in articles if a['id'] == article_id), None)
        if op == 'save':
            title = str(data.get('title') or '').strip()[:160]
            body = str(data.get('body') or '').strip()
            if not title or not body or len(body) > 30000:
                raise ValueError('Título y texto requeridos; máximo 30.000 caracteres.')
            if article_id and article is None:
                raise ValueError('Artículo no encontrado en este proyecto.')
            if article is None:
                if len(articles) >= 100: raise ValueError('Máximo 100 artículos por proyecto.')
                article = {'id': uuid.uuid4().hex[:16], 'created_at': holdings._now(), 'state': 'DRAFT'}
                articles.append(article)
            article.update(title=title, body=body, keyword=str(data.get('keyword') or '')[:160],
                           is_test=data.get('is_test') is True, updated_at=holdings._now(), pending_changes=True)
            filename = 'draft-' + article['id'] + '.html'
            content = ''.join('<p>'+html.escape(p)+'</p>' for p in body.split('\n') if p.strip())
            (root / filename).write_text(sites_native.document(row['name'], filename, title, body[:155],
                                       '<article>'+content+'</article>', row['canonical']), encoding='utf-8')
            article['preview_url'] = row['relative_url'] + filename
        elif op in {'publish', 'unpublish'}:
            if data.get('confirmed') is not True: raise ValueError('Confirma el cambio público por separado.')
            if holdings.read(scope).get('global_stop'): raise ValueError('STOP GLOBAL activo.')
            if article is None: raise ValueError('Artículo no encontrado en este proyecto.')
            if row.get('state') != 'PUBLISHED': raise ValueError('Publica primero el sitio mediante confirmación.')
            if op == 'publish' and article.get('is_test'): raise ValueError('Los artículos TEST permanecen privados.')
            from . import jev_decision
            decision = jev_decision.proposal(scope, {'source_agent':'SiteBuilderAgent', 'task':'Cambio editorial público',
                'action':'publish article' if op == 'publish' else 'unpublish article', 'resources':['local_static_host'],
                'expected_cost':0, 'expected_revenue':None, 'risk':.3, 'urgency':.5})
            if decision['decision'] == 'REJECT': raise ValueError('JEV rechazó el cambio público.')
            filename = 'article-' + article['id'] + '.html'
            marker = root / 'published.json'
            manifest = json.loads(marker.read_text(encoding='utf-8'))
            files = list(manifest['files'])
            if op == 'publish':
                content = ''.join('<p>'+html.escape(p)+'</p>' for p in article['body'].split('\n') if p.strip())
                (root / filename).write_text(sites_native.document(row['name'], filename, article['title'],
                    article['body'][:155], '<article>'+content+'</article>', row['canonical'], True), encoding='utf-8')
                if filename not in files: files.append(filename)
                article.update(state='PUBLISHED', public_url=row['relative_url']+filename, pending_changes=False, published_title=article['title'])
            else:
                files = [f for f in files if f != filename]
                article.update(state='DRAFT', public_url=None, pending_changes=True)
            manifest['files'] = files
            temp = marker.with_suffix('.tmp'); temp.write_text(json.dumps(manifest), encoding='utf-8'); temp.replace(marker)
            if op == 'unpublish': (root / filename).unlink(missing_ok=True)
            home = root / 'index.html'
            original = home.read_text(encoding='utf-8')
            original = re.sub(r'<section id="zar-editorial">.*?</section>', '', original, flags=re.S)
            links = ''.join('<p><a href="article-'+a['id']+'.html">'+html.escape(a.get('published_title',a['title']))+'</a></p>'
                            for a in articles if a['state'] == 'PUBLISHED')
            home.write_text(original.replace('</main>', '<section id="zar-editorial"><h2>Artículos</h2>'+links+'</section></main>') if links else original, encoding='utf-8')
            sitemap = '<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            sitemap += ''.join('<url><loc>'+html.escape(row['canonical']+f)+'</loc></url>' for f in files if f.endswith('.html'))+'</urlset>'
            (root / 'sitemap.xml').write_text(sitemap, encoding='utf-8')
            jev_decision.decision_state(scope, decision['id'], 'USER_CONFIRMED_EDITORIAL_CHANGE')
        else: raise ValueError('Operación editorial no admitida.')
        changes={'editorial_articles':articles, 'content_review_required':True}
        if op in {'publish','unpublish'}: changes['files']=files
        site_projects.patch(scope, row['id'], **changes)
        result = view(scope, row['id'])
        if op == 'save': result['saved_article_id'] = article['id']
        return result
