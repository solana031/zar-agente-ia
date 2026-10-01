import ast
from copy import deepcopy
from datetime import datetime, timezone
import os
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

class FakeManager:
    def __init__(self): self.configures=[]
    def configure(self, **kwargs): self.configures.append(deepcopy(kwargs))
    def status(self, limit=30):
        return {'feeds':{'equities':{'connected':True}},'watchlist':self.configures[-1] if self.configures else {},'latest':[],'zero_tokens':True}

class FakeStream:
    from app.stonks_stream import refresh_snapshot
    refresh_snapshot = staticmethod(refresh_snapshot)
    def __init__(self): self.MANAGER=FakeManager()


def load_stream_plan():
    tree=ast.parse((ROOT/'app/main.py').read_text(encoding='utf-8'))
    nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in {'_stonks_process_owns_engine','_stonks_stream_plan'}]
    ns={'os':os,'datetime':datetime,'timezone':timezone,'stonks_stream':FakeStream(),'_STONKS_ENGINE_OWNER_PID':None}
    exec(compile(ast.Module(body=nodes,type_ignores=[]),'main.py','exec'),ns)
    return ns


def test_non_owner_web_worker_never_configures_streams():
    ns=load_stream_plan(); mgr=ns['stonks_stream'].MANAGER
    state={
        'engine_symbols':['AAPL'], 'stream_watchlist_equities':['MSFT'],
        'stream_watchlist_crypto':['BTC/USD'], 'stream_watchlist_options':[],
        'market_stream_snapshot':{'feeds':{'equities':{'connected':True}},'latest':[{'symbol':'AAPL'}]}
    }
    out=ns['_stonks_stream_plan'](state,activate=False)
    assert mgr.configures==[]
    assert out['served_from_persisted_snapshot'] is True
    assert out['process_owner'] is False
    assert out['latest'][0]['symbol']=='AAPL'


def test_engine_owner_is_only_path_that_configures_streams():
    ns=load_stream_plan(); mgr=ns['stonks_stream'].MANAGER
    state={'engine_symbols':['AAPL'],'stream_watchlist_equities':['MSFT'],'stream_watchlist_crypto':['BTC/USD'],'stream_watchlist_options':[]}
    ns['_STONKS_ENGINE_OWNER_PID']=os.getpid()
    out=ns['_stonks_stream_plan'](state,activate=True)
    assert len(mgr.configures)==1
    assert mgr.configures[0]['equities']==['AAPL','MSFT']
    assert out['process_owner'] is True
