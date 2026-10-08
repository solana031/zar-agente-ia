"""Scoped map preferences and graph projection of persisted dynamic agents."""
from copy import deepcopy
import math
from . import holdings


def graph(base,d):
    from .business_orchestration import ensure
    control=ensure(d)
    hubs={'business':'BusinessOrchestrator','commerce':'CommerceOrchestrator','web_agency':'AgencyOrchestrator',
          'sites':'SitesOrchestrator','media':'MediaOrchestrator','identity':'IDENTITY','jev':'JEV'}
    seen={a['id'] for a in base['agents']}
    for domain,name in hubs.items():
        if name not in seen:
            base['agents'].append({'id':name,'name':name,'domain':domain,'parent':'zar_supervisor' if domain in {'business','identity','jev'} else 'BusinessOrchestrator',
                                   'type':'orchestrator','role':'Trading aislado' if domain=='business' else domain,'status':control['mode']})
            base['edges'].append(['zar_supervisor' if domain in {'business','identity','jev'} else 'BusinessOrchestrator',name]);seen.add(name)
    from .identity_center import ensure as identity
    state=identity(d)
    for name in ('GOOGLE','GMAIL','WORKSPACE','YOUTUBE','SHOPIFY','STRIPE','INSTAGRAM','TIKTOK','ADSENSE','VERCEL','DOMAIN','PHONE','SUPPLIER','MEDIA','CANVA'):
        aid='Identity:'+name
        if aid in seen:continue
        capability=state['capabilities'].get(name,{})
        plan=next((p for p in state['plans'] if p['service']==name),{})
        base['agents'].append({'id':aid,'name':name.title(),'domain':'identity','parent':'IDENTITY','type':'orchestrator',
            'status':state['google']['status'] if name=='GOOGLE' else capability.get('status',plan.get('status','NOT_CONNECTED')),
            'account':state['google'].get('email'),'capabilities':capability})
        base['edges'].append(['IDENTITY',aid]);seen.add(aid)
    for key,a in control['agents'].items():
        aid=str(a.get('id') or key)
        if aid in seen:continue
        parent=a.get('parent') or hubs.get(a.get('domain'),'BusinessOrchestrator')
        base['agents'].append({'id':aid,'name':a.get('name',aid),'domain':a.get('domain','business'),
            'parent':parent,'type':a.get('type','agent'),'status':a.get('state','UNKNOWN'),'role':a.get('function',''),
            'task':deepcopy(a.get('current_tasks',[])),'heartbeat':a.get('last_heartbeat'),
            'cost':a.get('costs'),'revenue':a.get('attributed_revenue'),'errors':deepcopy(a.get('errors',[]))[-10:]})
        base['edges'].append([parent,aid]);seen.add(aid)
    for agent in base['agents']:
        if agent['id']=='JEV':agent['status']='LOCAL_POLICY_ACTIVE'
    for row in d.get('jev_decisions',[]):
        requester=row.get('requesting_agent')
        edge=[requester,'JEV']
        if requester in seen and requester!='JEV' and edge not in base['edges']:base['edges'].append(edge)
    return base


def save(scope,data):
    result={}
    for key,low,high in [('zoom',.001,1000),('pan_x',0,33000000),('pan_y',0,33000000)]:
        val=float(data.get(key,1 if key=='zoom' else 0))
        if not math.isfinite(val) or not low<=val<=high:raise ValueError('Vista fuera de límites técnicos.')
        result[key]=val
    result['section']=str(data.get('section','all'))[:100]
    result['filters']=[str(x)[:100] for x in data.get('filters',[])][:30]
    with holdings.transaction(scope):
        d=holdings.read(scope);d['map_view']=result;holdings.write(scope,d)
    return result
