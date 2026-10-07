"""Real Flask routes and final Paper transport, isolated state and mocked broker."""
import os
import shutil
import uuid
from pathlib import Path
from unittest.mock import patch,Mock
from datetime import datetime,timezone
from decimal import Decimal
root=Path(__file__).resolve().parents[1]
temp=root/('zar-api-335-'+uuid.uuid4().hex);temp.mkdir()
try:
 with patch.dict(os.environ,{'ZAR_DATA_DIR':str(temp)},clear=True),patch('threading.Thread.start'):
  from app import main,holdings,business_orchestration as control
  from app import alpaca_configuration
  main.app.config.update(TESTING=True,SECRET_KEY='offline-test')
  client=main.app.test_client()
  with client.session_transaction() as s:s['zar_user_id']='offline-api';s['authenticated']=True
  with patch.object(main,'_user_scope_id',return_value='offline-api'):
   control.mutate('offline-api','deposit',{'currency':'USD','amount':'100','reference':'offline'})
   data={'transaction_id':uuid.uuid4().hex,'amount':'20','currency':'USD','reason':'Offline test','action':'assign','confirmed':True}
   assert client.post('/api/stonks/automaton/capital',json=data).status_code==403
   response=client.get('/api/stonks/automaton/capital');assert response.status_code==200,response.status_code
   headers={'X-ZAR-Business-CSRF':response.json['csrf']}
   def broker(path,**kwargs):return {'status':'ACTIVE','currency':'USD','equity':'1000'} if path=='/v2/account' else []
   with patch.object(alpaca_configuration,'validate_environment'),patch.object(main,'_alpaca_paper_request',side_effect=broker):
    first=client.post('/api/stonks/automaton/capital',json=data,headers=headers)
    second=client.post('/api/stonks/automaton/capital',json=data,headers=headers)
    assert first.status_code==second.status_code==200
    assert first.json['transaction']==second.json['transaction']
    assert Decimal(second.json['capital']['assigned'])==20,second.json
   assert client.post('/api/subagents/view',json={'zoom':2}).status_code==403
   assert client.post('/api/subagents/view',json={'zoom':2,'pan_x':30,'pan_y':40},headers=headers).status_code==200
   assert client.get('/api/subagents/view').json['view']['zoom']==2
   order={'symbol':'AAPL','qty':'1','side':'sell','client_order_id':'owned-exit'}
   state=main._stonks_default();state.update(paused=False,revoked=False,mode='paper',execution_mode='paper_auto',
     engine_last_reconcile=datetime.now(timezone.utc).isoformat(),engine_last_positions=[{'symbol':'AAPL','qty':'1'}],
     position_ledger={'owned':{'exits':[{'client_order_id':'owned-exit'}]}})
   transport=Mock(return_value=Mock(ok=True,json=lambda:{'id':'offline-order'}))
   with main.app.test_request_context('/'),patch.object(main,'_stonks_read',return_value=state),patch.object(alpaca_configuration,'validate_environment'),patch.object(main,'_alpaca_paper_credentials',return_value=('mock-key','mock-secret')),patch.object(main.requests,'post',transport),patch.object(holdings,'transaction',side_effect=AssertionError('Exit must not wait for business lock')):
    assert main._stonks_submit_paper_order(order)['id']=='offline-order'
    state['paused']=True
    try:main._stonks_submit_paper_order(order)
    except RuntimeError:pass
    else:raise AssertionError('Paused exit must remain blocked')
    assert transport.call_count==1
   with main.app.test_request_context('/'),patch.object(main,'_stonks_read',return_value={**state,'paused':False}),patch.object(alpaca_configuration,'validate_environment'),patch.object(main,'_alpaca_paper_request',return_value=[]),patch.object(main,'_stonks_latest_price',return_value=({'p':100},{})),patch.object(main.requests,'post',transport):
    try:main._stonks_submit_paper_order({**order,'side':'buy','client_order_id':'entry'})
    except ValueError as e:assert 'capital' in str(e)
    else:raise AssertionError('Budget increase must be blocked')
    assert transport.call_count==1
  print('PASS real Flask capital/map CSRF + dedup + Paper budget + exit fast-path/pause')
finally:
 assert temp.resolve().is_relative_to(root);shutil.rmtree(temp)
