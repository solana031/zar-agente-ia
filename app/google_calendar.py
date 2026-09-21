from datetime import datetime, timezone, timedelta
from googleapiclient.discovery import build
from .cloud_auth import get_credentials

def is_connected(): return bool(get_credentials())

def service():
    creds=get_credentials()
    if not creds: raise RuntimeError('Google no está conectado. Pulsa Conectar Google.')
    return build('calendar','v3',credentials=creds,cache_discovery=False)

def upcoming_events(days=7,max_results=10):
    now=datetime.now(timezone.utc); until=now+timedelta(days=days)
    result=service().events().list(calendarId='primary',timeMin=now.isoformat(),timeMax=until.isoformat(),maxResults=max_results,singleEvents=True,orderBy='startTime').execute(); out=[]
    for e in result.get('items',[]):
        st=e.get('start',{}); en=e.get('end',{}); out.append({'id':e.get('id'),'summary':e.get('summary','(sin título)'),'start':st.get('dateTime',st.get('date')),'end':en.get('dateTime',en.get('date')),'htmlLink':e.get('htmlLink')})
    return out

def calendar_status():
    info=service().calendars().get(calendarId='primary').execute(); return {'ok':True,'summary':info.get('summary',''),'timeZone':info.get('timeZone',''),'id':info.get('id','')}

def create_event(summary,start_iso,end_iso,description=''):
    body={'summary':summary,'description':description,'start':{'dateTime':start_iso,'timeZone':'Europe/Madrid'},'end':{'dateTime':end_iso,'timeZone':'Europe/Madrid'}}
    return service().events().insert(calendarId='primary',body=body).execute()


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
