import ast
from datetime import datetime, timezone
import json, os, uuid
from pathlib import Path
import tempfile
from app import stonks_learning

ROOT=Path(__file__).resolve().parents[1]


def closed_record(cid='c1'):
    return {
        'client_order_id':cid,'closed':True,'symbol':'AAPL','side':'buy','strategy':'trend','timeframe':'1Min',
        'submitted_at':'2026-10-01T13:30:00+00:00',
        'entry_fill':{'qty':'1','price':100,'filled_at':'2026-10-01T13:30:00+00:00'},
        'decision_context':{'signal':'BUY','regime':'trend','asset_class':'us_equity','indicators':{},'news_sources':[]},
        'learning_result':{'complete':True,'qty':'1','exit_price':101,'realized_pnl':1,'return_pct':1,'duration_s':60,'closed_at':'2026-10-01T13:31:00+00:00','exit_reason':'TP'}
    }


def namespace(directory):
    tree=ast.parse((ROOT/'app/main.py').read_text(encoding='utf-8'))
    wanted={'_stonks_atomic_json','_stonks_learning_file','_stonks_learning_read','_stonks_learning_write','_stonks_learning_update_state'}
    nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in wanted]
    ns={'Path':Path,'os':os,'json':json,'uuid':uuid,'datetime':datetime,'timezone':timezone,
        '_STONKS_DIR':Path(directory),'_user_scope_id':lambda:'owner','stonks_learning':stonks_learning}
    exec(compile(ast.Module(body=nodes,type_ignores=[]),'main.py','exec'),ns)
    return ns


def test_learning_journal_is_separate_persistent_and_idempotent():
    with tempfile.TemporaryDirectory() as td:
        ns=namespace(td)
        state={'position_ledger':{'c1':closed_record()},'paper_learning_enabled':True}
        out=ns['_stonks_learning_update_state'](state)
        assert len(out['added'])==1
        assert 'paper_learning_journal' not in state
        assert state['paper_learning_journal_count']==1
        path=Path(td)/'owner_paper_learning.json'
        assert path.exists()
        disk=json.loads(path.read_text())
        assert len(disk['journal'])==1 and disk['risk_authority'] is False and disk['live_authority'] is False
        # Simulate a process restart: same persistent file, no duplicate journal row.
        ns2=namespace(td)
        state2={'position_ledger':{'c1':closed_record()},'paper_learning_enabled':True}
        out2=ns2['_stonks_learning_update_state'](state2)
        assert out2['added']==[]
        assert state2['paper_learning_journal_count']==1
        assert len(ns2['_stonks_learning_read']()['journal'])==1
