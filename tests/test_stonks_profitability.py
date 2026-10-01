from datetime import datetime, timezone, timedelta
from app import stonks_profitability as p


def buy_signal(rsi=56, atr=0.5, regime='tendencia_alcista', strategy='trend'):
    return {'signal':'BUY','strategy':strategy,'indicators':{'rsi14':rsi,'atr_pct':atr,'regime':regime}}


def test_good_trend_candidate_passes_without_learning():
    st={}
    r=p.evaluate(st,'AAPL','trend','1Min',buy_signal(),{'sentiment':'neutral','sentiment_score':0},{})
    assert r['ok'] is True
    assert r['quality_score'] >= r['min_quality']
    assert r['risk_authority'] is False and r['live_authority'] is False


def test_extreme_volatility_and_rsi_can_block_entry():
    r=p.evaluate({},'AAPL','trend','1Min',buy_signal(rsi=82,atr=4.2,regime='alta_volatilidad'),{}, {})
    assert r['ok'] is False
    assert r['quality_score'] < r['min_quality']


def test_cooldown_blocks_reentry():
    now=datetime(2026,10,1,15,0,tzinfo=timezone.utc)
    st={'paper_last_entry_at':{'AAPL':(now-timedelta(minutes=3)).isoformat()},'paper_symbol_cooldown_minutes':15}
    r=p.evaluate(st,'AAPL','trend','1Min',buy_signal(),{}, {}, now=now)
    assert r['ok'] is False
    assert any('Cooldown' in x for x in r['reasons'])


def test_daily_entry_cap_blocks_overtrading():
    now=datetime(2026,10,1,15,0,tzinfo=timezone.utc)
    st={'paper_entry_counts':{'2026-10-01':{'AAPL':4}},'paper_max_entries_per_symbol_day':4}
    r=p.evaluate(st,'AAPL','trend','1Min',buy_signal(),{}, {}, now=now)
    assert not r['ok']
    assert any('Límite diario' in x for x in r['reasons'])


def test_learning_only_affects_priority_after_mature_sample():
    learning={'groups':[{'symbol':'AAPL','strategy':'trend','timeframe':'1Min','regime':'tendencia_alcista','trades':30,'can_influence_priority':True,'priority_score':-80}]}
    r=p.evaluate({},'AAPL','trend','1Min',buy_signal(),{},learning)
    assert not r['ok']
    assert r['learning_sample']==30
    assert r['risk_authority'] is False


def test_note_entry_is_bounded_and_counts_today():
    st={}
    for i in range(20):
        p.note_entry(st,'AAPL',datetime(2026,9,1+i,15,0,tzinfo=timezone.utc))
    assert len(st['paper_entry_counts']) <= p.MAX_TRACKED_DAYS
    assert st['paper_quality_stats']['entries_accepted']==20


def test_sell_is_not_treated_as_new_short_entry():
    sig={'signal':'SELL','strategy':'trend','indicators':{'rsi14':65,'atr_pct':0.4,'regime':'tendencia_bajista'}}
    r=p.evaluate({},'AAPL','trend','1Min',sig,{}, {})
    assert not r['ok']
    assert any('solo autoriza BUY' in x for x in r['reasons'])
