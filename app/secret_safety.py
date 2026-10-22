"""Secret-safe diagnostics at logging/JSON boundaries; no credential storage."""
import json
import logging
import os
import re
import traceback

REDACTED='[REDACTED]'
FIELDS={'api_key','api_secret','access_token','refresh_token','client_secret','password',
        'private_key','webhook_secret','webhook_verify_token','session_secret','secret_key',
        'authorization','api_token','id_token','encryption_key'}
PATTERNS=[
    re.compile(r'(?:sk-(?:or-v1-|proj-|svcacct-)?[A-Za-z0-9_-]{24,}|AIza[A-Za-z0-9_-]{30,}|GOCSPX-[A-Za-z0-9_-]{20,})'),
    re.compile(r'(?:github_pat_[A-Za-z0-9_]{40,}|gh[pousr]_[A-Za-z0-9]{30,}|(?:sk|rk)_(?:test|live)_[A-Za-z0-9]{20,}|whsec_[A-Za-z0-9]{24,})'),
    re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----[\s\S]+?-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
]


def field_name(name):
    return re.sub(r'(?<=[a-z0-9])(?=[A-Z])','_',str(name)).lower().replace('-','_')


def sensitive_name(name):
    return bool(re.search(r'(?:^|_)(?:KEY|SECRET|TOKEN|PASSWORD|CREDENTIAL)(?:_|$)',name.upper())) or name=='GOOGLE_CLIENT_CONFIG_JSON'


def known_values():
    values=[]
    def nested(value):
        if isinstance(value,dict):
            for name,item in value.items():
                if field_name(name) in FIELDS and isinstance(item,str):values.append(item)
                elif isinstance(item,(dict,list)):nested(item)
        elif isinstance(value,list):
            for item in value:nested(item)
    for name,value in os.environ.items():
        if not value or not sensitive_name(name):continue
        values.append(value)
        if value.lstrip().startswith('{'):
            try:nested(json.loads(value))
            except ValueError:pass
    return sorted({value for value in values if len(value)>=8},key=len,reverse=True)


def redact_text(value,extra_secrets=()):
    text=str(value)
    for secret in sorted(set(known_values())|{s for s in extra_secrets if isinstance(s,str) and s},key=len,reverse=True):
        text=text.replace(secret,REDACTED)
    for pattern in PATTERNS:text=pattern.sub(REDACTED,text)
    text=re.sub(r'(?i)(Bearer\s+)[A-Za-z0-9_.~+/=-]{8,}',r'\1'+REDACTED,text)
    text=re.sub(r'(?i)([?&](?:key|token|code|client_secret|access_token|refresh_token|api_key)=)[^&#\s"\']+',r'\1'+REDACTED,text)
    text=re.sub(r'(?i)(https?://)[^/\s:@]+:[^@\s]+@',r'\1'+REDACTED+'@',text)
    return text


def redact_payload(value):
    if isinstance(value,dict):
        return {key:REDACTED if field_name(key) in FIELDS and isinstance(item,str) and item else redact_payload(item) for key,item in value.items()}
    if isinstance(value,list):return [redact_payload(item) for item in value]
    return redact_text(value) if isinstance(value,str) else value


def install(app):
    """Preserve cookies/CSRF and provider states; sanitize diagnostics only."""
    factory=logging.getLogRecordFactory()
    if not getattr(factory,'_zar_secret_safe',False):
        def safe_record(*args,**kwargs):
            record=factory(*args,**kwargs)
            try:record.msg=redact_text(record.getMessage())
            except Exception:record.msg='[UNFORMATTABLE_LOG_RECORD]'
            record.args=()
            if record.exc_info:
                record.exc_text=redact_text(''.join(traceback.format_exception(*record.exc_info)))
                record.exc_info=None
            return record
        safe_record._zar_secret_safe=True
        logging.setLogRecordFactory(safe_record)

    @app.after_request
    def secret_safe_json(response):
        if response.is_json and not response.is_streamed:
            payload=response.get_json(silent=True)
            if isinstance(payload,(dict,list)):
                clean=redact_payload(payload)
                if clean!=payload:
                    response.set_data(app.json.dumps(clean))
                    response.headers.pop('ETag',None)
        return response
