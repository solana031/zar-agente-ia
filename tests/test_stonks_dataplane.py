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


def test_cache_is_bounded_and_expired_buckets_are_removed():
    from unittest.mock import patch
    dp=stonks_dataplane.ZeroTokenDataPlane()
    with patch.object(stonks_dataplane.time, 'monotonic', return_value=10):
        for i in range(dp.MAX_CACHE+20):
            dp._cached('u','signal',i,60,lambda: {'signal':'BUY'})
    assert len(dp._cache)==dp.MAX_CACHE
    with patch.object(stonks_dataplane.time, 'monotonic', return_value=71):
        dp._cached('u','signal','next',60,lambda: {})
    assert len(dp._cache)==1


def test_concurrent_cache_misses_load_once():
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    dp=stonks_dataplane.ZeroTokenDataPlane()
    entered, release=Event(), Event()
    calls=[]
    def loader():
        calls.append(1); entered.set()
        assert release.wait(2)
        return {'value': 1}
    with ThreadPoolExecutor(max_workers=2) as pool:
        a=pool.submit(dp._cached,'u','signal','key',60,loader)
        assert entered.wait(2)
        b=pool.submit(dp._cached,'u','signal','key',60,loader)
        release.set()
        assert a.result()[0]==b.result()[0]
    assert len(calls)==1


def test_identical_cached_event_is_not_counted_every_cycle():
    dp=stonks_dataplane.ZeroTokenDataPlane()
    signal={'signal':'BUY','bar_time':'2026-10-01T10:00:00Z'}
    news={'sentiment':'bullish','sentiment_score':54,'fetched_at':'x'}
    assert dp.route_event('u','AAPL',signal,news)['significant']
    repeated=dp.route_event('u','AAPL',signal,news)
    assert not repeated['significant'] and not repeated['ai_candidate']
    assert dp.status('u')['significant_events']==1


def test_runtime_maps_are_bounded():
    dp=stonks_dataplane.ZeroTokenDataPlane()
    for i in range(dp.MAX_SCOPES+2): dp.begin_cycle(str(i))
    assert len(dp._runtime)==dp.MAX_SCOPES
    for i in range(dp.MAX_SYMBOLS+2): dp.route_event('u',str(i))
    assert len(dp._scope('u')['last_signal_signatures'])==dp.MAX_SYMBOLS


def test_provider_specific_ai_telemetry_is_explicit():
    dp=stonks_dataplane.PLANE
    dp.begin_cycle('meter')
    dp.record_ai_call('meter','gpt-5',estimated_cost_usd=0.0123)
    dp.record_ai_call('meter','gemini-3')
    dp.record_ai_call('meter','ollama',local=True)
    status=dp.status('meter')
    assert status['gpt_calls']==1
    assert status['gemini_calls']==1
    assert status['local_model_calls']==1
    assert status['ai_calls']==2
    assert status['estimated_ai_cost_usd']==0.0123
