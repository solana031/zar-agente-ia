import calendar
import os
from collections import defaultdict
from datetime import datetime, date

from .file_store import list_files, get_file, ensure_evidence_token
from .google_workspace import sheets_add_professional_table, sheets_service, _normalize_spreadsheet_id


def _num(v):
    if v is None or v == '':
        return None
    try:
        if isinstance(v, (int, float)):
            return float(v)
        s = str(v).strip().replace('€','').replace('EUR','').replace(' ', '')
        if ',' in s and '.' in s:
            if s.rfind(',') > s.rfind('.'):
                s = s.replace('.','').replace(',','.')
            else:
                s = s.replace(',','')
        elif ',' in s:
            s = s.replace('.','').replace(',','.')
        return float(s)
    except Exception:
        return None


def _iso_date(v):
    s = str(v or '').strip()
    if not s:
        return ''
    for fmt in ('%Y-%m-%d','%d/%m/%Y','%d-%m-%Y','%d.%m.%Y'):
        try:
            return datetime.strptime(s[:10], fmt).date().isoformat()
        except Exception:
            pass
    return ''


def _evidence_formula(item):
    if not item or not str(item.get('mime') or '').startswith('image/'):
        return ''
    origin = (os.environ.get('PUBLIC_BASE_URL') or '').strip().rstrip('/')
    if not origin:
        return ''
    tok = ensure_evidence_token(item.get('id'))
    if not tok:
        return ''
    url = f"{origin}/api/files/{item.get('id')}/evidence/{tok}"
    return f'=IMAGE("{url}",4,96,128)'


def _clear_tab(spreadsheet_id, title):
    try:
        sheets_service().spreadsheets().values().clear(
            spreadsheetId=_normalize_spreadsheet_id(spreadsheet_id),
            range=f"'{title.replace(chr(39), chr(39)*2)}'!A:Z",
            body={}
        ).execute()
    except Exception:
        pass


def _collect_records(file_ids=None, year=None, month=None):
    wanted = set(str(x) for x in (file_ids or []) if x)
    items = list_files()
    if wanted:
        items = [x for x in items if str(x.get('id')) in wanted]
    shifts=[]
    closures=[]
    sources=[]
    for item in items:
        analysis = item.get('analysis') or {}
        if not analysis:
            continue
        kind = str(analysis.get('record_kind') or '').lower()
        if kind in {'shift_roster','mixed'}:
            for rec in analysis.get('shift_records') or []:
                if not isinstance(rec, dict):
                    continue
                d = _iso_date(rec.get('work_date'))
                if not d:
                    continue
                dd = date.fromisoformat(d)
                if year and dd.year != int(year):
                    continue
                if month and dd.month != int(month):
                    continue
                row=dict(rec)
                row['work_date']=d
                row['_file']=item
                shifts.append(row)
        if kind in {'cash_closure','mixed'}:
            rec = analysis.get('cash_closure') or {}
            if isinstance(rec, dict):
                d = _iso_date(rec.get('business_date') or analysis.get('document_date'))
                if d:
                    dd = date.fromisoformat(d)
                    if (not year or dd.year == int(year)) and (not month or dd.month == int(month)):
                        row=dict(rec)
                        row['business_date']=d
                        row['_file']=item
                        closures.append(row)
        sources.append(item)
    return shifts, closures, sources


def _merge_manual(shifts, closures, manual_shifts=None, manual_closures=None):
    for rec in manual_shifts or []:
        if not isinstance(rec, dict):
            continue
        d = _iso_date(rec.get('work_date'))
        if d:
            row=dict(rec); row['work_date']=d; row['_file']=None; shifts.append(row)
    for rec in manual_closures or []:
        if not isinstance(rec, dict):
            continue
        d = _iso_date(rec.get('business_date'))
        if d:
            row=dict(rec); row['business_date']=d; row['_file']=None; closures.append(row)
    return shifts, closures


def sync_business_control(spreadsheet_id, year, month, business_name='Negocio', file_ids=None,
                          manual_shifts=None, manual_closures=None, staff_totals=None):
    """Build a traceable business control workbook from analyzed evidence.

    Original sheets are preserved. Only the managed tabs are cleared/rebuilt.
    """
    year=int(year); month=int(month)
    if month < 1 or month > 12:
        raise ValueError('Mes inválido.')
    shifts, closures, sources = _collect_records(file_ids=file_ids, year=year, month=month)
    shifts, closures = _merge_manual(shifts, closures, manual_shifts, manual_closures)

    # Deduplicate shifts by semantic key; prefer evidence-backed rows.
    dedup={}
    for r in shifts:
        key=(str(r.get('employee') or '').strip().lower(), r.get('work_date',''), str(r.get('start_time') or ''), str(r.get('end_time') or ''))
        prev=dedup.get(key)
        if prev is None or (prev.get('_file') is None and r.get('_file') is not None):
            dedup[key]=r
    shifts=list(dedup.values())
    shifts.sort(key=lambda r:(r.get('work_date',''), str(r.get('employee') or '').lower(), str(r.get('start_time') or '')))

    # Consolidate closures by date; evidence-backed records win, but complementary values merge.
    by_date={}
    for r in closures:
        d=r.get('business_date')
        if not d:
            continue
        cur=by_date.setdefault(d, {'business_date':d, '_file':r.get('_file')})
        if r.get('_file') is not None:
            cur['_file']=r.get('_file')
        for k in ('cash_amount','card_amount','total_amount','terminal_amount','variance_amount','variance_note','operations_count','terminal_name','location','notes'):
            v=r.get(k)
            if v not in (None,''):
                cur[k]=v
    closures=list(by_date.values())

    # If total is absent but cash + card are known, compute it. If card is absent and TPV is known,
    # use TPV only as card when there is no explicit conflicting card amount.
    for r in closures:
        cash=_num(r.get('cash_amount'))
        card=_num(r.get('card_amount'))
        terminal=_num(r.get('terminal_amount'))
        if card is None and terminal is not None:
            card=terminal
            r['card_amount']=card
        total=_num(r.get('total_amount'))
        if total is None and cash is not None and card is not None:
            total=cash+card
            r['total_amount']=round(total,2)
        if r.get('variance_amount') in (None,'') and terminal is not None and card is not None:
            diff=round(card-terminal,2)
            if abs(diff) >= 0.01:
                r['variance_amount']=diff
                r['variance_note']=r.get('variance_note') or 'Diferencia entre tarjeta anotada y total TPV/datáfono.'

    # Every calendar day appears. Multiple shifts on one day produce multiple rows.
    days=calendar.monthrange(year,month)[1]
    shift_by_day=defaultdict(list)
    for r in shifts:
        shift_by_day[r['work_date']].append(r)
    shift_rows=[]
    for day in range(1,days+1):
        d=date(year,month,day).isoformat()
        records=shift_by_day.get(d) or []
        if not records:
            shift_rows.append([d,'Sin registro','','','', '', '', 'Sin datos',''])
            continue
        for r in records:
            dur=_num(r.get('duration_hours'))
            paid=_num(r.get('paid_hours'))
            pending=_num(r.get('pending_hours'))
            if pending is None and dur is not None and paid is not None:
                pending=max(0.0,dur-paid)
            shift_rows.append([
                d, str(r.get('employee') or 'Sin identificar'), str(r.get('start_time') or ''), str(r.get('end_time') or ''),
                dur if dur is not None else '', paid if paid is not None else '', pending if pending is not None else '',
                str(r.get('notes') or ''), _evidence_formula(r.get('_file'))
            ])

    closure_map={r['business_date']:r for r in closures if r.get('business_date')}
    closure_rows=[]
    for day in range(1,days+1):
        d=date(year,month,day).isoformat(); r=closure_map.get(d)
        if not r:
            closure_rows.append([d,'','','','','','','Sin datos',''])
            continue
        cash=_num(r.get('cash_amount')); card=_num(r.get('card_amount')); total=_num(r.get('total_amount')); terminal=_num(r.get('terminal_amount')); variance=_num(r.get('variance_amount'))
        notes=' · '.join(x for x in [str(r.get('variance_note') or '').strip(),str(r.get('notes') or '').strip()] if x)
        closure_rows.append([
            d, cash if cash is not None else '', card if card is not None else '', total if total is not None else '',
            terminal if terminal is not None else '', variance if variance is not None else '', r.get('operations_count') or '', notes,
            _evidence_formula(r.get('_file'))
        ])

    # Personal totals come from detailed shifts, enriched by explicit summary overrides where the daily detail is incomplete.
    per=defaultdict(lambda:{'hours':0.0,'paid':0.0,'pending':0.0,'days':set()})
    for r in shifts:
        emp=str(r.get('employee') or '').strip()
        if not emp: continue
        dur=_num(r.get('duration_hours')) or 0.0
        paid=_num(r.get('paid_hours')) or 0.0
        pend=_num(r.get('pending_hours'))
        per[emp]['hours'] += dur
        per[emp]['paid'] += paid
        per[emp]['pending'] += (pend if pend is not None else max(0.0,dur-paid))
        if r.get('work_date'): per[emp]['days'].add(r['work_date'])
    for override in staff_totals or []:
        if not isinstance(override,dict): continue
        emp=str(override.get('employee') or '').strip()
        if not emp: continue
        if _num(override.get('total_hours')) is not None: per[emp]['hours']=_num(override.get('total_hours'))
        if _num(override.get('paid_hours')) is not None: per[emp]['paid']=_num(override.get('paid_hours'))
        if _num(override.get('pending_hours')) is not None: per[emp]['pending']=_num(override.get('pending_hours'))
    personal_rows=[]
    for emp,d in sorted(per.items(), key=lambda kv: kv[0].lower()):
        personal_rows.append([emp,round(d['hours'],2),round(d['paid'],2),round(d['pending'],2),len(d['days'])])

    total_hours=sum(_num(x[1]) or 0 for x in personal_rows)
    total_paid=sum(_num(x[2]) or 0 for x in personal_rows)
    total_pending=sum(_num(x[3]) or 0 for x in personal_rows)
    closure_values=[r for r in closures if _num(r.get('total_amount')) is not None]
    total_cash=sum(_num(r.get('cash_amount')) or 0 for r in closure_values)
    total_card=sum(_num(r.get('card_amount')) or 0 for r in closure_values)
    total_close=sum(_num(r.get('total_amount')) or 0 for r in closure_values)
    total_variance=sum(_num(r.get('variance_amount')) or 0 for r in closure_values)

    # Compact KPI rows: explicit units in header names prevent formatting ambiguity.
    kpi_rows=[
        ['Horas trabajadas (h)', round(total_hours,2)],
        ['Horas pagadas (h)', round(total_paid,2)],
        ['Horas pendientes (h)', round(total_pending,2)],
        ['Cierres con datos', len(closure_values)],
        ['Efectivo acumulado (€)', round(total_cash,2)],
        ['Tarjeta acumulada (€)', round(total_card,2)],
        ['Cierre total acumulado (€)', round(total_close,2)],
        ['Descuadre acumulado (€)', round(total_variance,2)],
        ['Archivos analizados usados', len({str(x.get('id')) for x in sources if x.get('analysis')})],
    ]

    managed=['Resumen general','Cierres de caja','Horas y turnos','Personal']
    for tab in managed:
        _clear_tab(spreadsheet_id,tab)

    sheets_add_professional_table(spreadsheet_id,'Resumen general',f'{business_name} · Resumen general',['Indicador','Valor'],kpi_rows,
        'A1',f'KPIs operativos · {month:02d}/{year}',[])
    sheets_add_professional_table(spreadsheet_id,'Cierres de caja',f'Cierres de caja · {business_name}',
        ['Fecha','Efectivo (€)','Tarjeta (€)','Cierre total (€)','TPV/datáfono (€)','Descuadre (€)','Operaciones','Observaciones','Evidencia'],
        closure_rows,'A1','Una fila por día. El cierre total es efectivo + tarjeta cuando ambos datos están disponibles.',[])
    sheets_add_professional_table(spreadsheet_id,'Horas y turnos',f'Calendario diario de turnos · {business_name}',
        ['Fecha','Empleado','Entrada','Salida','Horas trabajadas','Horas pagadas','Horas pendientes','Observaciones','Evidencia'],
        shift_rows,'A1','Todos los días del mes aparecen, incluso cuando todavía no hay datos.',[])
    sheets_add_professional_table(spreadsheet_id,'Personal',f'Resumen de personal · {business_name}',
        ['Empleado','Horas trabajadas','Horas pagadas','Horas pendientes','Días con turno registrado'],
        personal_rows,'A1',f'Resumen derivado de turnos detallados y totales confirmados · {month:02d}/{year}',[])

    return {
        'ok':True,
        'spreadsheet_id':_normalize_spreadsheet_id(spreadsheet_id),
        'url':f"https://docs.google.com/spreadsheets/d/{_normalize_spreadsheet_id(spreadsheet_id)}/edit",
        'managed_tabs':managed,
        'shift_records':len(shifts),
        'closure_records':len(closures),
        'source_files':len(sources),
        'notes':'Las pestañas originales no se borran. Solo se reconstruyen las cuatro pestañas gestionadas.'
    }
