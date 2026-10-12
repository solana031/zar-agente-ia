"""Calendar creation contracts. No Google writes or application workers run."""
import ast
import secrets
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from flask import Flask, jsonify, request, session

from app import google_calendar


EVENT={'summary':'TEST Calendar review','start_iso':'2026-10-12T08:00:00Z',
       'end_iso':'2026-10-12T09:00:00Z','description':'TEST offline fixture',
       'location':'TEST meeting room'}


@pytest.fixture
def calendar_client(monkeypatch):
    app=Flask('calendar-fixture');app.secret_key='TEST-only-session'
    policy=Mock(return_value={'decision':'CONFIRM'})
    env={'__name__':'app.main','__package__':'app','app':app,'request':request,
         'jsonify':jsonify,'session':session,'secrets':secrets,'datetime':datetime,
         '_user_scope_id':lambda:'TEST-calendar-owner','jev_decision':SimpleNamespace(evaluate=policy)}
    tree=ast.parse(Path('app/main.py').read_text(encoding='utf-8-sig'))
    nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in ('calendar_month_api','calendar_create_api')]
    exec(compile(ast.Module(body=nodes,type_ignores=[]),'calendar-fixture','exec'),env)
    monkeypatch.setattr(google_calendar,'month_events',lambda year,month:[])
    create=Mock(return_value={'id':'TEST-event','summary':EVENT['summary'],'location':EVENT['location']})
    monkeypatch.setattr(google_calendar,'create_event',create)
    client=app.test_client()
    token=client.get('/api/calendar/month?year=2026&month=10').json['csrf']
    return client,{'X-ZAR-Calendar-CSRF':token},create,policy


def test_create_requires_session_csrf_and_explicit_confirmation(calendar_client):
    client,headers,create,policy=calendar_client
    assert client.post('/api/calendar/create',json={**EVENT,'confirmed':True}).status_code==403
    for value in (None,False,'true',1):
        response=client.post('/api/calendar/create',headers=headers,json={**EVENT,'confirmed':value})
        assert response.status_code==409
    create.assert_not_called();policy.assert_not_called()


@pytest.mark.parametrize('patch',[
    {'summary':''},{'summary':123},{'start_iso':'not-a-date'},
    {'start_iso':'2026-10-12'},{'end_iso':EVENT['start_iso']},
    {'end_iso':'2026-10-11T09:00:00Z'},{'description':['bad']},
    {'location':'x'*2049},{'all_day':'false'},
])
def test_invalid_event_never_contacts_google(calendar_client,patch):
    client,headers,create,policy=calendar_client
    response=client.post('/api/calendar/create',headers=headers,json={**EVENT,**patch,'confirmed':True})
    assert response.status_code==400
    create.assert_not_called();policy.assert_not_called()


def test_confirmed_event_passes_location_and_scope_policy(calendar_client):
    client,headers,create,policy=calendar_client
    response=client.post('/api/calendar/create',headers=headers,json={**EVENT,'confirmed':True})
    assert response.status_code==200 and response.json['ok']
    assert response.json['event']['location']==EVENT['location']
    create.assert_called_once_with(**EVENT,all_day=False)
    policy.assert_called_once_with('TEST-calendar-owner',{'action':'CALENDAR_CREATE','agent':'CalendarUI'})


def test_global_stop_does_not_create(calendar_client):
    client,headers,create,policy=calendar_client
    policy.return_value={'decision':'DENY'}
    assert client.post('/api/calendar/create',headers=headers,json={**EVENT,'confirmed':True}).status_code==403
    create.assert_not_called()


def test_provider_error_is_sanitized_and_never_retried(calendar_client):
    client,headers,create,policy=calendar_client
    create.side_effect=RuntimeError('sensitive provider response')
    response=client.post('/api/calendar/create',headers=headers,json={**EVENT,'confirmed':True})
    assert response.status_code==502
    assert 'sensitive' not in response.get_data(as_text=True)
    create.assert_called_once()


@pytest.mark.parametrize('scopes',[[],['https://www.googleapis.com/auth/calendar.readonly']])
def test_readonly_scopes_never_insert(monkeypatch,scopes):
    monkeypatch.setattr(google_calendar,'get_credentials',lambda:SimpleNamespace(scopes=scopes))
    build=Mock();monkeypatch.setattr(google_calendar,'build',build)
    with pytest.raises(PermissionError):google_calendar.create_event(**EVENT)
    build.assert_not_called()


def test_insert_uses_current_credentials_and_location(monkeypatch):
    credentials=SimpleNamespace(scopes=['https://www.googleapis.com/auth/calendar.events'])
    load=Mock(return_value=credentials);build=Mock()
    monkeypatch.setattr(google_calendar,'get_credentials',load)
    monkeypatch.setattr(google_calendar,'build',build)
    google_calendar.create_event(**EVENT)
    load.assert_called_once_with()
    assert build.call_args.kwargs['credentials'] is credentials
    payload=build.return_value.events.return_value.insert.call_args.kwargs
    assert payload['calendarId']=='primary'
    assert payload['body']['location']==EVENT['location']
    assert payload['body']['start']['dateTime']=='2026-10-12T08:00:00+00:00'


def test_all_day_end_is_exclusive_and_naive_legacy_dates_keep_madrid():
    body=google_calendar.event_body('TEST','2026-10-12','2026-10-13',all_day=True)
    assert body['start']=={'date':'2026-10-12'} and body['end']=={'date':'2026-10-13'}
    body=google_calendar.event_body('TEST','2026-10-12T10:00:00','2026-10-12T11:00:00')
    assert body['start']['dateTime'].endswith('+02:00')
