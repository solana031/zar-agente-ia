from app import stonks_agents, stonks_selftest


def base_state():
    return {'mode':'paper','execution_mode':'shadow','autonomous_engine':True,'position_lifecycle_enabled':False,'shadow_log':[{'order_created':False}]}


def test_selftest_passes_safe_shadow_architecture():
    r=stonks_selftest.run(base_state(),stonks_agents.describe(),{'architecture':'zero_token_data_plane','ai_gate_enabled':False})
    assert r['ok'] is True
    assert r['token_cost']==0
    assert r['orders_created']==0


def test_selftest_fails_if_shadow_created_order():
    st=base_state();st['shadow_log']=[{'order_created':True}]
    r=stonks_selftest.run(st,stonks_agents.describe(),{'architecture':'zero_token_data_plane','ai_gate_enabled':False})
    assert r['ok'] is False
    assert any(x['id']=='shadow_no_orders' and not x['ok'] for x in r['checks'])
