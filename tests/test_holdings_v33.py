from pathlib import Path


def test_holdings_lifecycle_and_ledger(monkeypatch, tmp_path):
    monkeypatch.setenv('ZAR_DATA_DIR', str(tmp_path))
    from app import holdings
    scope='test-user'
    assert holdings.read(scope)['companies']['commerce']['state']=='OFF'
    holdings.set_company_state(scope,'commerce','start')
    assert holdings.read(scope)['companies']['commerce']['state']=='RUNNING'
    holdings.set_company_state(scope,'commerce','pause')
    assert holdings.read(scope)['companies']['commerce']['state']=='PAUSED'
    holdings.set_company_state(scope,'commerce','start')
    holdings.set_global_stop(scope,True,'test')
    assert holdings.read(scope)['global_stop'] is True
    assert holdings.read(scope)['companies']['commerce']['state']=='PAUSED'
    holdings.set_global_stop(scope,False)
    a=holdings.add_ledger(scope,'commerce','revenue',100,reference='order-1',verified=True)
    b=holdings.add_ledger(scope,'commerce','revenue',100,reference='order-1',verified=True)
    assert a['id']==b['id']
    st=holdings.public_view(scope)
    assert st['companies']['commerce']['metrics']['revenue_collected']==100
    assert st['companies']['commerce']['metrics']['profit_realized']==100


def test_jev_fallback_is_typed(monkeypatch):
    monkeypatch.delenv('JEV_API_KEY',raising=False)
    monkeypatch.delenv('TYPESAFE_API_KEY',raising=False)
    from app import jev_decision
    r=jev_decision.gate('Preparar demo',{'safe':True},'medium')
    assert isinstance(r['allowed'],bool)
    assert isinstance(r['requires_review'],bool)
    assert r['decision']['fallback'] is True


def test_media_queue_and_plan(monkeypatch, tmp_path):
    monkeypatch.setenv('ZAR_DATA_DIR',str(tmp_path))
    from app import holdings, media_company
    scope='media-user'
    holdings.set_company_state(scope,'media','start')
    task=media_company.queue_story(scope,'un restaurante que cambia de menú cada día',platform='tiktok')
    text=media_company.process_one(scope)
    assert 'preparado' in text.lower()
    d=holdings.read(scope)
    t=next(x for x in d['companies']['media']['queue'] if x['id']==task['id'])
    assert t['status']=='READY_FOR_PRODUCTION'
    assert t['result']['format']=='9:16'
    assert t['result']['aigc'] is True


def test_web_demo_is_shareable_path(monkeypatch, tmp_path):
    monkeypatch.setenv('ZAR_DATA_DIR',str(tmp_path))
    from app import web_agency
    d=web_agency.build_demo('owner',{'name':'Café Prueba','address':'Madrid'},490)
    path=tmp_path/'holdings_public_demos'/d['slug']/'index.html'
    assert path.exists()
    assert 'Café Prueba' in path.read_text(encoding='utf-8')
    assert d['relative_url'].startswith('/holdings/demo/')


def test_commerce_scout_without_purchase(monkeypatch, tmp_path):
    monkeypatch.setenv('ZAR_DATA_DIR',str(tmp_path))
    monkeypatch.delenv('ZAR_SUPPLIER_CATALOG_URL',raising=False)
    from app import commerce_company
    monkeypatch.setattr(commerce_company,'public_search_results',lambda q,limit=10:{'ok':True,'provider':'test','results':[{'title':'Producto mayorista 12,50 €','snippet':'oferta proveedor','url':'https://supplier.invalid/p'}]})
    r=commerce_company.scout('commerce-user','producto prueba',39.90)
    assert r['ok'] and r['purchase_authority'] is False
    assert r['candidates'][0]['cost']==12.50
    assert r['candidates'][0]['margin']['profit']>0


def test_sites_builds_public_assets(monkeypatch, tmp_path):
    monkeypatch.setenv('ZAR_DATA_DIR', str(tmp_path))
    monkeypatch.setenv('GOOGLE_ADSENSE_PUBLISHER_ID', 'ca-pub-1234567890123456')
    from app import sites_company
    monkeypatch.setattr(sites_company, 'public_search_results', lambda q, limit=8: {
        'ok': True, 'provider': 'test', 'results': [
            {'title': 'Fuente útil', 'snippet': 'Información comprobable y útil.', 'url': 'https://example.invalid/a'}
        ]
    })
    site = sites_company.build_site('sites-user', 'ahorrar en la factura de luz', queue_promotion=False)
    root = tmp_path / 'holdings_public_sites' / site['slug']
    assert (root / 'index.html').exists()
    assert (root / 'privacy.html').exists()
    assert (root / 'robots.txt').exists()
    assert (root / 'sitemap.xml').exists()
    assert (root / 'ads.txt').read_text(encoding='utf-8').startswith('google.com, pub-1234567890123456')
    assert site['relative_url'].startswith('/holdings/site/')
    assert site['organic_only'] is True


def test_sites_network_starts_and_queues_first_site(monkeypatch, tmp_path):
    monkeypatch.setenv('ZAR_DATA_DIR', str(tmp_path))
    from app import holdings, sites_company
    d = sites_company.configure_network(
        'network-user', enabled=True, seed_topic='recetas rápidas mediterráneas', max_sites=4,
        auto_deploy_vercel=False, allow_domain_reinvestment=False, auto_domain_purchase=False,
    )
    c = d['companies']['sites']
    assert c['state'] == 'RUNNING'
    assert c['config']['auto_expand'] is True
    assert c['config']['max_sites'] == 4
    task = holdings.next_task('network-user', 'sites')
    assert task and task['kind'] == 'build_site'


def test_sites_domain_reinvestment_never_spends_without_realized_profit(monkeypatch, tmp_path):
    monkeypatch.setenv('ZAR_DATA_DIR', str(tmp_path))
    from app import sites_company
    # No network call is reached: profit gate must stop it first.
    sites_company.configure_policy('budget-user', allow_domain_reinvestment=True, auto_domain_purchase=True, max_domain_eur=20, domain_daily_budget_eur=40)
    result = sites_company.buy_domain('budget-user', 'missing-slug', 'ejemplo.com', 12, confirmed=True)
    assert result['ok'] is False
    assert result['requires_review'] is True
    assert 'beneficio realizado' in result['message'].lower()


def test_holdings_entry_is_visible_in_template():
    template = (Path(__file__).parents[1] / 'app' / 'templates' / 'index.html').read_text(encoding='utf-8')
    assert '.side .workspaceNavItem.holdingsNavBtn' in template
    assert "['holdings','🏢','ZAR Holdings'" in template
    assert 'onclick="showHoldings()"' in template
    assert 'zhActivateSitesNetwork()' in template
