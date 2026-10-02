import os, re, json
from datetime import datetime
from urllib.parse import quote

from .file_store import list_files, get_file


def _num(v):
    if v is None:
        return None
    if isinstance(v, (int,float)):
        return float(v)
    s=str(v).strip().replace('\u00a0',' ')
    s=re.sub(r'[^0-9,.-]','',s)
    if not s:
        return None
    if ',' in s and '.' in s:
        if s.rfind(',') > s.rfind('.'):
            s=s.replace('.','').replace(',','.')
        else:
            s=s.replace(',','')
    elif ',' in s:
        s=s.replace('.','').replace(',','.')
    try:return float(s)
    except Exception:return None


def _date_iso(value):
    if not value:return ''
    s=str(value).strip()
    for fmt in ('%Y-%m-%d','%d/%m/%Y','%d-%m-%Y','%d.%m.%Y','%d/%m/%y','%d-%m-%y'):
        try:return datetime.strptime(s[:10],fmt).strftime('%Y-%m-%d')
        except Exception:pass
    m=re.search(r'\b(\d{1,2})[/-](\d{1,2})[/-](20\d{2}|\d{2})\b',s)
    if m:
        d,mo,y=m.groups(); y=('20'+y if len(y)==2 else y)
        try:return datetime(int(y),int(mo),int(d)).strftime('%Y-%m-%d')
        except Exception:pass
    return ''


def _first_date(a):
    d=_date_iso(a.get('document_date'))
    if d:return d
    for x in a.get('dates') or []:
        if isinstance(x,dict):
            x=x.get('date') or x.get('value') or x.get('text')
        d=_date_iso(x)
        if d:return d
    return _date_iso(a.get('full_text') or '')


def _amounts(a):
    out=[]
    for x in a.get('amounts') or []:
        if isinstance(x,dict):
            label=str(x.get('label') or x.get('type') or x.get('concept') or x.get('name') or '').lower()
            val=_num(x.get('amount', x.get('value', x.get('total'))))
        else:
            label='';val=_num(x)
        if val is not None:out.append((label,val))
    return out


def _match_money(text, labels):
    for lab in labels:
        m=re.search(r'(?i)\b'+lab+r'\b[^\d-]{0,28}(-?\d{1,3}(?:[. ]\d{3})*(?:,\d{2})|-?\d+(?:[.,]\d{2})?)',text or '')
        if m:
            v=_num(m.group(1))
            if v is not None:return v
    return None


def _pick_amount(a, keywords):
    for label,val in _amounts(a):
        if any(k in label for k in keywords):return val
    return None


def _public_base_url():
    explicit=(os.environ.get('ZAR_PUBLIC_BASE_URL') or '').strip().rstrip('/')
    if explicit:return explicit
    domain=(os.environ.get('RAILWAY_PUBLIC_DOMAIN') or '').strip().strip('/')
    if domain:return 'https://'+domain
    return ''


def closure_record(item):
    a=(item or {}).get('analysis') or {}
    if not isinstance(a,dict) or not a:return None
    text='\n'.join(str(x or '') for x in [a.get('full_text'),a.get('summary'),a.get('description')])
    # Prefer the explicit business schema produced by the current analyzer.
    br=a.get('business_records') if isinstance(a.get('business_records'),dict) else {}
    explicit=(br.get('closures') or [])
    explicit=next((x for x in explicit if isinstance(x,dict)),None)
    dtype=' '.join(str(a.get(x) or '') for x in ('document_type','document_subtype','category')).lower()
    closure_like=bool(explicit) or bool(re.search(r'(?i)\b(cierre|caja|tpv|dat[aá]fono|efectivo|tarjeta|ventas|propina)\b', text+' '+dtype))
    if not closure_like:return None
    date=_date_iso((explicit or {}).get('date')) or _first_date(a)
    if not date:return None
    cash=_num((explicit or {}).get('cash'))
    card=_num((explicit or {}).get('card'))
    tpv=_num((explicit or {}).get('tpv_total'))
    printed_total=_num((explicit or {}).get('closing_total'))
    if cash is None: cash=_pick_amount(a,['efectivo','cash'])
    if card is None: card=_pick_amount(a,['tarjeta','card'])
    if tpv is None: tpv=_pick_amount(a,['tpv','datáfono','datafono'])
    if printed_total is None: printed_total=_pick_amount(a,['cierre total','total caja','total cierre','total'])
    if cash is None: cash=_match_money(text,[r'efectivo',r'cash'])
    if card is None: card=_match_money(text,[r'tarjeta(?:s)?',r'card'])
    if tpv is None: tpv=_match_money(text,[r'tpv',r'dat[aá]fono'])
    if printed_total is None: printed_total=_match_money(text,[r'cierre\s+total',r'total\s+(?:de\s+)?caja',r'total\s+cierre'])
    total=(round(cash+card,2) if cash is not None and card is not None else printed_total)
    discrepancy=None
    if total is not None and printed_total is not None and abs(total-printed_total)>0.004:
        discrepancy=round(total-printed_total,2)
    elif card is not None and tpv is not None and abs(card-tpv)>0.004:
        discrepancy=round(card-tpv,2)
    op=(explicit or {}).get('operations')
    try: op=int(op) if op is not None else None
    except Exception: op=None
    if op is None:
        m=re.search(r'(?i)\b(?:operaciones|tickets?|ventas)\b[^\d]{0,20}(\d{1,5})\b',text)
        if m:
            try:op=int(m.group(1))
            except Exception:pass
    tips=_num((explicit or {}).get('tips'))
    if tips is None: tips=_pick_amount(a,['propina','tips'])
    if tips is None: tips=_match_money(text,[r'propina(?:s)?',r'tips?'])
    obs=[]
    if explicit and explicit.get('notes'): obs.append(str(explicit.get('notes'))[:500])
    if discrepancy not in (None,0):obs.append(f'Descuadre detectado: {discrepancy:.2f} €')
    vo=str(a.get('visual_observations') or '').strip()
    if vo:obs.append(vo[:500])
    base=_public_base_url(); evidence=''
    if base and item.get('id'):
        evidence=f'=IMAGE("{base}/api/files/{quote(str(item["id"]), safe="")}/preview",4,90,120)'
    elif item.get('id'):
        evidence=f'Archivo ZAR: {item.get("name") or item.get("id")}'
    return {
        'date':date,'cash':cash,'card':card,'total':total,'tpv':tpv,'discrepancy':discrepancy,
        'operations':op,'tips':tips,'notes':' · '.join(obs),'file_id':item.get('id'),'file_name':item.get('name',''),
        'evidence':evidence,'printed_total':printed_total,
    }


def collect_closures(file_ids=None):
    wanted=set(str(x) for x in (file_ids or []) if x)
    out=[]
    for item in list_files():
        if wanted and str(item.get('id')) not in wanted: continue
        rec=closure_record(item)
        if rec:out.append(rec)
    out.sort(key=lambda x:(x.get('date') or '',x.get('file_name') or ''))
    # newest evidence wins for exact duplicate date+amount signature; preserve distinct closures same day
    unique=[];seen=set()
    for r in out:
        key=(r['date'],r.get('cash'),r.get('card'),r.get('total'),r.get('tpv'))
        if key in seen:continue
        seen.add(key);unique.append(r)
    return unique


def monthly_closure_tabs(records):
    months={}
    for r in records:
        months.setdefault((r.get('date') or '')[:7],[]).append(r)
    tabs=[]
    headers=['Fecha','Efectivo (€)','Tarjeta (€)','Cierre total (€)','TPV / datáfono (€)','Descuadre (€)','Operaciones','Propinas (€)','Observaciones','Evidencia']
    for month, rows in sorted(months.items()):
        if not month:continue
        data=[]
        for r in rows:
            data.append([r['date'],r.get('cash'),r.get('card'),r.get('total'),r.get('tpv'),r.get('discrepancy'),r.get('operations'),r.get('tips'),r.get('notes',''),r.get('evidence','')])
        cash=sum(x.get('cash') or 0 for x in rows); card=sum(x.get('card') or 0 for x in rows)
        total=sum(x.get('total') or 0 for x in rows); tips=sum(x.get('tips') or 0 for x in rows)
        tabs.append({'name':f'Cierres {month}','table_title':f'Cierres de caja · {month}','subtitle':'Datos extraídos de evidencias guardadas en ZAR. Cierre total = Efectivo + Tarjeta cuando ambos están disponibles.','headers':headers,'rows':data,
                     'summary':[{'label':'Efectivo del mes','value':round(cash,2)},{'label':'Tarjeta del mes','value':round(card,2)},{'label':'Cierre total del mes','value':round(total,2)},{'label':'Propinas','value':round(tips,2)},{'label':'Cierres registrados','value':len(rows)}]})
    return tabs


def all_closures_tab(records):
    headers=['Fecha','Mes','Efectivo (€)','Tarjeta (€)','Cierre total (€)','TPV / datáfono (€)','Descuadre (€)','Operaciones','Propinas (€)','Observaciones','Archivo origen','Evidencia']
    rows=[]
    for r in records:
        rows.append([r['date'],r['date'][:7],r.get('cash'),r.get('card'),r.get('total'),r.get('tpv'),r.get('discrepancy'),r.get('operations'),r.get('tips'),r.get('notes',''),r.get('file_name',''),r.get('evidence','')])
    return {'name':'Cierres de caja','table_title':'Histórico de cierres de caja','subtitle':'Histórico consolidado por fecha, con trazabilidad al archivo original.','headers':headers,'rows':rows,'summary':[{'label':'Cierres registrados','value':len(rows)}]}


def summary_tab(records):
    cash=sum(x.get('cash') or 0 for x in records);card=sum(x.get('card') or 0 for x in records);total=sum(x.get('total') or 0 for x in records)
    disc=sum(x.get('discrepancy') or 0 for x in records)
    rows=[['Cierres registrados',len(records)],['Efectivo acumulado (€)',round(cash,2)],['Tarjeta acumulada (€)',round(card,2)],['Cierre total acumulado (€)',round(total,2)],['Descuadre acumulado (€)',round(disc,2)]]
    return {'name':'Resumen general','table_title':'Resumen general · Room 108','subtitle':'KPIs derivados del histórico de cierres analizados y registrados.','headers':['Indicador','Valor'],'rows':rows,'summary':[]}


def shift_records_from_item(item):
    a=(item or {}).get('analysis') or {}
    br=a.get('business_records') if isinstance(a,dict) else None
    shifts=(br or {}).get('shifts') if isinstance(br,dict) else []
    out=[]
    for x in shifts or []:
        if not isinstance(x,dict):continue
        employee=str(x.get('employee') or '').strip()
        date=_date_iso(x.get('date'))
        if not employee or not date:continue
        out.append({'employee':employee,'date':date,'start_time':x.get('start_time'),'end_time':x.get('end_time'),
                    'hours':_num(x.get('hours')),'paid_hours':_num(x.get('paid_hours')),'pending_hours':_num(x.get('pending_hours')),
                    'notes':str(x.get('notes') or ''),'file_name':item.get('name',''),'file_id':item.get('id')})
    return out


def collect_shifts():
    out=[]
    for item in list_files():out.extend(shift_records_from_item(item))
    out.sort(key=lambda x:(x['date'],x['employee'].lower()))
    seen=set();unique=[]
    for r in out:
        k=(r['date'],r['employee'].lower(),str(r.get('start_time')),str(r.get('end_time')))
        if k in seen:continue
        seen.add(k);unique.append(r)
    return unique


def monthly_shift_tabs(records):
    months={}
    for r in records:months.setdefault(r['date'][:7],[]).append(r)
    tabs=[]
    for month,rows in sorted(months.items()):
        data=[]
        for r in rows:
            data.append([r['date'],r['employee'],r.get('start_time'),r.get('end_time'),r.get('hours'),r.get('paid_hours'),r.get('pending_hours'),r.get('notes',''),r.get('file_name','')])
        tabs.append({'name':f'Turnos {month}','table_title':f'Turnos · {month}','subtitle':'Registro cronológico extraído de archivos analizados por ZAR.','headers':['Fecha','Empleado','Entrada','Salida','Horas trabajadas','Horas pagadas','Horas pendientes','Observaciones','Archivo origen'],'rows':data,'summary':[{'label':'Turnos registrados','value':len(rows)},{'label':'Horas registradas','value':round(sum(x.get('hours') or 0 for x in rows),2)}]})
    return tabs
