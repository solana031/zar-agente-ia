"""Resolve recipients from real contacts and scoped relationship memory."""
import re
from . import holdings

def resolve(scope,name):
    from .google_contacts import search_contacts
    from .knowledge import search_hybrid
    needle=str(name or '').strip().casefold()
    if not needle:return {'status':'WAITING','reason':'Destinatario pendiente','candidates':[]}
    state=holdings.read(scope);candidates=[]
    for row in state.get('contact_relations',[]):
        if needle in [str(x).casefold() for x in [row.get('display_name',''),*row.get('aliases',[])]]:
            candidates.append(dict(row,source='ZAR_RELATION_MEMORY',confidence=1.0))
    errors=[]
    try:
        for row in search_contacts(name,20):
            raw=row.get('raw') or {};emails=[e['value'] for e in raw.get('emailAddresses',[]) if e.get('value')]
            if not emails and row.get('email'):emails=[row['email']]
            if not emails:continue
            candidates.append({'contact_id':row.get('resourceName'),'display_name':row.get('name'),'emails':emails,'phones':[p['value'] for p in raw.get('phoneNumbers',[]) if p.get('value')],'aliases':[],
                'source':'GOOGLE_CONTACTS','confidence':.95 if needle in str(row.get('name','')).casefold() else .6})
    except Exception:errors.append('Google Contacts no confirmó acceso; no se inventará una dirección.')
    try:
        for hit in search_hybrid(name,limit=10):
            text=str(hit.get('text') or hit.get('content') or '')
            for line in text.splitlines():
                if needle not in line.casefold():continue
                for address in re.findall(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}',line):
                    candidates.append({'contact_id':hit.get('source_id'),'display_name':name,'emails':[address],'phones':[],'aliases':[],'source':'DOCUMENTED_HISTORY','confidence':.65})
    except Exception:pass
    unique={}
    for row in candidates:
        key=tuple(sorted(set(row['emails'])))
        if key not in unique or row['confidence']>unique[key]['confidence']:unique[key]=row
    rows=list(unique.values());valid=[x for x in rows if x['confidence']>=.9 and len(x['emails'])==1]
    return {'status':'RESOLVED' if len(rows)==1 and len(valid)==1 else 'WAITING','contact':valid[0] if len(rows)==1 and len(valid)==1 else None,'candidates':rows,'errors':errors}

def remember(scope,contact,**relations):
    with holdings.transaction(scope):
        d=holdings.read(scope);rows=d.setdefault('contact_relations',[])
        row=next((r for r in rows if r.get('emails')==contact.get('emails')),None)
        if not row:row=dict(contact,files=[],tasks=[],projects=[],companies=[],conversations=[]);rows.append(row)
        for key,values in relations.items():
            if key not in {'files','tasks','projects','companies','conversations','aliases'}:continue
            row.setdefault(key,[])
            for value in values:
                if value not in row[key]:row[key].append(value)
        holdings.write(scope,d);return row
