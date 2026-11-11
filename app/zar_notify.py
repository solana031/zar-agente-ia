"""ZAR notifications outside the app: email, WhatsApp and (optionally) phone calls.

* Email is sent from ZAR's own Gmail (zaragente031@gmail.com) to the owner's
  personal address. WhatsApp uses the WhatsApp Business Cloud API and phone
  calls use Twilio; both stay off until their credentials are configured.
* Subscriptions ("notify me about X every week") are stored per owner and
  can be created from the chat, from WhatsApp or from the settings panel.
* Important in-app notifications are forwarded immediately; a weekly summary
  (ReposNews visits, Google clicks, YouTube, TikTok, AdSense, Reels) is created
  by default.
* Everything goes through a durable outbox with deduplication and retries.
  Provider responses and tokens never enter logs or stored errors.
"""
import hashlib
import hmac
import html
import json
import os
import re
import secrets
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests

from . import holdings

MADRID = ZoneInfo('Europe/Madrid')
ZAR_EMAIL = 'zaragente031@gmail.com'
DEFAULT_TO = 'solana031@gmail.com'
CHANNELS = ('email', 'whatsapp', 'call')
IMPORTANT_TYPES = {'PUBLISH_FAILED', 'SOCIAL_ACCOUNT_BLOCKED', 'ACCOUNT_CONNECTION', 'WORKER_SESSION_EXPIRED',
                   'ARTICLE_NEEDS_DISAMBIGUATION', 'ARTICLE_IDENTIFICATION_REQUIRED', 'ARTICLE_FAILED',
                   'ARTICLE_READY', 'ARTICLE_UPDATE_READY', 'SYSTEM_ACTION_REQUIRED', 'MIRROR_SYNC_FAILED'}
TOPICS = {
    'resumen_semanal': 'Resumen semanal de ZAR',
    'reposnews': 'Visitas y actividad de ReposNews',
    'youtube': 'YouTube: visualizaciones e ingresos estimados',
    'tiktok': 'TikTok: seguidores y visualizaciones',
    'adsense': 'AdSense: estado e ingresos estimados',
    'reels': 'Reels de Instagram procesados',
}
TOPIC_WORDS = [
    ('resumen_semanal', r'resumen|todo|general|novedades de zar|informe'),
    ('reposnews', r'reposnews|visitas|tr[aá]fico|web\b|p[aá]gina'),
    ('youtube', r'youtube|\byt\b'),
    ('tiktok', r'tiktok|tik tok'),
    ('adsense', r'adsense|anuncios|ingresos de la web'),
    ('reels', r'reels?|instagram'),
]
DAY_NAMES = {'lunes': 0, 'martes': 1, 'miércoles': 2, 'miercoles': 2, 'jueves': 3, 'viernes': 4, 'sábado': 5, 'sabado': 5, 'domingo': 6}


# ------------------------------------------------------------------ state

def owner_scope():
    from . import reposnews as rn
    try:
        return rn.read().get('owner')
    except (OSError, ValueError):
        return None


def _now():
    return time.time()


def settings(data):
    s = data.setdefault('notify', {})
    s.setdefault('email', {'enabled': True, 'to': DEFAULT_TO})
    s.setdefault('whatsapp', {'enabled': False, 'to': ''})
    s.setdefault('call', {'enabled': False, 'to': ''})
    s.setdefault('important', {'enabled': True, 'channels': ['email']})
    s.setdefault('subscriptions', [])
    s.setdefault('outbox', [])
    s.setdefault('questions', {})
    if not s.get('defaults_v1'):
        s['subscriptions'].append(_subscription('resumen_semanal', {'unit': 'week', 'every': 1, 'weekday': 0, 'hour': 9}, 'email', 'default'))
        s['defaults_v1'] = True
    return s


def public_view(scope):
    data = holdings.read(scope)
    s = settings(data)
    return {
        'email': {**s['email'], 'from': ZAR_EMAIL},
        'whatsapp': {**s['whatsapp'], 'configured': whatsapp_configured()},
        'call': {**s['call'], 'configured': call_configured()},
        'important': s['important'],
        'subscriptions': [{k: v for k, v in sub.items() if k != 'last_error_detail'} for sub in s['subscriptions'] if sub.get('active', True)],
        'outbox': [{k: row.get(k) for k in ('id', 'channel', 'subject', 'status', 'created_at', 'sent_at', 'error')} for row in s['outbox'][-15:]][::-1],
        'topics': TOPICS,
    }


def update_settings(scope, payload):
    with holdings.transaction(scope):
        data = holdings.read(scope)
        s = settings(data)
        email = payload.get('email') or {}
        if 'to' in email:
            to = str(email['to']).strip().lower()
            if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]{2,}', to):
                raise ValueError('EMAIL_INVALID')
            s['email']['to'] = to
        if 'enabled' in email:
            s['email']['enabled'] = email['enabled'] is True
        for channel in ('whatsapp', 'call'):
            row = payload.get(channel) or {}
            if 'to' in row:
                number = normalize_phone(row['to'])
                if row['to'] and not number:
                    raise ValueError('PHONE_INVALID')
                s[channel]['to'] = number
            if 'enabled' in row:
                s[channel]['enabled'] = row['enabled'] is True
        important = payload.get('important') or {}
        if 'enabled' in important:
            s['important']['enabled'] = important['enabled'] is True
        if 'channels' in important:
            s['important']['channels'] = [c for c in important['channels'] if c in CHANNELS] or ['email']
        holdings.write(scope, data)
    return public_view(scope)


def normalize_phone(value):
    digits = re.sub(r'[^\d+]', '', str(value or ''))
    if digits.startswith('00'):
        digits = '+' + digits[2:]
    if re.fullmatch(r'[67]\d{8}', digits):  # Spanish mobile without prefix
        digits = '+34' + digits
    return digits if re.fullmatch(r'\+\d{8,15}', digits) else ''


# ------------------------------------------------------------------ schedule

def _subscription(topic, period, channel, source, label=None):
    sub = {'id': secrets.token_hex(6), 'topic': topic, 'label': label or TOPICS.get(topic) or topic, 'period': period,
           'channel': channel, 'source': source, 'active': True, 'created_at': datetime.now(timezone.utc).isoformat()}
    sub['next_at'] = next_run(period)
    return sub


def next_run(period, after=None):
    now = datetime.fromtimestamp(after or _now(), MADRID)
    unit, every = period.get('unit', 'week'), max(1, int(period.get('every', 1)))
    if unit in ('minute', 'hour'):
        step = timedelta(minutes=every) if unit == 'minute' else timedelta(hours=every)
        return (now + step).timestamp()
    hour = int(period.get('hour', 9))
    candidate = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    if unit == 'day':
        while candidate <= now:
            candidate += timedelta(days=every)
        return candidate.timestamp()
    if unit == 'week':
        weekday = int(period.get('weekday', 0))
        candidate += timedelta(days=(weekday - candidate.weekday()) % 7)
        while candidate <= now:
            candidate += timedelta(weeks=every)
        return candidate.timestamp()
    if unit == 'month':
        day = min(int(period.get('day', 1)), 28)
        candidate = candidate.replace(day=day)
        while candidate <= now:
            month = candidate.month - 1 + every
            candidate = candidate.replace(year=candidate.year + month // 12, month=month % 12 + 1)
        return candidate.timestamp()
    raise ValueError('PERIOD_INVALID')


def describe_period(period):
    unit, every = period.get('unit'), int(period.get('every', 1))
    days = ['lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado', 'domingo']
    hour = '%02d:00' % int(period.get('hour', 9))
    if unit == 'minute':
        return 'cada %d minutos' % every
    if unit == 'hour':
        return 'cada hora' if every == 1 else 'cada %d horas' % every
    if unit == 'day':
        return ('cada día' if every == 1 else 'cada %d días' % every) + ' a las ' + hour
    if unit == 'week':
        return ('cada ' if every == 1 else 'cada %d semanas, el ' % every) + days[int(period.get('weekday', 0))] + ' a las ' + hour
    if unit == 'month':
        return ('cada mes' if every == 1 else 'cada %d meses' % every) + ', el día %d a las %s' % (int(period.get('day', 1)), hour)
    return 'periódicamente'


def add_subscription(scope, topic, period, channel='email', source='ui', label=None):
    if channel not in CHANNELS:
        raise ValueError('CHANNEL_INVALID')
    if period.get('unit') == 'minute' and int(period.get('every', 1)) < 15:
        period = dict(period, every=15)
    with holdings.transaction(scope):
        data = holdings.read(scope)
        s = settings(data)
        same = next((x for x in s['subscriptions'] if x.get('active', True) and x['topic'] == topic and x['channel'] == channel
                     and (x.get('label') == label or not label)), None)
        if same:
            same.update(period=period, next_at=next_run(period), source=source)
            sub = same
        else:
            sub = _subscription(topic, period, channel, source, label)
            s['subscriptions'].append(sub)
        holdings.write(scope, data)
    return sub


def cancel_subscription(scope, ident=None, topic_text=None):
    removed = []
    with holdings.transaction(scope):
        data = holdings.read(scope)
        for sub in settings(data)['subscriptions']:
            if not sub.get('active', True):
                continue
            if ident and sub['id'] == ident or topic_text and (topic_text in (sub.get('label') or '').lower() or topic_text == sub['topic']):
                sub['active'] = False
                removed.append(sub)
        holdings.write(scope, data)
    return removed


# ------------------------------------------------------------------ chat commands

def _period_from_text(text):
    t = text.lower()
    hour = 9
    m = re.search(r'a las (\d{1,2})(?::\d\d)?', t)
    if m and 0 <= int(m.group(1)) <= 23:
        hour = int(m.group(1))
    m = re.search(r'cada (\d+) ?(minutos?|horas?|d[ií]as?|semanas?|mes(?:es)?)', t)
    if m:
        n, word = int(m.group(1)), m.group(2)
        unit = 'minute' if word.startswith('min') else 'hour' if word.startswith('hora') else 'day' if word.startswith('d') else 'week' if word.startswith('sem') else 'month'
        return {'unit': unit, 'every': n, 'hour': hour, 'weekday': 0, 'day': 1}
    for name, number in DAY_NAMES.items():
        if re.search(r'(cada|todos los|los) ' + name, t):
            return {'unit': 'week', 'every': 1, 'weekday': number, 'hour': hour}
    if re.search(r'cada hora|cada 1 hora', t):
        return {'unit': 'hour', 'every': 1}
    if re.search(r'diari|cada d[ií]a|todos los d[ií]as|cada mañana|cada noche', t):
        return {'unit': 'day', 'every': 1, 'hour': 21 if 'noche' in t else hour}
    if re.search(r'semanal|cada semana|todas las semanas', t):
        return {'unit': 'week', 'every': 1, 'weekday': 0, 'hour': hour}
    if re.search(r'mensual|cada mes|todos los meses', t):
        return {'unit': 'month', 'every': 1, 'day': 1, 'hour': hour}
    return None


def _topic_from_text(subject):
    for topic, pattern in TOPIC_WORDS:
        if re.search(pattern, subject, re.I):
            return topic
    return 'custom'


def chat_command(scope, message):
    """Handle 'notifícame de X cada …', 'deja de notificarme de X', 'qué avisos tengo'. None if not a command."""
    text = re.sub(r'\s+', ' ', str(message or '')).strip()
    low = text.lower()
    if not scope or len(text) > 400:
        return None
    if re.search(r'(qu[eé]|cu[aá]les) (avisos|notificaciones|suscripciones)( peri[oó]dicas)? tengo', low):
        view = public_view(scope)
        rows = view['subscriptions']
        if not rows:
            return 'No tienes avisos periódicos activos. Pídeme por ejemplo: «notifícame por email de las visitas de ReposNews cada lunes».'
        return 'Tus avisos activos:\n' + '\n'.join('• %s — %s, por %s' % (r['label'], describe_period(r['period']), r['channel']) for r in rows)
    stop = re.search(r'(deja de|no me|para de|cancela)\s+(?:notificar|avisar|mandar|enviar|el aviso|los avisos)(?:me|nos)?\s*(?:de|sobre)?\s*(.+)', low)
    if stop:
        subject = stop.group(2).strip(' .¡!¿?')
        topic = _topic_from_text(subject)
        removed = cancel_subscription(scope, topic_text=topic if topic != 'custom' else subject)
        if not removed:
            return 'No encontré ningún aviso activo sobre «%s». Pregúntame «qué avisos tengo» para ver la lista.' % subject
        return 'Hecho. He cancelado: ' + ', '.join(r['label'] for r in removed) + '.'
    start = re.search(r'(notif[ií]ca(?:me|nos)|av[ií]sa(?:me|nos)|m[aá]nda(?:me|nos)|env[ií]a(?:me|nos)|inf[oó]rma(?:me|nos)|recu[eé]rda(?:me|nos))\b(.*)', low)
    if not start:
        return None
    rest = start.group(2)
    period = _period_from_text(rest)
    if not period:
        return None
    channel = 'whatsapp' if 'whatsapp' in rest else 'call' if re.search(r'llamada|ll[aá]mame', rest) else 'email'
    subject = re.sub(r'\b(por|a trav[eé]s de) (email|correo|mail|whatsapp|llamada)\b', ' ', rest)
    subject = re.sub(r'\b(cada|todos los|todas las|los|a las)\b.*$', '', subject)
    subject = re.sub(r'^\s*(de|del|sobre|acerca de|con)\s+', '', subject.strip()).strip(' .,¡!¿?')
    if not subject:
        return None
    topic = _topic_from_text(subject)
    label = TOPICS.get(topic) if topic != 'custom' else subject[:1].upper() + subject[1:120]
    reminder = start.group(1).startswith('recu')
    if reminder:
        topic, label = 'reminder', subject[:1].upper() + subject[1:160]
    sub = add_subscription(scope, topic, period, channel, 'chat', label)
    when = datetime.fromtimestamp(sub['next_at'], MADRID).strftime('%d/%m a las %H:%M')
    extra = ''
    if channel == 'whatsapp' and not whatsapp_configured():
        extra = ' Aviso: WhatsApp aún no está configurado en ZAR; hasta entonces te lo enviaré por email.'
    if channel == 'call' and not call_configured():
        extra = ' Aviso: las llamadas aún no están configuradas; hasta entonces te lo enviaré por email.'
    return 'Perfecto. Te %s «%s» %s por %s. Primer envío: %s.%s' % (
        'recordaré' if reminder else 'enviaré', label, describe_period(sub['period']), {'email': 'email', 'whatsapp': 'WhatsApp', 'call': 'llamada'}[channel], when, extra)


# ------------------------------------------------------------------ reports

def _money(value, currency='EUR'):
    try:
        return '%.2f %s' % (float(value), currency)
    except (TypeError, ValueError):
        return '—'


def _section(title, lines):
    return {'title': title, 'lines': [str(x) for x in lines if x]}


def report_reposnews(scope, days=7):
    from . import site_stats, reposnews as rn
    visits = site_stats.summary(days)
    lines = ['Visitas a reposnews.com (últimos %d días): %d (semana anterior: %d)' % (days, visits['total'], visits['previous'])]
    if visits['top']:
        lines.append('Páginas más vistas: ' + '; '.join('%s (%d)' % (p, n) for p, n in visits['top'][:5]))
    data = rn.read()
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    published = [a for a in data.get('articles', []) if a.get('published') and _parse(a.get('published_at')) and _parse(a.get('published_at')) >= cutoff]
    lines.append('Artículos publicados: %d' % len(published) + (' — ' + '; '.join(a.get('title_es', a['id'])[:70] for a in published[:6]) if published else ''))
    try:
        gsc = _search_console(scope, days)
        if gsc:
            lines.append('Google (Search Console): %d clics y %d impresiones (semana anterior: %d clics)' % (gsc['clicks'], gsc['impressions'], gsc['previous_clicks']))
    except Exception:
        lines.append('Google Search Console: sin datos (revisa la conexión en ZAR Sites).')
    return _section('ReposNews', lines)


def _parse(value):
    try:
        result = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return result if result.tzinfo else result.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _search_console(scope, days):
    from . import reposnews_metrics as metrics
    creds = metrics._credentials(scope, 'search_console', None)
    end = datetime.now(timezone.utc).date()
    start = end - timedelta(days=days - 1)
    body = {'startDate': start.isoformat(), 'endDate': end.isoformat(), 'type': 'web', 'dataState': 'all', 'aggregationType': 'byProperty'}
    now = metrics._query(creds, body).get('rows') or [{}]
    before = metrics._query(creds, dict(body, startDate=(start - timedelta(days=days)).isoformat(), endDate=(start - timedelta(days=1)).isoformat())).get('rows') or [{}]
    return {'clicks': int(now[0].get('clicks', 0)), 'impressions': int(now[0].get('impressions', 0)), 'previous_clicks': int(before[0].get('clicks', 0))}


def report_youtube(scope, days=7):
    from . import cloud_auth
    creds = cloud_auth.get_credentials(user_id=cloud_auth.youtube_user_id(scope))
    if not creds or not creds.token:
        return _section('YouTube', ['Sin conexión con YouTube. Conéctalo en CUENTAS.'])
    headers = {'Authorization': 'Bearer ' + creds.token}
    lines = []
    try:
        r = requests.get('https://www.googleapis.com/youtube/v3/channels', params={'part': 'snippet,statistics', 'mine': 'true'}, headers=headers, timeout=(5, 20))
        item = (r.json().get('items') or [{}])[0] if r.ok else {}
        stats = item.get('statistics', {})
        if stats:
            lines.append('Canal %s: %s visualizaciones totales, %s suscriptores, %s vídeos' % (
                item.get('snippet', {}).get('title', ''), stats.get('viewCount', '—'), stats.get('subscriberCount', '—'), stats.get('videoCount', '—')))
    except (requests.RequestException, ValueError):
        lines.append('YouTube no respondió.')
    granted = set(creds.scopes or [])
    if any('yt-analytics' in s for s in granted):
        end = datetime.now(timezone.utc).date()
        start = end - timedelta(days=days - 1)
        metrics = 'views,estimatedMinutesWatched' + (',estimatedRevenue' if any('monetary' in s for s in granted) else '')
        try:
            r = requests.get('https://youtubeanalytics.googleapis.com/v2/reports', params={'ids': 'channel==MINE', 'startDate': start.isoformat(), 'endDate': end.isoformat(), 'metrics': metrics}, headers=headers, timeout=(5, 20))
            row = (r.json().get('rows') or [[]])[0] if r.ok else []
            if row:
                lines.append('Últimos %d días: %s visualizaciones, %s minutos vistos' % (days, int(row[0]), int(row[1])) + (', ingresos estimados ' + _money(row[2], 'USD') if len(row) > 2 else ''))
        except (requests.RequestException, ValueError, IndexError):
            lines.append('YouTube Analytics no respondió.')
    else:
        lines.append('Para ver visualizaciones e ingresos de la semana, reconecta YouTube en CUENTAS (ZAR pedirá el permiso de estadísticas).')
    return _section('YouTube', lines)


def report_tiktok(scope):
    from . import tiktok_oauth
    try:
        token = tiktok_oauth.access_token(scope)
    except Exception:
        token = None
    if not token:
        return _section('TikTok', ['Sin conexión con TikTok. Conéctalo en CUENTAS.'])
    try:
        r = requests.get('https://open.tiktokapis.com/v2/user/info/', params={'fields': 'display_name,follower_count,likes_count,video_count'},
                         headers={'Authorization': 'Bearer ' + token}, timeout=(5, 20))
        user = (r.json().get('data') or {}).get('user') or {}
    except (requests.RequestException, ValueError):
        user = {}
    if 'follower_count' not in user:
        return _section('TikTok', ['TikTok no permite leer estadísticas con el permiso actual (hace falta «user.info.stats» en la app de TikTok). TikTok no ofrece ingresos por API.'])
    return _section('TikTok', ['%s: %s seguidores, %s me gusta, %s vídeos. (TikTok no ofrece ingresos estimados por API.)' % (
        user.get('display_name', 'Cuenta'), user.get('follower_count'), user.get('likes_count'), user.get('video_count'))])


def report_adsense(scope):
    from . import reposnews_metrics as metrics
    cached = holdings.read(scope).get('reposnews_metrics', {}).get('providers', {}).get('adsense', {})
    data = cached.get('data') or {}
    if not data:
        return _section('AdSense', ['Sin datos de AdSense todavía (cuenta pendiente de aprobación o sin conectar).'])
    lines = ['Cuenta: %s · Sitio reposnews.com: %s · Anuncios automáticos: %s' % (
        data.get('account_state', '—'), data.get('site_state', '—'), 'sí' if data.get('auto_ads_enabled') else 'no')]
    sites = holdings.read(scope).get('sites_company', {}) or {}
    estimate = sites.get('metrics', {}).get('adsense_estimated_30d') if isinstance(sites.get('metrics'), dict) else None
    if estimate is not None:
        lines.append('Ingresos estimados (30 días): ' + _money(estimate))
    return _section('AdSense', lines)


def report_reels():
    from . import reposnews as rn, instagram_conversation_history as history
    data = rn.read()
    h = history.summary(data)
    return _section('Instagram → ReposNews', ['Reels encontrados: %s · procesados: %s · pendientes: %s · necesitan tu ayuda: %s' % (
        h.get('reels_found'), h.get('processed'), h.get('pending'), h.get('ambiguous'))])


def report_custom(subject):
    from . import web_search
    result = web_search.google_web_search(subject, 'Resume en español, en 5 viñetas como máximo, lo más relevante y reciente. Incluye fechas y cifras si las hay.')
    text = str(result.get('text') or result.get('answer') or result.get('summary') or '').strip()
    if not text:
        text = 'No he encontrado información nueva sobre este tema.'
    return _section(subject, [line for line in text.splitlines() if line.strip()][:12])


def build_report(scope, sub):
    topic = sub['topic']
    sections = []
    safe = lambda fn, *args: _safe_section(fn, *args)
    if topic == 'reminder':
        return 'Recordatorio: ' + sub['label'], [_section('Recordatorio', [sub['label']])]
    if topic in ('resumen_semanal', 'reposnews'):
        sections.append(safe(report_reposnews, scope))
    if topic in ('resumen_semanal', 'reels'):
        sections.append(safe(report_reels))
    if topic in ('resumen_semanal', 'youtube'):
        sections.append(safe(report_youtube, scope))
    if topic in ('resumen_semanal', 'tiktok'):
        sections.append(safe(report_tiktok, scope))
    if topic in ('resumen_semanal', 'adsense'):
        sections.append(safe(report_adsense, scope))
    if topic == 'custom':
        sections.append(safe(report_custom, sub['label']))
    title = sub.get('label') or TOPICS.get(topic, 'Informe de ZAR')
    return title + ' · ' + datetime.now(MADRID).strftime('%d/%m/%Y'), sections


def _safe_section(fn, *args):
    try:
        return fn(*args)
    except Exception:
        return _section(getattr(fn, '__name__', 'Informe').replace('report_', '').capitalize(), ['No se pudieron obtener estos datos ahora.'])


def render_email(title, sections, footer=None):
    text = title + '\n\n' + '\n\n'.join(s['title'] + '\n' + '\n'.join('- ' + l for l in s['lines']) for s in sections)
    text += '\n\n' + (footer or 'Puedes cambiar o cancelar estos avisos desde ZAR o pidiéndoselo a ZAR en el chat.')
    rows = ''.join('<tr><td style="padding:14px 0;border-top:1px solid #eadfcb"><div style="font:600 15px Arial,sans-serif;color:#3b2a12;margin-bottom:6px">%s</div>%s</td></tr>' % (
        html.escape(s['title']), ''.join('<div style="font:14px/1.5 Arial,sans-serif;color:#3d3a35;margin:3px 0">%s</div>' % html.escape(l) for l in s['lines'])) for s in sections)
    body = ('<div style="background:#f6f1e7;padding:24px 12px"><table role="presentation" style="max-width:600px;margin:auto;background:#fff;border-radius:14px;padding:22px 26px;width:100%%">'
            '<tr><td><div style="font:700 12px Arial,sans-serif;letter-spacing:.12em;color:#a07a35">ZAR · AVISOS</div>'
            '<h1 style="font:700 21px Arial,sans-serif;color:#1d160c;margin:6px 0 4px">%s</h1></td></tr>%s'
            '<tr><td style="padding-top:16px;font:12px Arial,sans-serif;color:#8a8071">%s</td></tr></table></div>') % (
        html.escape(title), rows, html.escape(footer or 'Puedes cambiar o cancelar estos avisos desde ZAR o pidiéndoselo a ZAR en el chat.'))
    return text, body


# ------------------------------------------------------------------ channels

def whatsapp_configured():
    return bool(os.environ.get('WHATSAPP_TOKEN') and os.environ.get('WHATSAPP_PHONE_NUMBER_ID'))


def call_configured():
    return bool(os.environ.get('TWILIO_ACCOUNT_SID') and os.environ.get('TWILIO_AUTH_TOKEN') and os.environ.get('TWILIO_FROM_NUMBER'))


class ChannelError(ValueError):
    pass


def _zar_gmail(scope):
    from . import cloud_auth, google_accounts
    key = hashlib.sha256(ZAR_EMAIL.encode()).hexdigest()
    creds = None
    try:
        if key in google_accounts.read(scope).get('accounts', {}):
            creds = cloud_auth.get_credentials(user_id=scope, account_id=key)
    except (OSError, ValueError):
        creds = None
    if not creds:
        creds = cloud_auth.get_credentials(user_id=scope)
        if creds and str(cloud_auth.get_account_email(creds) or '').lower() != ZAR_EMAIL:
            creds = None
    if not creds:
        raise ChannelError('GMAIL_ZAR_NOT_CONNECTED')
    return creds


def send_email(scope, to, subject, text, body_html=None):
    import base64
    from email.message import EmailMessage
    from googleapiclient.discovery import build
    message = EmailMessage()
    message['To'] = to
    message['From'] = 'ZAR <' + ZAR_EMAIL + '>'
    message['Subject'] = subject
    message.set_content(text)
    if body_html:
        message.add_alternative(body_html, subtype='html')
    creds = _zar_gmail(scope)
    service = build('gmail', 'v1', credentials=creds, cache_discovery=False)
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    return service.users().messages().send(userId='me', body={'raw': raw}).execute().get('id')


def send_whatsapp(to, text, buttons=None):
    if not whatsapp_configured():
        raise ChannelError('WHATSAPP_NOT_CONFIGURED')
    version = os.environ.get('WHATSAPP_API_VERSION', 'v21.0')
    if not re.fullmatch(r'v\d+\.\d+', version):
        version = 'v21.0'
    url = 'https://graph.facebook.com/%s/%s/messages' % (version, re.sub(r'\D', '', os.environ['WHATSAPP_PHONE_NUMBER_ID']))
    recipient = re.sub(r'\D', '', to)
    if buttons:
        payload = {'messaging_product': 'whatsapp', 'to': recipient, 'type': 'interactive', 'interactive': {
            'type': 'button', 'body': {'text': text[:1000]},
            'action': {'buttons': [{'type': 'reply', 'reply': {'id': b['id'][:256], 'title': b['title'][:20]}} for b in buttons[:3]]}}}
    else:
        payload = {'messaging_product': 'whatsapp', 'to': recipient, 'type': 'text', 'text': {'body': text[:4000], 'preview_url': False}}
    response = requests.post(url, json=payload, headers={'Authorization': 'Bearer ' + os.environ['WHATSAPP_TOKEN']}, timeout=(5, 20), allow_redirects=False)
    if response.ok:
        return (response.json().get('messages') or [{}])[0].get('id')
    try:
        code = (response.json().get('error') or {}).get('code')
    except ValueError:
        code = None
    template = os.environ.get('WHATSAPP_TEMPLATE_NAME')
    if code == 131047 and template and not buttons:
        # Outside the 24-hour window Meta only accepts an approved template.
        payload = {'messaging_product': 'whatsapp', 'to': recipient, 'type': 'template', 'template': {
            'name': template, 'language': {'code': os.environ.get('WHATSAPP_TEMPLATE_LANG', 'es')},
            'components': [{'type': 'body', 'parameters': [{'type': 'text', 'text': text[:900]}]}]}}
        response = requests.post(url, json=payload, headers={'Authorization': 'Bearer ' + os.environ['WHATSAPP_TOKEN']}, timeout=(5, 20), allow_redirects=False)
        if response.ok:
            return (response.json().get('messages') or [{}])[0].get('id')
    raise ChannelError('WHATSAPP_HTTP_%s%s' % (response.status_code, '_WINDOW_CLOSED' if code == 131047 else ''))


def place_call(to, text):
    if not call_configured():
        raise ChannelError('CALL_NOT_CONFIGURED')
    sid = re.sub(r'[^A-Za-z0-9]', '', os.environ['TWILIO_ACCOUNT_SID'])
    twiml = '<Response><Say language="es-ES">%s</Say><Pause length="1"/><Say language="es-ES">%s</Say></Response>' % (html.escape(text[:600]), html.escape(text[:600]))
    response = requests.post('https://api.twilio.com/2010-04-01/Accounts/%s/Calls.json' % sid,
                             data={'To': to, 'From': os.environ['TWILIO_FROM_NUMBER'], 'Twiml': twiml},
                             auth=(sid, os.environ['TWILIO_AUTH_TOKEN']), timeout=(5, 20), allow_redirects=False)
    if not response.ok:
        raise ChannelError('CALL_HTTP_%s' % response.status_code)
    return response.json().get('sid')


# ------------------------------------------------------------------ outbox

def enqueue(scope, channel, subject, text, key=None, body_html=None, buttons=None, question=None):
    key = key or secrets.token_hex(8)
    with holdings.transaction(scope):
        data = holdings.read(scope)
        s = settings(data)
        if any(row.get('key') == key for row in s['outbox']):
            return None
        row = {'id': secrets.token_hex(6), 'key': key, 'channel': channel, 'subject': subject[:200], 'text': text[:20000],
               'html': body_html, 'buttons': buttons, 'question': question, 'status': 'PENDING', 'attempts': 0,
               'created_at': datetime.now(timezone.utc).isoformat(), 'next_try': 0}
        s['outbox'].append(row)
        if len(s['outbox']) > 300:
            pending = [r for r in s['outbox'] if r['status'] == 'PENDING']
            done = [r for r in s['outbox'] if r['status'] != 'PENDING']
            s['outbox'] = done[-(300 - min(len(pending), 300)):] + pending[-300:] if len(pending) < 300 else pending[-300:]
        holdings.write(scope, data)
    return row['id']


def _deliver(scope, s, row):
    channel = row['channel']
    if channel == 'whatsapp' and (not s['whatsapp'].get('to') or not whatsapp_configured()):
        channel = 'email'
    if channel == 'call' and (not s['call'].get('to') or not call_configured()):
        channel = 'email'
    if channel == 'email':
        if not s['email'].get('enabled', True):
            return 'SKIPPED', None
        return 'SENT', send_email(scope, s['email'].get('to') or DEFAULT_TO, row['subject'], row['text'], row.get('html'))
    if channel == 'whatsapp':
        body = row['subject'] + '\n\n' + row['text'] if row['subject'] not in row['text'][:200] else row['text']
        return 'SENT', send_whatsapp(s['whatsapp']['to'], body[:4000], row.get('buttons'))
    return 'SENT', place_call(s['call']['to'], row['subject'] + '. ' + row['text'][:400])


def flush(scope, limit=5):
    with holdings.transaction(scope):
        data = holdings.read(scope)
        s = settings(data)
        due = [dict(r) for r in s['outbox'] if r['status'] == 'PENDING' and r.get('next_try', 0) <= _now()][:limit]
        snapshot = {k: dict(s[k]) for k in ('email', 'whatsapp', 'call')}
        holdings.write(scope, data)
    for row in due:
        try:
            status, ref = _deliver(scope, snapshot, row)
            update = {'status': status, 'sent_at': datetime.now(timezone.utc).isoformat(), 'provider_id': ref, 'error': None}
        except Exception as exc:
            code = str(exc) if re.fullmatch(r'[A-Z0-9_]{3,60}', str(exc)) else 'DELIVERY_FAILED'
            attempts = row['attempts'] + 1
            update = {'attempts': attempts, 'error': code, 'next_try': _now() + min(6 * 3600, 120 * 2 ** attempts),
                      'status': 'FAILED' if attempts >= 6 or code == 'GMAIL_ZAR_NOT_CONNECTED' and attempts >= 3 else 'PENDING'}
        with holdings.transaction(scope):
            data = holdings.read(scope)
            for current in settings(data)['outbox']:
                if current['id'] == row['id']:
                    current.update(update)
                    if update.get('status') == 'SENT':
                        current.pop('html', None)
            holdings.write(scope, data)
        if update.get('status') == 'FAILED':
            _emit_failure(scope, row, update['error'])


def _emit_failure(scope, row, code):
    from .notification_center import emit
    message = {'GMAIL_ZAR_NOT_CONNECTED': 'Conecta en CUENTAS la cuenta de Google zaragente031@gmail.com para que ZAR pueda enviarte emails.'}.get(code, 'No se pudo entregar un aviso por ' + row['channel'] + ' (' + code + ').')
    emit(scope, 'SYSTEM_ACTION_REQUIRED', 'notify-failed:' + code, 'Aviso externo no entregado', message, '/accounts#google',
         entity_type='NOTIFY', status='ACTION_REQUIRED', priority='P2', forward=False)


def run_due_subscriptions(scope):
    with holdings.transaction(scope):
        data = holdings.read(scope)
        s = settings(data)
        due = []
        for sub in s['subscriptions']:
            if sub.get('active', True) and sub.get('next_at', 0) <= _now():
                due.append(dict(sub))
                sub['last_run'] = _now()
                sub['next_at'] = next_run(sub['period'])
        holdings.write(scope, data)
    for sub in due:
        title, sections = build_report(scope, sub)
        text, body = render_email(title, sections)
        enqueue(scope, sub['channel'], title, text, key='sub:%s:%d' % (sub['id'], int(sub.get('last_run') or _now()) // 60), body_html=body)


def on_event(scope, row):
    """Forward important in-app notifications. Called by notification_center.emit."""
    if not scope or row.get('status') in {'DONE', 'COMPLETED'} and row.get('type') != 'PUBLISH_SUCCESS':
        return
    important = row.get('priority') in {'P0', 'P1'} or row.get('type') in IMPORTANT_TYPES
    if not important:
        return
    data = holdings.read(scope)
    s = settings(data)
    if not s['important'].get('enabled', True):
        return
    title = str(row.get('title') or 'Aviso de ZAR')[:160]
    message = str(row.get('message') or row.get('reason') or '')[:1200]
    link = row.get('deep_link') or '/'
    base = os.environ.get('PUBLIC_BASE_URL', 'https://web-production-a9565.up.railway.app').rstrip('/')
    url = link if str(link).startswith('http') else base + str(link)
    text, body = render_email(title, [_section('Qué ha pasado', [message, 'Abrir en ZAR: ' + url])],
                              'Recibes este email porque ZAR te avisa de lo importante. Puedes desactivarlo en Notificaciones → Ajustes.')
    for channel in s['important'].get('channels', ['email']):
        question = None
        buttons = None
        if channel == 'whatsapp' and row.get('type') == 'ARTICLE_READY' and row.get('entity_id'):
            qid = secrets.token_hex(5)
            question = {'id': qid, 'kind': 'ARTICLE_PUBLISH', 'article_id': row.get('entity_id')}
            buttons = [{'id': 'q:%s:yes' % qid, 'title': 'Publicar'}, {'id': 'q:%s:no' % qid, 'title': 'Más tarde'}]
            _remember_question(scope, question)
        enqueue(scope, channel, title, text if channel == 'email' else title + '\n' + message + '\n' + url,
                key='event:%s:%s' % (channel, row.get('notification_key') or row.get('id')), body_html=body, buttons=buttons, question=question)


# ------------------------------------------------------------------ questions over WhatsApp

def _remember_question(scope, question):
    from .reposnews_automation import revision
    from . import reposnews as rn
    article = next((a for a in rn.read().get('articles', []) if a['id'] == question.get('article_id')), None)
    if article:
        question['revision'] = revision(article)
    question['created_at'] = _now()
    with holdings.transaction(scope):
        data = holdings.read(scope)
        qs = settings(data)['questions']
        qs[question['id']] = question
        for key in [k for k, v in qs.items() if _now() - v.get('created_at', 0) > 7 * 86400]:
            qs.pop(key, None)
        holdings.write(scope, data)


def answer_question(scope, qid, answer):
    with holdings.transaction(scope):
        data = holdings.read(scope)
        question = settings(data)['questions'].get(qid)
        if not question or question.get('answer'):
            return 'Esa pregunta ya no está pendiente.'
        question['answer'] = answer
        question['answered_at'] = _now()
        holdings.write(scope, data)
    if question.get('kind') == 'ARTICLE_PUBLISH' and answer == 'yes':
        return _publish_from_whatsapp(scope, question)
    return 'De acuerdo, lo dejo pendiente en ZAR.'


def _publish_from_whatsapp(scope, question):
    from . import reposnews as rn, reposnews_automation as automation
    with holdings.transaction('reposnews-editorial'):
        data = rn.read()
        if data.get('owner') != scope:
            return 'No puedo publicar: la sesión no es la propietaria de ReposNews.'
        article = next((a for a in data.get('articles', []) if a['id'] == question.get('article_id')), None)
        if not article or article.get('published'):
            return 'Ese artículo ya está publicado o no existe.'
        if automation.revision(article) != question.get('revision'):
            return 'El borrador cambió después de preguntarte. Revísalo en ZAR antes de publicar.'
        article.update(approval_status='APPROVED_BY_USER', approval={'owner': scope, 'revision': automation.revision(article), 'at': holdings._now(), 'channel': 'WHATSAPP'})
        try:
            automation.publish_article(data, article, scope)
        except ValueError as exc:
            automation.revoke(article)
            rn.write(data)
            return 'No se pudo publicar: %s' % str(exc)[:120]
        rn.write(data)
    return 'Publicado: %s' % article.get('title_es', article['id'])


def verify_whatsapp_signature(raw, header):
    secret = os.environ.get('WHATSAPP_APP_SECRET') or os.environ.get('META_APP_SECRET') or ''
    if not secret or not header or not header.startswith('sha256='):
        return False
    expected = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header[7:])


def handle_whatsapp(payload):
    """Owner messages: button answers, notification commands. Replies through WhatsApp."""
    scope = owner_scope()
    if not scope:
        return 0
    s = settings(holdings.read(scope))
    owner_number = re.sub(r'\D', '', s['whatsapp'].get('to') or '')
    handled = 0
    for entry in (payload.get('entry') or [])[:10]:
        for change in (entry.get('changes') or [])[:10]:
            for message in ((change.get('value') or {}).get('messages') or [])[:10]:
                if not owner_number or re.sub(r'\D', '', str(message.get('from') or '')) != owner_number:
                    continue
                reply = None
                button = ((message.get('interactive') or {}).get('button_reply') or {}).get('id') or ((message.get('button') or {}).get('payload'))
                if button:
                    m = re.fullmatch(r'q:([a-f0-9]{10}):(yes|no)', str(button))
                    if m:
                        reply = answer_question(scope, m.group(1), m.group(2))
                text = ((message.get('text') or {}).get('body') or '').strip()
                if text and not reply:
                    reply = chat_command(scope, text) or ('Hola, soy ZAR. Puedo avisarte de lo que quieras: escribe por ejemplo «notifícame de las visitas de ReposNews cada lunes por whatsapp» o «qué avisos tengo».')
                if reply:
                    handled += 1
                    try:
                        send_whatsapp(s['whatsapp']['to'], reply)
                    except ChannelError:
                        pass
    return handled


# ------------------------------------------------------------------ worker hook

_last_tick = 0


def tick():
    global _last_tick
    if _now() - _last_tick < 55:
        return
    _last_tick = _now()
    scope = owner_scope()
    if not scope:
        return
    run_due_subscriptions(scope)
    flush(scope)


def register(app, scope_fn, csrf_owner):
    from flask import jsonify, request, session, abort

    def owner():
        if session.get('zar_auth') is not True:
            abort(401)
        return scope_fn()

    @app.get('/api/notify/settings')
    def notify_settings():
        return jsonify(ok=True, csrf=session.setdefault('business_csrf', secrets.token_urlsafe(32)), settings=public_view(owner()))

    @app.post('/api/notify/settings')
    def notify_settings_save():
        try:
            return jsonify(ok=True, settings=update_settings(csrf_owner(), request.get_json(silent=True) or {}))
        except ValueError as exc:
            return jsonify(ok=False, error=str(exc), message={'EMAIL_INVALID': 'El email no es válido.', 'PHONE_INVALID': 'El teléfono debe incluir prefijo, por ejemplo +34600111222.'}.get(str(exc), 'No se pudo guardar.')), 400

    @app.post('/api/notify/subscriptions')
    def notify_subscription_add():
        scope = csrf_owner()
        payload = request.get_json(silent=True) or {}
        topic = payload.get('topic')
        if topic not in TOPICS:
            return jsonify(ok=False, error='TOPIC_INVALID'), 400
        period = {k: payload.get(k) for k in ('unit', 'every', 'weekday', 'hour', 'day') if payload.get(k) is not None}
        try:
            next_run(period)
            sub = add_subscription(scope, topic, period, payload.get('channel', 'email'), 'ui')
        except (ValueError, TypeError):
            return jsonify(ok=False, error='PERIOD_INVALID'), 400
        return jsonify(ok=True, subscription=sub, settings=public_view(scope))

    @app.post('/api/notify/subscriptions/<ident>/cancel')
    def notify_subscription_cancel(ident):
        scope = csrf_owner()
        cancel_subscription(scope, ident=ident)
        return jsonify(ok=True, settings=public_view(scope))

    @app.post('/api/notify/test')
    def notify_test():
        scope = csrf_owner()
        channel = (request.get_json(silent=True) or {}).get('channel', 'email')
        if channel not in CHANNELS:
            return jsonify(ok=False, error='CHANNEL_INVALID'), 400
        text, body = render_email('Prueba de avisos de ZAR', [_section('Todo correcto', ['Si lees esto, ZAR puede avisarte por ' + channel + '.'])])
        enqueue(scope, channel, 'Prueba de avisos de ZAR', text, key='test:%s:%d' % (channel, int(_now())), body_html=body)
        flush(scope)
        return jsonify(ok=True, settings=public_view(scope))

    @app.post('/api/notify/report-now')
    def notify_report_now():
        scope = csrf_owner()
        sub = {'id': 'manual', 'topic': 'resumen_semanal', 'label': TOPICS['resumen_semanal']}
        title, sections = build_report(scope, sub)
        text, body = render_email(title, sections)
        enqueue(scope, 'email', title, text, key='manual:%d' % int(_now()), body_html=body)
        flush(scope)
        return jsonify(ok=True, settings=public_view(scope))

    @app.get('/api/whatsapp/webhook')
    def whatsapp_verify():
        expected = os.environ.get('WHATSAPP_VERIFY_TOKEN', '')
        if expected and request.args.get('hub.mode') == 'subscribe' and hmac.compare_digest(request.args.get('hub.verify_token', ''), expected):
            return str(request.args.get('hub.challenge', ''))[:200], 200, {'Content-Type': 'text/plain'}
        abort(403)

    @app.post('/api/whatsapp/webhook')
    def whatsapp_receive():
        raw = request.get_data(cache=True)
        if not verify_whatsapp_signature(raw, request.headers.get('X-Hub-Signature-256', '')):
            abort(403)
        try:
            handle_whatsapp(json.loads(raw or b'{}'))
        except (ValueError, TypeError):
            pass
        return jsonify(ok=True)
