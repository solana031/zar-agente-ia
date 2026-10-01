"""Paper transport only. No environment variable can authorize Live."""
import math

LIVE_TRADING_ENABLED = False


class LiveExecutionAdapter:
    def __new__(cls, *args, **kwargs):
        raise RuntimeError('LIVE BLOQUEADO: adapter no disponible')


class PaperExecutionAdapter:
    def __init__(self, post):
        self._post = post

    def submit(self, body, state, credentials):
        # Caller must complete Decision/Risk in the serialized state transaction.
        # Repeat the non-negotiable controls at the final transport boundary.
        if state.get('mode') != 'paper' or body.get('mode', 'paper') != 'paper':
            raise RuntimeError('LIVE BLOQUEADO')
        if state.get('execution_mode') not in ('decision', 'paper_auto'):
            raise RuntimeError('Shadow no tiene autoridad de orden')
        if state.get('paused', True) or state.get('revoked', True):
            raise RuntimeError('Paper bloqueado por pausa/revocacion')
        for name in ('max_trade_eur', 'max_daily_loss_eur', 'max_position_pct'):
            value = float(state.get(name) or 0)
            if not math.isfinite(value) or value <= 0:
                raise RuntimeError('Limites Risk invalidos')
        key, secret = credentials
        if not key or not secret:
            raise RuntimeError('Credenciales Paper no configuradas')
        response = self._post('https://paper-api.alpaca.markets/v2/orders',
            headers={'APCA-API-KEY-ID': key, 'APCA-API-SECRET-KEY': secret},
            json=body, timeout=12)
        if not response.ok:
            raise RuntimeError('Orden Paper no confirmada; reconciliar identificador antes de reintentar')
        order = response.json()
        if not isinstance(order, dict) or not order.get('id'):
            raise RuntimeError('Respuesta Paper no valida')
        return order
