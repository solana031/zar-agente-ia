"""Real Flask OAuth/state and Identity workflows with workers off and no network."""
import os,shutil,uuid
from pathlib import Path
from urllib.parse import urlparse,parse_qs
from unittest.mock import patch
root=Path(__file__).resolve().parents[1];temp=root/('zar-api-336-'+uuid.uuid4().hex);temp.mkdir()
try:
 with patch.dict(os.environ,{'ZAR_DATA_DIR':str(temp)},clear=True),patch('threading.Thread.start'):
  from app import main,cloud_auth
  main.app.config.update(TESTING=True,SECRET_KEY='offline-test')
  client=main.app.test_client()
  with client.session_transaction() as s:s['zar_user_id']='offline-api-336'
  path='/api/holdings/workflows/identity_center_register'
  assert client.post(path,json={'email':'zar.offline@gmail.com'}).status_code==403
  wf=client.get('/api/holdings/workflows');assert wf.status_code==200
  headers={'X-ZAR-Business-CSRF':wf.json['csrf']}
  response=client.post(path,json={'email':'zar.offline@gmail.com'},headers=headers)
  assert response.status_code==200 and response.json['result']['status']=='NEEDS_OAUTH'
  with patch.object(cloud_auth,'_oauth_client',return_value=('offline-client','offline-secret')):
   r=client.get('/connect/google?purpose=zar&force=1&service=core&email=zar.offline%40gmail.com')
   assert r.status_code==302,r.status_code
   params=parse_qs(urlparse(r.headers['Location']).query)
   assert 'youtube.upload' not in params['scope'][0]
   pending=main._load_oauth_pending('google',params['state'][0])
   assert pending['expected_email']=='zar.offline@gmail.com' and pending['purpose']=='zar'
  with patch.object(main,'finish_oauth',side_effect=AssertionError('Invalid callback must not exchange tokens')):
   assert client.get('/oauth2callback?state=invalid&code=offline').status_code==400
  assert client.get('/connect/google?purpose=zar&service=unknown&email=zar.offline%40gmail.com').status_code==400
  assert client.get('/health').json['version']=='33.3.6'
  print('PASS real Flask Identity CSRF, OAuth PKCE/pending email, invalid callback and 33.3.6')
finally:
 assert temp.resolve().is_relative_to(root);shutil.rmtree(temp)
