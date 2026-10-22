"""One bounded HTTP verification, independent of Railway API/authentication.

Default: GET /health only. Optional smoke sends exactly one free-model request,
only after the required deployment is live and its environment key fingerprint
matches the operator's expected replacement. Never prints credentials or bodies.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request,urlopen


def version_tuple(value):
    if not re.fullmatch(r'\d+\.\d+\.\d+',str(value or '')):return None
    return tuple(int(x) for x in value.split('.'))


def request_json(request,opener):
    try:
        with opener(request,timeout=25) as response:
            # Only parse health. Provider bodies and error bodies never enter reports.
            body=json.load(response) if request.method=='GET' else None
            return response.status,body
    except HTTPError as error:return error.code,None
    except Exception:return None,None


def check(base_url,expected_version,expected_commit=None,smoke=False,key_fingerprint=None,env=None,opener=urlopen):
    parsed=urlsplit(base_url)
    if parsed.scheme!='https' or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in {'','/'}:
        raise ValueError('HTTPS origin without credentials or query required')
    target=version_tuple(expected_version)
    if target is None:raise ValueError('Numeric target version required')
    env=os.environ if env is None else env
    http,health=request_json(Request(base_url.rstrip('/')+'/health',method='GET'),opener)
    health=health if isinstance(health,dict) else {}
    current=version_tuple(health.get('version'))
    commit=health.get('commit') or health.get('commit_sha')
    # Only a valid commit identifier is ever copied from the response.
    commit=commit if isinstance(commit,str) and re.fullmatch(r'[0-9a-fA-F]{7,40}',commit) else None
    ready=http==200 and health.get('ok') is True and current is not None and current>=target
    commit_match=None if not expected_commit or not commit else commit.startswith(expected_commit) or expected_commit.startswith(commit)
    if commit_match is False:ready=False
    result={'health_http':http,'version':'.'.join(map(str,current)) if current else None,'commit':commit,'commit_match':commit_match,
            'required_version':expected_version,'deployment_ready':ready,'openrouter':{'status':'NOT_RUN','requests':0}}
    if not smoke:return result
    provider=result['openrouter']
    if not ready:provider['status']='BLOCKED_DEPLOYMENT';return result
    key=env.get('OPENROUTER_API_KEY','')
    if not key:provider['status']='KEY_UNAVAILABLE';return result
    if not key_fingerprint or not re.fullmatch(r'[0-9a-f]{8,64}',key_fingerprint):
        provider['status']='EXPECTED_REPLACEMENT_FINGERPRINT_REQUIRED';return result
    if not hashlib.sha256(key.encode()).hexdigest().startswith(key_fingerprint):
        provider['status']='REPLACEMENT_NOT_ACTIVE';return result
    payload={'model':'openrouter/free','messages':[{'role':'user','content':'Reply OK.'}],'max_tokens':4,'stream':False}
    request=Request('https://openrouter.ai/api/v1/chat/completions',data=json.dumps(payload).encode(),
                    headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'},method='POST')
    status,_=request_json(request,opener)
    provider.update(http=status,requests=1,status='OK' if status is not None and 200<=status<300 else 'HTTP_ERROR' if status else 'UNKNOWN_NO_RETRY')
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url',default='https://web-production-a9565.up.railway.app')
    parser.add_argument('--expected-version',required=True)
    parser.add_argument('--expected-commit')
    parser.add_argument('--openrouter-smoke',action='store_true')
    parser.add_argument('--expected-key-fingerprint')
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    report=check(args.base_url,args.expected_version,args.expected_commit,args.openrouter_smoke,args.expected_key_fingerprint)
    rendered=json.dumps(report,indent=2)
    if args.output:args.output.write_text(rendered+'\n',encoding='utf-8')
    print(rendered)
    return 0 if report['deployment_ready'] and (not args.openrouter_smoke or report['openrouter']['status']=='OK') else 2


if __name__=='__main__':raise SystemExit(main())
