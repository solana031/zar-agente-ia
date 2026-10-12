"""RC isolation and accounting regressions. All data is temporary TEST data."""
import json
import pytest
from app import holdings, business_orchestration as control, scoped_media, user_scope


def test_currency_totals_and_test_exclusion(tmp_path, monkeypatch):
    monkeypatch.setenv('ZAR_DATA_DIR', str(tmp_path))
    holdings.add_ledger('TEST', 'sites', 'revenue', 25, currency='EUR', verified=True)
    holdings.add_ledger('TEST', 'sites', 'revenue', 100, currency='USD', verified=True)
    holdings.add_ledger('TEST', 'sites', 'cost', 10, currency='USD', verified=True)
    state = holdings.read('TEST')
    state['ledger'].append(dict(company='sites',kind='revenue',amount=999,currency='EUR',status='collected',test_mode=True))
    holdings.write('TEST',state)
    view = holdings.public_view('TEST')
    assert view['totals']['revenue_collected'] == 25
    assert view['totals']['by_currency']['USD']['profit_realized'] == 90
    assert view['companies']['sites']['metrics']['by_currency']['EUR']['revenue_collected'] == 25
    assert view['companies']['commerce']['metrics']['has_evidence'] is False


def test_settled_spend_still_counts_and_current_limits_are_rechecked():
    now = holdings._now()
    state = holdings._default() if hasattr(holdings,'_default') else {}
    state['treasury_budgets'] = {'sites':dict(currency='EUR',assigned='20',max_action='10',max_day='10',max_month='20')}
    control.ensure(state)['approvals'] = [dict(id='old',business='sites',currency='EUR',total='8',state='SETTLED',approved_at=now)]
    proposal = dict(id='new',business='sites',currency='EUR',total='3',state='APPROVED')
    with pytest.raises(ValueError, match='límites'): control.validate_budget(state,proposal)
    proposal['total']='2';control.validate_budget(state,proposal)
    state['treasury_budgets']['sites']['max_action']='1'
    with pytest.raises(ValueError, match='acción'): control.validate_budget(state,proposal)


@pytest.mark.parametrize('editor',['audio_studio','video_creator'])
def test_legacy_requires_existing_owner_and_paths_are_scoped(tmp_path,monkeypatch,editor):
    monkeypatch.setenv('ZAR_DATA_DIR',str(tmp_path))
    legacy=tmp_path/editor/'projects';legacy.mkdir(parents=True)
    (legacy/'old.json').write_text(json.dumps({'id':'old'}))
    token=user_scope.set_current_user('TEST-alice')
    try:
        assert scoped_media.projects(editor)==[]
        own=scoped_media.file_path(editor,'projects','new.json');own.write_text('{"id":"new"}')
        assert own.is_relative_to(tmp_path/'users'/'TEST-alice')
        user_scope.set_current_user('TEST-bob')
        assert scoped_media.projects(editor)==[]
        assert not scoped_media.file_path(editor,'projects','new.json').exists()
        for name in ['../old.json','..','/secret','C:\\secret']:
            with pytest.raises(ValueError):scoped_media.file_path(editor,'projects',name)
        (tmp_path/'legacy_owner_browser.txt').write_text('TEST-browser')
        assert scoped_media.projects(editor)==[]
        user_scope.set_current_user(user_scope.anonymous_id('TEST-browser'))
        assert scoped_media.projects(editor)==[legacy/'old.json']
        assert scoped_media.file_path(editor,'projects','old.json')==legacy/'old.json'
        assert (legacy/'old.json').exists()
    finally:user_scope.reset_current_user(token)


@pytest.mark.parametrize('editor',['audio_studio','video_creator'])
def test_editors_preserve_projects_but_deny_other_scopes(tmp_path,monkeypatch,editor):
    import importlib
    monkeypatch.setenv('ZAR_DATA_DIR',str(tmp_path))
    module=importlib.import_module('app.'+editor)
    token=user_scope.set_current_user('TEST-owner')
    try:
        project=module.create_project(name='TEST privacy')
        assert any(p['id']==project['id'] for p in module.list_projects())
        user_scope.set_current_user('TEST-other')
        assert module.list_projects()==[]
        if editor=='audio_studio':
            with pytest.raises(ValueError):module._load(project['id'])
        else:assert module.get_project(project['id']) is None
        user_scope.set_current_user('TEST-owner')
        assert any(p['id']==project['id'] for p in module.list_projects())
    finally:user_scope.reset_current_user(token)
