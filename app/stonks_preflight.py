"""Read-only Paper entry checks. Missing evidence never means permission."""
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation


def valid_symbol(symbol):
    return bool(re.fullmatch(r'[A-Z][A-Z0-9.-]{0,19}', symbol))


def evaluate(state, symbol, snapshots, configured, owner, now=None):
    now = now or datetime.now(timezone.utc)
    checks = []

    def check(code, label, value):
        checks.append({'code':code, 'label':label,
                       'status':'UNVERIFIED' if value is None else 'PASS' if value else 'BLOCKED'})

    def flag(obj, name, expected):
        return obj.get(name) == expected if name in obj else None

    def number(obj, name):
        try:
            value = Decimal(str(obj[name]))
            return value if value.is_finite() else None
        except (KeyError, InvalidOperation, ValueError, TypeError):
            return None

    account = snapshots.get('account') or {}
    clock = snapshots.get('clock') or {}
    asset = snapshots.get('asset') or {}
    check('CONFIGURED', 'Credenciales Alpaca Paper configuradas', configured)
    check('ACCOUNT', 'Datos de cuenta Paper disponibles', bool(account) or None)
    check('ACTIVE', 'Cuenta ACTIVE', flag(account, 'status', 'ACTIVE'))
    check('TRADING', 'Cuenta permite trading', None if any(k not in account for k in ('trading_blocked','account_blocked')) else account['trading_blocked'] is False and account['account_blocked'] is False)
    check('MARKET', 'Mercado abierto', flag(clock, 'is_open', True))
    check('ENGINE', 'Motor servidor activado', flag(state, 'autonomous_engine', True))
    try:
        age = (now - datetime.fromisoformat(state['engine_last_run'].replace('Z','+00:00'))).total_seconds()
        alive = 0 <= age <= 90
    except (KeyError, TypeError, ValueError):
        alive = None
    check('HEARTBEAT', 'Ciclo servidor reciente (≤90 s)', alive)
    check('OWNER', 'Propietario del motor correcto', owner)
    check('PAUSE', 'Sin Pausa', flag(state, 'paused', False))
    check('REVOCATION', 'Sin Revocación', flag(state, 'revoked', False))
    check('PAPER', 'Modo Paper', flag(state, 'mode', 'paper'))
    check('AUTO', 'Paper automático', flag(state, 'execution_mode', 'paper_auto'))
    check('MANAGEMENT', 'Position Management activo', flag(state, 'position_lifecycle_enabled', True))
    check('SYMBOL', 'Símbolo válido', valid_symbol(symbol))
    check('ASSET', 'Activo existe', False if snapshots.get('asset_missing') else bool(asset) or None)
    for code, label, field, value in [('ASSET_ACTIVE','Activo active','status','active'),('EQUITY_ASSET','Activo us_equity','class','us_equity'),('TRADABLE','Activo tradable','tradable',True),('FRACTIONABLE','Activo fractionable','fractionable',True)]:
        check(code,label,flag(asset,field,value))
    for key, code, label in [('positions','POSITION','Sin posición previa incompatible'),('orders','ORDER','Sin orden abierta incompatible')]:
        rows = snapshots.get(key)
        verified = isinstance(rows,list) and (key!='orders' or len(rows)<500) and all(isinstance(r,dict) and isinstance(r.get('symbol'),str) for r in rows)
        check(code,label,not any(r['symbol'].upper()==symbol for r in rows) if verified else None)
    ledger = state.get('position_ledger')
    active = [r for r in ledger.values() if not r.get('closed')] if isinstance(ledger,dict) else None
    check('TEST', 'Sin otra prueba TEST_LIFECYCLE activa', not any(r.get('purpose')=='TEST_LIFECYCLE' for r in active) if active is not None else None)
    check('INTENT', 'Sin intención incompatible pendiente', not any(r.get('symbol')==symbol for r in active) and symbol not in (state.get('pending_entries') or {}) if active is not None else None)
    equity, last, buying = [number(account,k) for k in ('equity','last_equity','buying_power')]
    trade, daily, pct = [number(state,k) for k in ('max_trade_eur','max_daily_loss_eur','max_position_pct')]
    check('RISK', 'Límites Risk válidos y activos', all(x>0 for x in (trade,daily,pct)) and pct<=100 if all(x is not None for x in (trade,daily,pct)) else None)
    check('EQUITY', 'Equity válido y positivo', equity>0 if equity is not None else None)
    check('MAX_TRADE', 'Máximo por operación ≥1 USD', trade>=1 if trade is not None else None)
    check('BUYING_POWER', 'Buying power ≥1 USD', buying>=1 if buying is not None else None)
    check('DAILY_LOSS', 'Pérdida diaria permite operación', max(Decimal(0),last-equity)<daily if all(x is not None for x in (last,equity,daily)) else None)
    check('MAX_POSITION', 'Máximo de posición permite 1 USD', equity*pct/100>=1 if equity is not None and pct is not None else None)
    status = 'BLOCKED' if any(c['status']=='BLOCKED' for c in checks) else 'UNVERIFIED' if any(c['status']=='UNVERIFIED' for c in checks) else 'READY'
    return {'status':status,'symbol':symbol,'checked_at':now.isoformat(),'checks':checks,
            'market_open':clock.get('is_open') if isinstance(clock.get('is_open'),bool) else None,
            'next_open':clock.get('next_open') if isinstance(clock.get('next_open'),str) else None}
