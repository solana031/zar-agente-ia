"""Read-only evidence checklist. It has no broker, state-write or model access."""
from datetime import datetime, timezone
import math


def evaluate(state, stream, self_test, journal_verified=False):
    checks = []
    def add(name, value=None, detail=''):
        checks.append({'name': name, 'status': 'preparado tecnicamente' if value is True else 'bloqueado' if value is False else 'pendiente', 'detail': detail})
    def recent(value):
        try:
            return 0 <= (datetime.now(timezone.utc) - datetime.fromisoformat(value.replace('Z', '+00:00'))).total_seconds() <= 90
        except (TypeError, ValueError, AttributeError):
            return False
    learning = state.get('paper_learning') or {}
    overall = learning.get('overall') or {}
    n = int(state.get('paper_learning_journal_count') or 0)
    sample = int(overall.get('trades') or 0)
    add('Paper sample size', True if sample >= 20 else None, f'{sample}/20; muestra descriptiva, no autorizacion Live')
    add('Operaciones aprendidas', True if n else None, str(n))
    # Validation Lab results are not persisted in 31.3.51. Never fabricate evidence.
    add('Estrategia validada', detail='Verificar Validation Lab; sin evidencia persistida')
    add('Walk-forward', detail='Verificar resultados fuera de muestra; sin evidencia persistida')
    add('Shadow history', True if state.get('shadow_log') else None)
    add('Paper history', True if n else None)
    add('Drawdown', detail=f"Maximo observado USD: {overall.get('max_drawdown_usd', 'sin muestra')}; requiere evaluar tolerancia")
    limits = [state.get(k) for k in ('max_trade_eur','max_daily_loss_eur','max_position_pct')]
    try:
        valid = all(math.isfinite(float(x)) and float(x) > 0 for x in limits) and float(limits[2]) <= 100
    except (TypeError, ValueError):
        valid = False
    add('Risk configurado', valid)
    add('Kill switch', isinstance(state.get('paused'), bool) and isinstance(state.get('revoked'), bool), 'Pausa/revocacion bloquean nuevos envios')
    add('Lifecycle', bool(state.get('position_lifecycle_enabled')))
    ledger = state.get('position_ledger') or {}
    add('Ownership', all(r.get('baseline_flat') and not r.get('ownership_conflict') for r in ledger.values()) if ledger else None)
    feeds = [f for f in (stream.get('feeds') or {}).values() if f.get('enabled')]
    add('Stream health', bool(feeds) and all(f.get('connected') and f.get('authenticated') and not f.get('stale') for f in feeds))
    add('Journal persistence', True if journal_verified else None, 'Lectura y contador del journal verificados' if journal_verified else 'Sin journal verificable')
    add('Broker connection', bool(state.get('paper_connected')) and recent(state.get('engine_last_reconcile')), 'Reconciliacion Paper reciente requerida')
    add('Self-Test', self_test.get('ok') is True)
    return {'status': 'bloqueado', 'live_trading_enabled': False, 'label': 'LIVE BLOQUEADO',
            'read_only': True, 'orders_created': 0, 'token_cost': 0, 'checks': checks}
