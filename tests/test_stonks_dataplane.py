from app import stonks_dataplane


def setup_function(_):
    stonks_dataplane.PLANE.reset_runtime()


def test_cycle_is_zero_token_by_default():
    dp=stonks_dataplane.PLANE
    dp.begin_cycle('u1')
    dp.begin_cycle('u1')
    s=dp.status('u1')
    assert s['cycles_total']==2
    assert s['zero_token_cycles']==2
    assert s['ai_calls']==0
    assert s['llm_calls_avoided_estimate']==2


def test_signal_cache_avoids_duplicate_loader_calls():
    dp=stonks_dataplane.PLANE
    calls=[]
    def loader():
        calls.append(1)
        return {'signal':'HOLD','bar_time':'2026-10-01T10:00:00Z','indicators':{'regime':'lateral'}}
    a,meta1=dp.signal('u','AAPL','trend','1Min',False,loader)
    b,meta2=dp.signal('u','AAPL','trend','1Min',False,loader)
    assert a==b
    assert len(calls)==1
    assert meta1['cached'] is False
    assert meta2['cached'] is True


def test_news_cache_avoids_duplicate_fetch():
    dp=stonks_dataplane.PLANE
    calls=[]
    def loader():
        calls.append(1)
        return {'sentiment':'neutral','sentiment_score':0,'fetched_at':'x'}
    dp.news('u','AAPL',loader,ttl=300)
    _,meta=dp.news('u','AAPL',loader,ttl=300)
    assert len(calls)==1
    assert meta['cached'] is True


def test_event_router_never_calls_model_and_marks_candidate():
    dp=stonks_dataplane.PLANE
    ev=dp.route_event('u','AAPL',
        {'signal':'BUY','bar_time':'2026-10-01T10:00:00Z','indicators':{'regime':'trend'}},
        {'sentiment':'bullish','sentiment_score':54,'fetched_at':'x'})
    assert ev['significant'] is True
    assert ev['ai_candidate'] is True
    assert ev['model_called'] is False
    s=dp.status('u')
    assert s['ai_candidates']==1
    assert s['ai_calls']==0


def test_api_ai_call_removes_zero_token_credit_for_current_cycle():
    dp=stonks_dataplane.PLANE
    dp.begin_cycle('u')
    dp.record_ai_call('u','openai')
    s=dp.status('u')
    assert s['cycles_total']==1
    assert s['zero_token_cycles']==0
    assert s['ai_calls']==1

def test_hydrate_preserves_accumulated_telemetry():
    dp=stonks_dataplane.PLANE
    dp.hydrate('u', {'cycles_total':40,'zero_token_cycles':39,'ai_calls':1,'signal_cache_hits':10,'signal_cache_misses':2})
    dp.begin_cycle('u')
    s=dp.status('u')
    assert s['cycles_total']==41
    assert s['zero_token_cycles']==40
    assert s['ai_calls']==1
    assert s['signal_cache_hits']==10
