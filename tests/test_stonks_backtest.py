from app import stonks_backtest


def make_bars(n=320, start=100.0):
    bars=[]; px=start
    for i in range(n):
        # Alternating long trend regimes create multiple entries/exits.
        phase=(i//55)%4
        drift=0.45 if phase in (0,3) else -0.32 if phase==1 else 0.18
        o=px
        c=max(5.0, px+drift + ((i%7)-3)*0.04)
        h=max(o,c)+0.8
        l=min(o,c)-0.8
        bars.append({'t':f'2025-01-{(i%28)+1:02d}T00:00:00Z','o':o,'h':h,'l':l,'c':c})
        px=c
    return bars


def test_backtest_is_deterministic_and_paper_only_model():
    bars=make_bars()
    a=stonks_backtest.run_backtest(bars,'trend',10000,1,0.05)
    b=stonks_backtest.run_backtest(bars,'trend',10000,1,0.05)
    assert a['metrics']==b['metrics']
    assert a['model']['lookahead_safe'] is True
    assert a['model']['execution_timing']=='next_open'
    assert a['model']['atr_source']=='prior_closed_bar'
    assert a['model']['live_orders'] is False


def test_risk_parameter_changes_position_size():
    bars=make_bars()
    low=stonks_backtest.run_backtest(bars,'trend',10000,0.5,0.05)
    high=stonks_backtest.run_backtest(bars,'trend',10000,2.0,0.05)
    low_buys=[t for t in low['trades'] if t['side']=='BUY']
    high_buys=[t for t in high['trades'] if t['side']=='BUY']
    assert low_buys and high_buys
    assert high_buys[0]['qty'] > low_buys[0]['qty']


def test_stress_tests_are_present_and_more_slippage_not_better_on_same_trade_path():
    bars=make_bars()
    r=stonks_backtest.run_backtest(bars,'trend',10000,1,0.05)
    assert len(r['stress_tests'])==3
    assert r['stress_tests'][1]['slippage_pct']>=r['stress_tests'][0]['slippage_pct']
    assert r['stress_tests'][2]['slippage_pct']>=r['stress_tests'][1]['slippage_pct']
    assert r['stress_tests'][2]['return_pct'] <= r['stress_tests'][0]['return_pct'] + 1e-9


def test_metrics_include_robustness_fields():
    r=stonks_backtest.run_backtest(make_bars(),'mean_reversion',10000,1,0.05)
    m=r['metrics']
    for key in ('cagr_pct','max_drawdown_pct','expectancy_usd','sharpe','calmar','exposure_pct','avg_bars_held','max_consecutive_losses','benchmark_return_pct','vs_benchmark_pct'):
        assert key in m
    assert isinstance(r['segments'],list)
    assert isinstance(r['diagnostics'],list)
