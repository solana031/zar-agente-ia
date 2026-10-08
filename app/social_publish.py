"""Official social publishing connectors used by ZAR Media.

Posting remains disabled until the platform tokens are explicitly configured.
"""
from __future__ import annotations
import os, requests


def status():
    return {
        "tiktok": bool(os.environ.get("TIKTOK_ACCESS_TOKEN", "").strip()),
        "instagram": bool(os.environ.get("INSTAGRAM_ACCESS_TOKEN", "").strip() and os.environ.get("INSTAGRAM_IG_USER_ID", "").strip()),
        "instagram_graph_version": os.environ.get("META_GRAPH_VERSION", "v24.0"),
    }


def tiktok_direct_post(video_url, caption, privacy="SELF_ONLY", confirmed=False):
    token=os.environ.get("TIKTOK_ACCESS_TOKEN","").strip()
    if not token: return {"ok":False,"configured":False,"error":"Falta TIKTOK_ACCESS_TOKEN."}
    if not confirmed: return {"ok":False,"requires_review":True,"message":"Confirma la publicación antes de enviarla a TikTok."}
    headers={"Authorization":"Bearer "+token,"Content-Type":"application/json; charset=UTF-8"}
    info=requests.post("https://open.tiktokapis.com/v2/post/publish/creator_info/query/",headers=headers,json={},timeout=25)
    if not info.ok: raise RuntimeError(f"TikTok creator info {info.status_code}: {info.text[:700]}")
    options=((info.json().get("data") or {}).get("privacy_level_options") or [])
    if privacy not in options: raise ValueError("Privacidad TikTok no autorizada por la cuenta; revisa las opciones actuales.")
    payload={"post_info":{"title":str(caption or "")[:2200],"privacy_level":privacy,"disable_duet":False,"disable_comment":False,"disable_stitch":False,"is_aigc":True},"source_info":{"source":"PULL_FROM_URL","video_url":video_url}}
    r=requests.post("https://open.tiktokapis.com/v2/post/publish/video/init/",headers=headers,json=payload,timeout=30)
    if not r.ok: raise RuntimeError(f"TikTok publish {r.status_code}: {r.text[:900]}")
    return {"ok":True,"platform":"tiktok","data":r.json().get("data") or {}}


def instagram_reel(video_url, caption, confirmed=False):
    token=os.environ.get("INSTAGRAM_ACCESS_TOKEN","").strip(); user=os.environ.get("INSTAGRAM_IG_USER_ID","").strip(); ver=os.environ.get("META_GRAPH_VERSION","v24.0")
    if not token or not user: return {"ok":False,"configured":False,"error":"Faltan INSTAGRAM_ACCESS_TOKEN / INSTAGRAM_IG_USER_ID."}
    if not confirmed: return {"ok":False,"requires_review":True,"message":"Confirma la publicación antes de enviarla a Instagram."}
    base=f"https://graph.facebook.com/{ver}"
    r=requests.post(f"{base}/{user}/media",params={"media_type":"REELS","video_url":video_url,"caption":str(caption or "")[:2200],"share_to_feed":"true","access_token":token},timeout=35)
    if not r.ok: raise RuntimeError(f"Instagram container {r.status_code}: {r.text[:900]}")
    cid=(r.json() or {}).get("id")
    if not cid: raise RuntimeError("Instagram no devolvió container id.")
    # Container processing can take time. We return the ID and publish can be retried after FINISHED.
    status_r=requests.get(f"{base}/{cid}",params={"fields":"status_code,status","access_token":token},timeout=25)
    status_data=status_r.json() if status_r.ok else {}
    if str(status_data.get("status_code") or "").upper() != "FINISHED":
        return {"ok":True,"platform":"instagram","container_id":cid,"status":status_data,"pending_publish":True}
    p=requests.post(f"{base}/{user}/media_publish",params={"creation_id":cid,"access_token":token},timeout=35)
    if not p.ok: raise RuntimeError(f"Instagram publish {p.status_code}: {p.text[:900]}")
    return {"ok":True,"platform":"instagram","container_id":cid,"media":p.json()}


def publishing_readiness(platform):
    if platform not in {'tiktok','instagram'}: raise ValueError('Plataforma no admitida.')
    connected=status()[platform]
    result={'ok':True,'connected':connected,'privacy_options':[],'account':None}
    if not connected:return result
    if platform=='instagram':
        user=os.environ.get('INSTAGRAM_IG_USER_ID')
        response=requests.get('https://graph.facebook.com/'+os.environ.get('META_GRAPH_VERSION','v24.0')+'/'+user,params={'fields':'id,username','access_token':os.environ['INSTAGRAM_ACCESS_TOKEN']},timeout=20,allow_redirects=False)
        if not response.ok:raise ValueError('Instagram no confirmó identidad (HTTP '+str(response.status_code)+').')
        data=response.json()
        if data.get('id')!=user:raise ValueError('Instagram devolvió otra identidad.')
        result.update(account=data.get('username'),account_id=data['id'],capabilities=['IDENTITY_VERIFIED'],publish_capability='UNVERIFIED')
        return result
    response=requests.post('https://open.tiktokapis.com/v2/post/publish/creator_info/query/',headers={'Authorization':'Bearer '+os.environ['TIKTOK_ACCESS_TOKEN']},json={},timeout=25,allow_redirects=False)
    if not response.ok:raise ValueError('TikTok no confirmó cuenta/opciones (HTTP '+str(response.status_code)+').')
    payload=response.json()
    if (payload.get('error') or {}).get('code') not in {None,'ok'}:raise ValueError('TikTok requiere revisar la conexión de la cuenta.')
    data=payload.get('data') or {}
    result.update(account=data.get('creator_nickname'),account_id=data.get('creator_username'),max_video_post_duration_sec=data.get('max_video_post_duration_sec'),capabilities=['CREATOR_INFO_VERIFIED'],privacy_options=[v for v in data.get('privacy_level_options',[]) if v in {'PUBLIC_TO_EVERYONE','MUTUAL_FOLLOW_FRIENDS','FOLLOWER_OF_CREATOR','SELF_ONLY'}])
    return result
