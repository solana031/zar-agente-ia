"""Paper-only server credentials, including existing variable compatibility."""
import os
PAPER_URL='https://paper-api.alpaca.markets'

def credentials():
    # A pair is atomic: never mix a new key with a legacy secret.
    key=os.environ.get('ALPACA_API_KEY','').strip()
    secret=os.environ.get('ALPACA_API_SECRET','').strip()
    if key or secret:return key,secret
    return os.environ.get('ALPACA_PAPER_API_KEY','').strip(),os.environ.get('ALPACA_PAPER_API_SECRET','').strip()

def validate_environment():
    base=os.environ.get('ALPACA_BASE_URL',PAPER_URL).strip().rstrip('/')
    if base!=PAPER_URL:raise ValueError('LIVE bloqueado: ALPACA_BASE_URL debe ser https://paper-api.alpaca.markets')
    return PAPER_URL

def preflight(state,account,feed,heartbeat_owner,clock=None):
    from decimal import Decimal,InvalidOperation
    from datetime import datetime,timezone
    def positive(value):
        try:return Decimal(str(value)).is_finite() and Decimal(str(value))>0
        except (InvalidOperation,ValueError,TypeError):return False
    def age(stamp):
        try:return (datetime.now(timezone.utc)-datetime.fromisoformat(str(stamp).replace('Z','+00:00'))).total_seconds()
        except (ValueError,TypeError):return None
    feed_age=age(feed.get('t'))
    beat_age=age((state.get('automaton') or {}).get('last_heartbeat'))
    feed_valid=positive(feed.get('p')) and feed_age is not None and feed_age>=-5
    if (clock or {}).get('is_open') is True:feed_valid=feed_valid and feed_age<=90
    checks={
        'broker':bool(account.get('id')),
        'account_status':account.get('status')=='ACTIVE' and account.get('trading_blocked') is False and account.get('account_blocked') is False,
        'capital':positive(account.get('equity')) and positive(account.get('buying_power')),
        'market_feed':feed_valid,
        'risk_engine':all(positive(state.get(k)) for k in ('max_trade_eur','max_daily_loss_eur','max_position_pct')) and float(state.get('max_position_pct') or 0)<=100,
        'trading_mode':state.get('mode')=='paper' and state.get('execution_mode') in {'decision','shadow','paper_auto'},
        'revocation':not state.get('revoked'),
        'heartbeat':bool(heartbeat_owner and beat_age is not None and 0<=beat_age<=90),
    }
    return {'state':'LISTO' if all(checks[k] for k in ('broker','account_status','capital','market_feed')) else 'ERROR','ready_to_start':all(value for key,value in checks.items() if key!='heartbeat'),'ready_to_trade':all(checks.values()),'checks':checks,
            'heartbeat':{'owner':heartbeat_owner,'last_update':state.get('engine_last_run'),'activation':'STARTING until real engine heartbeat'},
            'source':'Alpaca Paper / IEX','last_update':feed.get('t'),'feed_status':'DELAYED','feed_age_seconds':feed_age,'market_open':(clock or {}).get('is_open'),
            'account':{k:account.get(k) for k in ('id','status','currency','equity','cash','buying_power')},'paper':True}
