from app import stonks_validation


def test_gate_passes_consistent_shadow_evidence():
    rows=[
        {'symbol':'AAA','ok':True,'return_pct':1,'max_drawdown_pct':-3,'sharpe':0.4},
        {'symbol':'AAA','ok':True,'return_pct':2,'max_drawdown_pct':-5,'sharpe':0.6},
        {'symbol':'AAA','ok':True,'return_pct':-0.5,'max_drawdown_pct':-7,'sharpe':0.2},
    ]
    wf={'symbol':'AAA','summary':{'positive_fold_pct':75,'median_sharpe':0.5,'trades':9}}
    r=stonks_validation.assess_symbol('AAA',rows,wf)
    assert r['meets_shadow_criteria'] is True
    assert r['status']=='MEETS_SHADOW_CRITERIA'


def test_gate_requires_more_evidence_when_oos_is_weak():
    rows=[
        {'symbol':'BBB','ok':True,'return_pct':2,'max_drawdown_pct':-3,'sharpe':0.5},
        {'symbol':'BBB','ok':True,'return_pct':1,'max_drawdown_pct':-4,'sharpe':0.4},
        {'symbol':'BBB','ok':True,'return_pct':1,'max_drawdown_pct':-4,'sharpe':0.3},
    ]
    wf={'symbol':'BBB','summary':{'positive_fold_pct':25,'median_sharpe':-0.2,'trades':4}}
    r=stonks_validation.assess_symbol('BBB',rows,wf)
    assert r['meets_shadow_criteria'] is False
    assert any(not x['passed'] for x in r['checks'])


def test_suite_never_enables_paper():
    rows=[{'symbol':'AAA','ok':True,'return_pct':1,'max_drawdown_pct':-2,'sharpe':0.4} for _ in range(3)]
    wf=[{'symbol':'AAA','summary':{'positive_fold_pct':75,'median_sharpe':0.5,'trades':8}}]
    r=stonks_validation.assess_suite(rows,wf)
    assert r['model']['auto_enable_paper'] is False
    assert r['model']['broker_orders'] is False
