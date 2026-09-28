"""Persistent Paper position state machine, called by the existing server worker.

No scheduler or credentials live here. Broker I/O and durable writes are injected.
Ownership requires a persisted flat-before-entry intent AND matching broker fills.
"""
from datetime import datetime, timezone, timedelta
from decimal import Decimal, InvalidOperation, ROUND_DOWN
import uuid

TERMINAL = {'filled', 'canceled', 'expired', 'rejected'}


def number(value):
    try:
        result = Decimal(str(value))
        if result.is_finite():
            return result
    except (InvalidOperation, ValueError, TypeError):
        pass
    raise ValueError('Dato numérico Paper no válido')


def now():
    return datetime.now(timezone.utc).isoformat()


def timestamp(value):
    return datetime.fromisoformat(str(value).replace('Z', '+00:00'))


def history_start(records):
    # Include a clock-skew margin; actual ownership boundaries use broker timestamps.
    return (min(timestamp(r['submitted_at']) for r in records) - timedelta(days=1)).isoformat()


def entry_intent(state, symbol, side, qty, strategy, timeframe):
    """Caller must prove flat position + no open order and persist BEFORE POST."""
    cid = 'zar-e-' + uuid.uuid4().hex
    record = {'client_order_id': cid, 'symbol': symbol, 'side': side,
              'qty_requested': str(qty), 'strategy': strategy, 'timeframe': timeframe,
              'origin': 'motor autónomo', 'submitted_at': now(), 'baseline_flat': True,
              'exits': [], 'status': 'PENDIENTE', 'closed': False}
    state.setdefault('position_ledger', {})[cid] = record
    return record


def active_records(state):
    return [r for r in state.get('position_ledger', {}).values() if not r.get('closed')]


def blocked(state, clock):
    if state.get('revoked'):
        return 'Revocado: SL/TP suspendido; reconciliación activa'
    if state.get('paused'):
        return 'Pausado: SL/TP suspendido; reconciliación activa'
    if state.get('mode') != 'paper' or state.get('execution_mode') != 'paper_auto':
        return 'Solo Paper automático permite cierres'
    if not state.get('autonomous_engine') or not state.get('position_lifecycle_enabled'):
        return 'Gestión o motor desactivado: solo reconciliación'
    if not clock.get('is_open'):
        return 'Mercado cerrado: esperando apertura'
    return ''


def manage(state, positions, orders, lookup, submit, save, audit, account, clock, cancel=None):
    """Reconcile a complete broker snapshot. Never infer a fill from submission.

    lookup returns None ONLY on broker HTTP 404. Network/errors raise and retain
    intents. A POST timeout never permits a new client_order_id for that intent.
    """
    managed = state.setdefault('managed_positions', {})
    actions = []
    by_symbol = {p['symbol']: p for p in positions}
    order_map = {o.get('client_order_id'): o for o in orders if o.get('client_order_id')}

    def event(name, row, reason=''):
        audit(name, {'symbol': row['symbol'], 'qty': row.get('qty'),
                     'price': row.get('current_price'), 'entry_price': row.get('entry_price'),
                     'reason': reason, 'client_order_id': row.get('client_order_id')})

    def error(row, reason):
        if row.get('status') != 'ERROR' or row.get('reason') != reason:
            event('POSITION_ERROR', row, reason)
        row.update(status='ERROR', reason=reason, updated_at=now())
        actions.append(row['symbol'] + ': ' + reason)

    for record in active_records(state):
        symbol, cid = record['symbol'], record['client_order_id']
        row = managed.get(symbol)
        if not row or row.get('client_order_id') != cid:
            row = {'symbol': symbol, 'client_order_id': cid, 'status': 'ABIERTA',
                   'strategy': record.get('strategy'), 'origin': record.get('origin'),
                   'opened_at': None, 'qty': '0'}
        try:
            entry = order_map.get(cid) or lookup(cid)
            if not entry:
                managed[symbol] = row
                error(row, 'Entrada pendiente de confirmación de Alpaca; no se reenvía')
                continue
            if entry.get('symbol') != symbol or entry.get('side') != record['side']:
                raise ValueError('Identidad de entrada no coincide')
            filled = number(entry.get('filled_qty') or 0)
            if filled == 0:
                record['status'] = entry.get('status')
                if entry.get('status') in TERMINAL:
                    record['closed'] = True
                    if managed.get(symbol, {}).get('client_order_id') == cid:
                        managed.pop(symbol, None)
                continue
            exit_orders = []
            for intent in record['exits']:
                order = order_map.get(intent['client_order_id']) or lookup(intent['client_order_id'])
                if order and (order.get('symbol') != symbol or order.get('side') == record['side']):
                    raise ValueError('Identidad de salida no coincide')
                exit_orders.append((intent, order))
            exited = sum((number(o.get('filled_qty') or 0) for _, o in exit_orders if o), Decimal(0))
            remaining = filled - exited
            position = by_symbol.get(symbol)
            known_ids = {cid} | {x['client_order_id'] for x in record['exits']}
            foreign = [o for o in orders if o.get('symbol') == symbol
                       and o.get('client_order_id') not in known_ids
                       and (o.get('status') not in TERMINAL or timestamp(o['submitted_at']) >= timestamp(entry['submitted_at']))
                       and (number(o.get('filled_qty') or 0) > 0 or o.get('status') not in TERMINAL)]
            if foreign:
                record['ownership_conflict'] = True
            if not record.get('baseline_flat') or record.get('ownership_conflict'):
                managed[symbol] = row
                error(row, 'Ownership ambiguo: actividad ajena al motor; sin cierre automático')
                continue
            # Do not close a new manual position or mistake transient missing data for closure.
            if remaining == 0 and not position and entry.get('status') in TERMINAL:
                if row.get('status') != 'CERRADA':
                    row.update(status='CERRADA', qty='0', market_value=0, unrealized_pl=0, unrealized_pl_pct=0, reason='Cierre confirmado en Alpaca Paper', closed_at=now())
                    event('POSITION_CLOSED', row, row['reason'])
                record['closed'] = True
                managed[symbol] = row
                continue
            if not position:
                managed[symbol] = row
                error(row, 'Posición no disponible o cierre externo; esperando reconciliación inequívoca')
                continue
            qty = abs(number(position['qty']))
            direction = 'SHORT' if number(position['qty']) < 0 or position.get('side') == 'short' else 'LONG'
            if qty != remaining or direction != ('LONG' if record['side'] == 'buy' else 'SHORT'):
                managed[symbol] = row
                error(row, 'Cantidad/dirección no coincide con fills ZAR; no se gestiona exposición ajena')
                continue
            entry_price, current = number(position['avg_entry_price']), number(position['current_price'])
            if entry_price <= 0 or current <= 0:
                raise ValueError('Precio de posición no válido')
            sign = Decimal(1) if direction == 'LONG' else Decimal(-1)
            sl, tp = number(state['stop_loss_pct']), number(state['take_profit_pct'])
            stop = entry_price * (1 - sign * sl / 100) if sl > 0 else None
            take = entry_price * (1 + sign * tp / 100) if tp > 0 else None
            detected = not row.get('opened_at')
            row.update(direction=direction, qty=str(qty), entry_price=float(entry_price),
                       current_price=float(current), market_value=float(number(position['market_value'])),
                       unrealized_pl=float(number(position['unrealized_pl'])),
                       unrealized_pl_pct=float(number(position['unrealized_plpc']) * 100),
                       stop_price=float(stop) if stop else None, take_price=float(take) if take else None,
                       distance_sl_pct=float(sign * (current - stop) / current * 100) if stop else None,
                       distance_tp_pct=float(sign * (take - current) / current * 100) if take else None,
                       opened_at=row.get('opened_at') or entry.get('filled_at') or entry.get('updated_at') or entry.get('submitted_at'),
                       updated_at=now())
            managed[symbol] = row
            if detected:
                event('POSITION_DETECTED', row, 'Posición y fills reales reconciliados')
            reason = blocked({**state, 'position_lifecycle_enabled':True} if record.get('trigger')=='SIGNAL' else state, clock)
            pending = [(i, o) for i, o in exit_orders if not o or o.get('status') not in TERMINAL]
            if pending:
                intent, order = pending[0]
                row.update(status='CERRANDO_' + intent['trigger'], reason=reason or 'Esperando ejecución y reconciliación')
                if order:
                    continue
                # Missing after an ambiguous POST: only the SAME durable intent can be retried.
                if reason:
                    continue
            else:
                if exit_orders and exit_orders[-1][1].get('status') == 'rejected':
                    error(row, 'Salida rechazada por Alpaca; revisar antes de nuevas órdenes')
                    continue
                if reason or (not (stop or take) and not record.get('trigger')):
                    row.update(status='ABIERTA', reason=reason or 'SL y TP desactivados')
                    continue
                if row.get('status') != 'PROTEGIDA':
                    event('POSITION_PROTECTED', row, 'SL/TP servidor activo')
                row.update(status='PROTEGIDA', reason='SL/TP servidor activo')
                trigger = record.get('trigger')
                if not trigger:
                    if stop and sign * (current - stop) <= 0:
                        trigger = 'SL'
                    elif take and sign * (current - take) >= 0:
                        trigger = 'TP'
                if not trigger:
                    continue
                if not record.get('trigger'):
                    record['trigger'] = trigger
                    event(trigger + '_TRIGGERED', row, 'Nivel alcanzado')
            # Risk applies even to risk-reducing exits: no hidden kill-switch bypass.
            acc = account()
            equity, last = number(acc['equity']), number(acc['last_equity'])
            daily = number(state['max_daily_loss_eur'])
            if acc.get('trading_blocked') or acc.get('account_blocked'):
                error(row, 'Risk: cuenta bloqueada')
                continue
            if max(Decimal(0), last - equity) >= daily:
                error(row, 'Risk: pérdida diaria máxima; cierre suspendido')
                continue
            cap = min(number(state['max_trade_eur']), equity * number(state['max_position_pct']) / 100)
            close_qty = min(qty, cap / current).quantize(Decimal('0.000000001'), rounding=ROUND_DOWN)
            if close_qty <= 0:
                error(row, 'Risk: límites no permiten una cantidad de cierre positiva')
                continue
            # No exits while entry is still filling: cancel remainder first, then reconcile.
            if entry.get('status') not in TERMINAL:
                row.update(status='ABIERTA', reason='SL/TP alcanzado: cancelando remanente de entrada antes de cerrar')
                save(state)
                if cancel and entry.get('status') != 'pending_cancel':
                    cancel(entry['id'])
                continue
            if pending:
                intent = pending[0][0]
                if number(intent['qty']) > close_qty:
                    error(row, 'Risk: intención de cierre pendiente supera límites actuales; no se reenvía')
                    continue
            else:
                intent = {'client_order_id': 'zar-x-' + uuid.uuid4().hex,
                          'qty': str(close_qty), 'trigger': record['trigger'], 'submitted_at': now()}
                record['exits'].append(intent)
            row.update(status='CERRANDO_' + intent['trigger'], reason='Cierre Paper solicitado; pendiente de confirmar')
            save(state)  # durable before any side effect, including retries
            order = submit({'symbol': symbol, 'qty': intent['qty'],
                            'side': 'sell' if direction == 'LONG' else 'buy',
                            'type': 'market', 'time_in_force': 'day',
                            'client_order_id': intent['client_order_id']})
            intent['order_id'] = order.get('id')
            event('CLOSE_REQUESTED', {**row, 'qty':intent['qty'], 'client_order_id':intent['client_order_id']}, intent['trigger'])
            actions.append(symbol + ': ' + row['status'])
        except Exception:
            # Never persist broker response bodies/credentials or erase pending intents.
            managed[symbol] = row
            error(row, 'Fallo temporal de reconciliación/orden Paper; se reintentará con el mismo identificador')
        finally:
            save(state)
    state['lifecycle_last_action'] = ' | '.join(actions) or state.get('lifecycle_last_action')
    save(state)
    return {'actions': actions, 'managed_positions': managed}
