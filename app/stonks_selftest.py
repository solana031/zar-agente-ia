"""Runtime invariant checks for ZAR Stonks. Zero model tokens, zero orders."""
from __future__ import annotations
from datetime import datetime, timezone


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
    required = {'supervisor','market_data','analysis','news_sentiment','data_plane','event_router','ai_gate','self_test','risk','shadow_validation','shadow_outcome','paper_execution','position_manager'}
    check('agents_complete', required.issubset(set(ids)), 'Especialistas críticos registrados')
    check('data_plane_zero_token', data_plane.get('architecture') == 'zero_token_data_plane', 'Data Plane determinista activo')
    check('ai_gate_closed', data_plane.get('ai_gate_enabled') is False, 'AI Gate cerrado por defecto')
    check('shadow_no_orders', all(not bool(r.get('order_created')) for r in shadow_rows), 'Diario Shadow contiene 0 órdenes')
    execution_mode = state.get('execution_mode')
    check('execution_mode_valid', execution_mode in ('decision','shadow','paper_auto'), f'Modo de ejecución válido: {execution_mode}')
    if execution_mode == 'paper_auto' and state.get('autonomous_engine'):
        check('paper_lifecycle_guard', bool(state.get('position_lifecycle_enabled')), 'Paper automático exige Position Lifecycle')
    else:
        check('paper_lifecycle_guard', True, 'Guard lifecycle no requerido en modo actual')

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
