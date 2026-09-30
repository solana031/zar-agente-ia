from app import stonks_agents


def test_architecture_is_token_free_and_complete():
    d = stonks_agents.describe()
    assert d['architecture'] == 'deterministic_multi_agent'
    assert d['token_cost_router'] == 0
    ids = {a['id'] for a in d['agents']}
    assert {'supervisor','market_data','analysis','risk','paper_execution','position_manager'} <= ids


def test_risk_precheck_fail_closed():
    ok, trace = stonks_agents.SUPERVISOR.risk.precheck({
        'revoked': True, 'paused': True, 'mode': 'paper', 'execution_mode': 'paper_auto',
        'autonomous_engine': True, 'position_lifecycle_enabled': True,
    }, {'is_open': True})
    assert not ok
    assert trace['status'] == 'blocked'


def test_risk_precheck_passes_safe_operating_state():
    ok, trace = stonks_agents.SUPERVISOR.risk.precheck({
        'revoked': False, 'paused': False, 'mode': 'paper', 'execution_mode': 'paper_auto',
        'autonomous_engine': True, 'position_lifecycle_enabled': True,
    }, {'is_open': True})
    assert ok
    assert trace['status'] == 'pass'
