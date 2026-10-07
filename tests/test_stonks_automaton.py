from app import stonks_automaton


def test_start_pause_stop_and_metrics_delta():
    state={
        'paper_learning': {'overall': {'trades': 10, 'wins': 6, 'losses': 4, 'realized_pnl': 2.5}},
    }
    auto=stonks_automaton.start(state)
    assert auto['state']=='STARTING'
    assert auto['last_heartbeat'] is None
    auto=stonks_automaton.heartbeat(state)
    assert auto['state']=='ACTIVE'
    assert auto['baseline_trades']==10
    state['paper_learning']={'overall': {'trades': 12, 'wins': 7, 'losses': 5, 'realized_pnl': 3.1}, 'groups': []}
    stonks_automaton.complete_cycle(state, action='AAPL: esperar', learning=state['paper_learning'])
    auto=state['automaton']
    assert auto['cycles']==1
    assert auto['trades']==2
    assert auto['wins']==1
    assert auto['losses']==1
    assert auto['win_rate']==50.0
    assert round(auto['pnl_usd'], 2)==0.6
    stonks_automaton.pause(state)
    assert state['automaton']['state']=='PAUSED'
    stonks_automaton.stop(state)
    assert state['automaton']['state']=='OFF'
