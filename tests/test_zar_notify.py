import hashlib
import hmac
import json
from datetime import datetime

import pytest
from app import holdings, reposnews as rn, zar_notify as notify, site_stats

SCOPE = 's_' + 'b' * 32


@pytest.fixture
def owner(tmp_path, monkeypatch):
    monkeypatch.setenv('ZAR_DATA_DIR', str(tmp_path))
    rn.write({'owner': SCOPE, 'articles': [], 'instagram_inbox': []})
    sent = []
    monkeypatch.setattr(notify, 'send_email', lambda scope, to, subject, text, html=None: sent.append((to, subject, text)) or 'm1')
    return sent


def test_chat_creates_lists_and_cancels_subscriptions(owner):
    reply = notify.chat_command(SCOPE, 'Notifícame por email de las visitas de ReposNews cada lunes a las 10')
    assert 'Visitas y actividad de ReposNews' in reply and 'lunes a las 10:00' in reply
    sub = next(s for s in notify.public_view(SCOPE)['subscriptions'] if s['source'] == 'chat')
    assert sub['topic'] == 'reposnews' and sub['period'] == {'unit': 'week', 'every': 1, 'weekday': 0, 'hour': 10}
    assert datetime.fromtimestamp(sub['next_at'], notify.MADRID).weekday() == 0
    assert 'Visitas y actividad' in notify.chat_command(SCOPE, '¿Qué avisos tengo?')
    assert 'cancelado' in notify.chat_command(SCOPE, 'deja de notificarme de las visitas de reposnews')
    assert all(s['topic'] != 'reposnews' for s in notify.public_view(SCOPE)['subscriptions'])


def test_custom_topics_whatsapp_and_reminders(owner):
    reply = notify.chat_command(SCOPE, 'avísame por whatsapp del precio del bitcoin cada 6 horas')
    assert 'Precio del bitcoin' in reply and 'WhatsApp' in reply and 'email' in reply  # falls back while not configured
    reply = notify.chat_command(SCOPE, 'recuérdame revisar AdSense cada viernes')
    assert 'recordaré' in reply
    assert notify.chat_command(SCOPE, 'hola, ¿qué tal?') is None
    assert notify.chat_command(SCOPE, 'notifícame de algo') is None  # no period: normal chat handles it


def test_weekly_default_and_due_reports_are_emailed(owner, monkeypatch):
    monkeypatch.setattr(notify, 'build_report', lambda scope, sub: ('Resumen', [notify._section('ReposNews', ['Visitas: 10'])]))
    with holdings.transaction(SCOPE):
        data = holdings.read(SCOPE)
        subs = notify.settings(data)['subscriptions']
        assert subs[0]['topic'] == 'resumen_semanal' and subs[0]['channel'] == 'email'
        subs[0]['next_at'] = 0
        holdings.write(SCOPE, data)
    notify.run_due_subscriptions(SCOPE)
    notify.flush(SCOPE)
    assert owner == [('solana031@gmail.com', 'Resumen', owner[0][2])] and 'Visitas: 10' in owner[0][2]
    notify.run_due_subscriptions(SCOPE); notify.flush(SCOPE)
    assert len(owner) == 1  # rescheduled, not resent


def test_important_events_forwarded_once_and_failures_retry(owner, monkeypatch):
    from app.notification_center import emit
    emit(SCOPE, 'PUBLISH_FAILED', 'k1', 'Publicación fallida', 'Error al publicar', '/x')
    emit(SCOPE, 'PUBLISH_FAILED', 'k1', 'Publicación fallida', 'Error al publicar', '/x')
    emit(SCOPE, 'DOC_READY', 'k2', 'Doc', 'listo', '/y', status='DONE', priority='P2')
    notify.flush(SCOPE)
    assert [s[1] for s in owner] == ['Publicación fallida']
    def broken(*a, **k):
        raise notify.ChannelError('GMAIL_ZAR_NOT_CONNECTED')
    monkeypatch.setattr(notify, 'send_email', broken)
    notify.enqueue(SCOPE, 'email', 'Otro', 'texto', key='k3')
    notify.flush(SCOPE)
    row = next(r for r in notify.public_view(SCOPE)['outbox'] if r['subject'] == 'Otro')
    assert row['status'] == 'PENDING' and row['error'] == 'GMAIL_ZAR_NOT_CONNECTED'


def test_whatsapp_webhook_only_accepts_signed_owner_messages(owner, monkeypatch):
    monkeypatch.setenv('WHATSAPP_APP_SECRET', 'secret')
    raw = b'{"entry":[]}'
    good = 'sha256=' + hmac.new(b'secret', raw, hashlib.sha256).hexdigest()
    assert notify.verify_whatsapp_signature(raw, good) and not notify.verify_whatsapp_signature(raw, 'sha256=00')
    notify.update_settings(SCOPE, {'whatsapp': {'to': '600111222', 'enabled': True}})
    assert notify.public_view(SCOPE)['whatsapp']['to'] == '+34600111222'
    replies = []
    monkeypatch.setattr(notify, 'send_whatsapp', lambda to, text, buttons=None: replies.append((to, text)))
    message = lambda sender, text: {'entry': [{'changes': [{'value': {'messages': [{'from': sender, 'text': {'body': text}}]}}]}]}
    assert notify.handle_whatsapp(message('34999999999', 'notifícame de youtube cada día')) == 0
    assert notify.handle_whatsapp(message('34600111222', 'notifícame de youtube cada día')) == 1
    assert 'YouTube' in replies[-1][1]


def test_whatsapp_publish_answer_is_bound_to_revision(owner, monkeypatch):
    from app import reposnews_automation as automation
    article = {'id': 'demo', 'title_es': 'Demo', 'state': 'READY_PRIVATE', 'published': False}
    rn.write({'owner': SCOPE, 'articles': [article], 'instagram_inbox': []})
    published = []
    monkeypatch.setattr(automation, 'publish_article', lambda data, a, scope: published.append(a['approval']['channel']) or a.update(published=True))
    notify._remember_question(SCOPE, {'id': 'a' * 10, 'kind': 'ARTICLE_PUBLISH', 'article_id': 'demo'})
    data = rn.read(); data['articles'][0]['title_es'] = 'Cambiado'; rn.write(data)
    assert 'cambió' in notify.answer_question(SCOPE, 'a' * 10, 'yes') and not published
    notify._remember_question(SCOPE, {'id': 'c' * 10, 'kind': 'ARTICLE_PUBLISH', 'article_id': 'demo'})
    assert notify.answer_question(SCOPE, 'c' * 10, 'yes').startswith('Publicado') and published == ['WHATSAPP']
    assert 'ya no está pendiente' in notify.answer_question(SCOPE, 'c' * 10, 'yes')


def test_visit_counter_skips_bots_and_assets(owner):
    for _ in range(3):
        site_stats.record('/es/repositorios/uv/', 'Mozilla/5.0 (iPhone)')
    site_stats.record('/es/', 'Mozilla/5.0 (Windows NT 10.0)')
    site_stats.record('/es/', 'Googlebot/2.1')
    site_stats.record('/media/reposnews/x.png', 'Mozilla/5.0')
    result = site_stats.summary(7)
    assert result['total'] == 4 and result['top'][0] == ('/es/repositorios/uv/', 3)


def test_period_rules():
    assert notify._period_from_text('cada 5 minutos')['every'] == 5
    sub = notify._subscription('youtube', {'unit': 'month', 'every': 1, 'day': 1, 'hour': 9}, 'email', 'ui')
    assert datetime.fromtimestamp(sub['next_at'], notify.MADRID).day == 1
    assert notify.describe_period({'unit': 'day', 'every': 1, 'hour': 21}) == 'cada día a las 21:00'
