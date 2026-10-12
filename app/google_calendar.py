from datetime import datetime, timezone, timedelta
from googleapiclient.discovery import build
from .cloud_auth import get_credentials

def is_connected(): return bool(get_credentials())

def service(write=False):
    creds=get_credentials()
    if not creds: raise PermissionError('Google no está conectado. Pulsa Conectar Google.')
    if write:
        granted=set(getattr(creds,'granted_scopes',None) or creds.scopes or [])
        writable={'https://www.googleapis.com/auth/calendar',
                  'https://www.googleapis.com/auth/calendar.events',
                  'https://www.googleapis.com/auth/calendar.events.owned'}
        if not granted.intersection(writable):
            raise PermissionError('Autoriza el permiso de escritura de Google Calendar para crear eventos.')
    return build('calendar','v3',credentials=creds,cache_discovery=False)

def upcoming_events(days=7,max_results=10):
    now=datetime.now(timezone.utc); until=now+timedelta(days=days)
    result=service().events().list(calendarId='primary',timeMin=now.isoformat(),timeMax=until.isoformat(),maxResults=max_results,singleEvents=True,orderBy='startTime').execute(); out=[]
    for e in result.get('items',[]):
        st=e.get('start',{}); en=e.get('end',{}); out.append({'id':e.get('id'),'summary':e.get('summary','(sin título)'),'start':st.get('dateTime',st.get('date')),'end':en.get('dateTime',en.get('date')),'htmlLink':e.get('htmlLink')})
    return out

def calendar_status():
    info=service().calendars().get(calendarId='primary').execute(); return {'ok':True,'summary':info.get('summary',''),'timeZone':info.get('timeZone',''),'id':info.get('id','')}

def event_body(summary,start_iso,end_iso,description='',location='',all_day=False):
    """Validate locally before accessing Google; keep the existing Madrid default."""
    from datetime import date
    from zoneinfo import ZoneInfo
    for name,value,limit in [('Título',summary,1024),('Descripción',description,10000),('Ubicación',location,2048)]:
        if not isinstance(value,str) or len(value)>limit:
            raise ValueError(name+' no válido o demasiado largo.')
    if not summary.strip():raise ValueError('Indica un título para el evento.')
    if not isinstance(all_day,bool):raise ValueError('El indicador de día completo no es válido.')
    if not isinstance(start_iso,str) or not isinstance(end_iso,str):
        raise ValueError('Indica fechas de inicio y fin válidas.')
    try:
        if all_day:
            start=date.fromisoformat(start_iso);end=date.fromisoformat(end_iso)
            bounds={'start':{'date':start.isoformat()},'end':{'date':end.isoformat()}}
        else:
            start=datetime.fromisoformat(start_iso.replace('Z','+00:00'))
            end=datetime.fromisoformat(end_iso.replace('Z','+00:00'))
            if 'T' not in start_iso or 'T' not in end_iso:raise ValueError()
            if start.tzinfo is None:start=start.replace(tzinfo=ZoneInfo('Europe/Madrid'))
            if end.tzinfo is None:end=end.replace(tzinfo=ZoneInfo('Europe/Madrid'))
            bounds={'start':{'dateTime':start.isoformat(),'timeZone':'Europe/Madrid'},
                    'end':{'dateTime':end.isoformat(),'timeZone':'Europe/Madrid'}}
    except (ValueError,OverflowError):
        raise ValueError('Indica fechas de inicio y fin válidas.') from None
    if end<=start:raise ValueError('El fin del evento debe ser posterior al inicio.')
    return {'summary':summary.strip(),'description':description,'location':location,**bounds}


def create_event(summary,start_iso,end_iso,description='',location='',all_day=False):
    body=event_body(summary,start_iso,end_iso,description,location,all_day)
    return service(write=True).events().insert(calendarId='primary',body=body).execute()


def month_events(year, month):
    """List primary-calendar events intersecting the requested calendar month."""
    import calendar as _calendar
    from zoneinfo import ZoneInfo
    tz=ZoneInfo("Europe/Madrid")
    first=datetime(year,month,1,tzinfo=tz)
    last_day=_calendar.monthrange(year,month)[1]
    until=datetime(year,month,last_day,23,59,59,tzinfo=tz)
    result=service().events().list(
        calendarId='primary', timeMin=first.astimezone(timezone.utc).isoformat(),
        timeMax=until.astimezone(timezone.utc).isoformat(), maxResults=250,
        singleEvents=True, orderBy='startTime'
    ).execute()
    out=[]
    for e in result.get('items',[]):
        st=e.get('start',{}); en=e.get('end',{})
        start=st.get('dateTime',st.get('date')); end=en.get('dateTime',en.get('date'))
        out.append({'id':e.get('id'),'summary':e.get('summary','(sin título)'),
                    'start':start,'end':end,'all_day':bool(st.get('date')),
                    'htmlLink':e.get('htmlLink'),'location':e.get('location','')})
    return out
