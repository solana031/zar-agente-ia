"""Public-news and sentiment specialist for ZAR Stonks.

Only public web information is queried. The agent has no order authority and never
uses private/non-public information. A short cache prevents the 5-second Paper
engine loop from repeatedly hitting search providers.
"""
from datetime import datetime, timezone
import re
import threading
import time

from .web_search import public_search_results

_CACHE = {}
_LOCK = threading.RLock()
_TTL = 300

_POS = {
    'beat','beats','upgrade','upgraded','growth','record','surge','surges','rally','rallies',
    'profit','profits','strong','bullish','approval','approved','partnership','launch','wins','win',
    'sube','subida','beneficio','beneficios','crecimiento','récord','alcista','aprobación','acuerdo'
}
_NEG = {
    'miss','misses','downgrade','downgraded','drop','drops','fall','falls','loss','losses','weak',
    'bearish','lawsuit','probe','investigation','recall','fraud','warning','cuts','cut','layoffs',
    'baja','caída','pérdida','pérdidas','bajista','demanda','investigación','fraude','alerta','despidos'
}


def _score_text(text):
    words = re.findall(r"[a-záéíóúñ]+", (text or '').lower())
    pos = sum(1 for w in words if w in _POS)
    neg = sum(1 for w in words if w in _NEG)
    raw = pos - neg
    if raw > 1: label='bullish'
    elif raw < -1: label='bearish'
    else: label='neutral'
    score = max(-100, min(100, raw * 18))
    return score, label


def _public_queries(symbol):
    s = re.sub(r'[^A-Z0-9.\-]', '', str(symbol or '').upper())[:16]
    return [
        f'{s} stock latest news earnings company today',
        f'{s} market news analyst upgrade downgrade today',
        f'site:x.com {s} stock trader market',
    ]


def get_context(symbol, force=False, limit=8):
    key = re.sub(r'[^A-Z0-9.\-]', '', str(symbol or '').upper())[:16]
    if not key:
        return {'ok':False,'symbol':'','error':'Símbolo no válido','items':[]}
    now=time.time()
    with _LOCK:
        cached=_CACHE.get(key)
        if cached and not force and now-cached['ts'] < _TTL:
            out=dict(cached['data']); out['cached']=True; return out
    rows=[]; seen=set(); providers=[]
    errors=[]
    for query in _public_queries(key):
        try:
            result=public_search_results(query, max(3, min(int(limit), 8)))
            if result.get('provider'): providers.append(result.get('provider'))
            if not result.get('ok'):
                if result.get('error'): errors.append(str(result['error']))
                continue
            for item in result.get('results') or []:
                url=item.get('url') or ''
                if not url or url in seen: continue
                seen.add(url)
                text=(item.get('title') or '')+' '+(item.get('snippet') or '')
                score,label=_score_text(text)
                rows.append({
                    'title':(item.get('title') or url)[:300], 'url':url,
                    'snippet':(item.get('snippet') or '')[:700],
                    'sentiment':label,'score':score,
                })
                if len(rows)>=limit: break
            if len(rows)>=limit: break
        except Exception as exc:
            errors.append(str(exc))
    total=sum(x['score'] for x in rows)
    avg=round(total/max(len(rows),1),1)
    overall='bullish' if avg>15 else 'bearish' if avg<-15 else 'neutral'
    data={
        'ok':bool(rows),'symbol':key,'items':rows,'sentiment':overall,'sentiment_score':avg,
        'provider':', '.join(dict.fromkeys(providers)) or 'public web',
        'public_only':True,'order_authority':False,'cached':False,
        'fetched_at':datetime.now(timezone.utc).isoformat(),
        'error':'; '.join(errors)[:900] if not rows else ''
    }
    with _LOCK: _CACHE[key]={'ts':now,'data':data}
    return data
