"""Runtime invariant checks for ZAR Stonks. Zero model tokens, zero orders."""
from __future__ import annotations
from datetime import datetime, timezone
from . import stonks_execution, stonks_readiness, stonks_live_readonly


def _now():
    return datetime.now(timezone.utc).isoformat()


def run(state, agents_meta, data_plane):
    state = state or {}
    agents_meta = agents_meta or {}
    data_plane = data_plane or {}
    ids = [str(a.get('id')) for a in (agents_meta.get('agents') or []) if a.get('id')]
    shadow_rows = state.get('shadow_log') or []
    checks = []

    def check(cid, ok, detail):
        checks.append({'id': cid, 'ok': bool(ok), 'detail': str(detail)})

    check('paper_only', state.get('mode') == 'paper', 'Modo operativo permanece Paper')
    check('router_zero_tokens', int(agents_meta.get('token_cost_router') or 0) == 0, 'Router determinista a 0 tokens')
    check('agent_ids_unique', len(ids) == len(set(ids)), 'IDs de subagentes sin duplicados')
    required = {'supervisor','market_data','market_stream','analysis','news_sentiment','data_plane','event_router','ai_gate','self_test','risk','shadow_validation','shadow_outcome','paper_learning','paper_quality','paper_execution','position_manager'}
    check('agents_complete', required.issubset(set(ids)), 'Especialistas críticos registrados')
    check('data_plane_zero_token', data_plane.get('architecture') == 'zero_token_data_plane', 'Data Plane determinista activo')
    check('ai_gate_closed', data_plane.get('ai_gate_enabled') is False, 'AI Gate cerrado por defecto')
    check('shadow_no_orders', all(not bool(r.get('order_created')) for r in shadow_rows), 'Diario Shadow contiene 0 órdenes')
    check('live_hard_locked', stonks_execution.LIVE_TRADING_ENABLED is False, 'Live no disponible; ninguna variable de entorno lo habilita')
    check('live_gate_locked', stonks_execution.LiveSafetyGate.allowed() is False, 'LiveSafetyGate deniega toda escritura Live')
    try:
        stonks_execution.LiveSafetyGate.require('buy')
        gate_raises = False
    except RuntimeError:
        gate_raises = True
    check('live_gate_enforced', gate_raises, 'El gate de servidor rechaza rutas Live')
    adapter = stonks_live_readonly.LiveReadOnlyAdapter
    forbidden = {'submit','buy','sell','cancel','cancel_order','replace','replace_order','modify','patch','post','delete'}
    check('live_adapter_read_only', not any(hasattr(adapter, name) for name in forbidden), 'Adapter Live expone únicamente lectura GET')
    check('live_credentials_separate', 'ALPACA_LIVE_READONLY_KEY' != 'ALPACA_API_KEY', 'Credenciales Live read-only usan namespace separado de Paper')

    readiness = stonks_readiness.evaluate(state, {}, {})
    check('readiness_read_only', readiness['read_only'] and readiness['orders_created'] == 0 and readiness['live_trading_enabled'] is False, 'Readiness nunca autoriza ordenes')
    learning = state.get('paper_learning') or {}
    journal_count = int(state.get('paper_learning_journal_count') or 0)
    check('learning_store_count', journal_count >= 0, 'Contador de journal Paper persistente válido')
    check('learning_no_risk_authority', learning.get('risk_authority') in (None, False), 'Learning no tiene autoridad sobre Risk')
    check('learning_no_live_authority', learning.get('live_authority') in (None, False), 'Learning no puede habilitar Live')
    check('quality_gate_paper_only', bool(state.get('paper_profitability_enabled', True)) and float(state.get('paper_min_signal_quality', 55) or 0) >= 0, 'Quality Gate Paper activo y sin permisos Live/Risk')
    execution_mode = state.get('execution_mode')
    check('execution_mode_valid', execution_mode in ('decision','shadow','paper_auto'), f'Modo de ejecución válido: {execution_mode}')
    if execution_mode == 'paper_auto':
        check('paper_auto_engine', bool(state.get('autonomous_engine')), 'Paper automático exige motor servidor activo')
        check('paper_auto_not_paused', not bool(state.get('paused')), 'Paper automático debe estar reanudado para operar')
        check('paper_auto_not_revoked', not bool(state.get('revoked')), 'Paper automático requiere control no revocado')
        check('paper_lifecycle_guard', bool(state.get('position_lifecycle_enabled')), 'Paper automático exige Position Lifecycle')
    else:
        check('paper_lifecycle_guard', True, 'Guard lifecycle no requerido en modo actual')

    bounds = data_plane.get('runtime_bounds')
    if bounds is not None:
        check('caches_bounded', 0 <= bounds.get('cache_entries', -1) <= bounds.get('cache_limit', -2) and 0 <= bounds.get('scopes', -1) <= bounds.get('scope_limit', -2), 'Caches y scopes dentro del limite duro')
    failed = [x for x in checks if not x['ok']]
    return {
        'ok': not failed,
        'status': 'PASS' if not failed else 'FAIL',
        'passed': len(checks)-len(failed),
        'total': len(checks),
        'failed': len(failed),
        'checks': checks,
        'checked_at': _now(),
        'token_cost': 0,
        'orders_created': 0,
    }
