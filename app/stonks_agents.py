"""ZAR Stonks deterministic multi-agent orchestration.

These agents are deliberately code-first: routing, market snapshots, pre-risk checks,
Paper execution and position supervision do not call an LLM and therefore consume
no model tokens. The hardened Decision/Risk endpoint remains the final authority.
"""
from dataclasses import dataclass
from datetime import datetime, timezone


def _now():
    return datetime.now(timezone.utc).isoformat()


@dataclass
class AgentResult:
    agent: str
    status: str
    detail: str = ""
    data: dict | None = None

    def as_dict(self):
        return {
            "agent": self.agent,
            "status": self.status,
            "detail": self.detail,
            "data": self.data or {},
            "timestamp": _now(),
        }


class MarketDataAgent:
    name = "market_data"

    def snapshot(self, scope_id, reconcile_fn, clock_fn):
        recon = reconcile_fn(scope_id, emit_audit=True)
        clock = clock_fn()
        return recon, clock, AgentResult(self.name, "ok", "Paper reconciliado y reloj de mercado actualizado", {
            "positions": len(recon.get("positions") or []),
            "open_orders": len(recon.get("open_orders") or []),
            "market_open": bool(clock.get("is_open")),
        }).as_dict()


class PositionManagerAgent:
    name = "position_manager"

    def run(self, scope_id, recon, clock, manage_fn):
        result = manage_fn(scope_id, recon, clock)
        return result, AgentResult(self.name, "ok", "Lifecycle de posiciones reconciliado", {
            "actions": list(result.get("actions") or [])[:20]
        }).as_dict()


class AnalysisAgent:
    name = "analysis"

    @staticmethod
    def _strength(signal):
        indicators = signal.get("indicators") or {}
        fast = indicators.get("sma20")
        slow = indicators.get("sma50")
        try:
            fast = float(fast)
            slow = float(slow)
            gap_pct = abs(fast - slow) / max(abs(slow), 1e-9) * 100.0
        except (TypeError, ValueError):
            gap_pct = 0.0
        # Technical signal strength, not a probability or forecast.
        strength = min(100.0, round(gap_pct * 25.0, 1))
        return strength, round(gap_pct, 4)

    def signal(self, symbol, strategy, timeframe, signal_fn):
        signal, _clock = signal_fn(symbol, strategy, timeframe, "iex")
        strength, gap_pct = self._strength(signal)
        return signal, AgentResult(self.name, "ok", f"{symbol}: {signal.get('signal_label') or signal.get('signal')}", {
            "symbol": symbol,
            "signal": signal.get("signal"),
            "reason": signal.get("reason"),
            "indicators": signal.get("indicators") or {},
            "signal_strength": strength,
            "sma_gap_pct": gap_pct,
        }).as_dict()


class RiskAgent:
    name = "risk"

    def precheck(self, state, clock):
        reasons = []
        if state.get("revoked"):
            reasons.append("Control revocado")
        if state.get("paused"):
            reasons.append("Motor pausado")
        if state.get("mode") != "paper":
            reasons.append("Modo no Paper")
        if state.get("execution_mode") != "paper_auto":
            reasons.append("Paper automático desactivado")
        if not state.get("autonomous_engine"):
            reasons.append("Motor autónomo desactivado")
        if not state.get("position_lifecycle_enabled"):
            reasons.append("Position Management desactivado")
        if not bool((clock or {}).get("is_open")):
            reasons.append("Mercado cerrado")
        status = "blocked" if reasons else "pass"
        gates = {
            "revoked": not bool(state.get("revoked")),
            "paused": not bool(state.get("paused")),
            "paper_mode": state.get("mode") == "paper",
            "paper_auto": state.get("execution_mode") == "paper_auto",
            "autonomous_engine": bool(state.get("autonomous_engine")),
            "position_lifecycle": bool(state.get("position_lifecycle_enabled")),
            "market_open": bool((clock or {}).get("is_open")),
        }
        return not reasons, AgentResult(self.name, status,
            "; ".join(reasons) if reasons else "Pre-check local superado; Decision/Risk servidor mantiene la autoridad final",
            {"reasons": reasons, "gates": gates}).as_dict()


class PaperExecutionAgent:
    name = "paper_execution"

    def execute(self, symbol, strategy, timeframe, signal, decision_fn):
        data = decision_fn(symbol, strategy, timeframe, signal)
        created = bool(data.get("order_created"))
        status = "executed" if created else "no_action"
        detail = data.get("primary_reason") or data.get("reason") or data.get("decision") or "Sin acción"
        return data, AgentResult(self.name, status, str(detail), {
            "symbol": symbol,
            "signal": signal,
            "order_created": created,
            "decision": data.get("decision"),
        }).as_dict()


class StonksSupervisor:
    """Coordinates specialists without changing the hardened trading authority."""
    name = "supervisor"

    def __init__(self):
        self.market = MarketDataAgent()
        self.positions = PositionManagerAgent()
        self.analysis = AnalysisAgent()
        self.risk = RiskAgent()
        self.execution = PaperExecutionAgent()

    def describe(self):
        return {
            "architecture": "deterministic_multi_agent",
            "phase": 2,
            "token_cost_router": 0,
            "paper_only": True,
            "execution_authority": "Decision + Risk server route",
            "agents": [
                {"id":"supervisor","role":"Coordina el ciclo y consolida trazas"},
                {"id":"market_data","role":"Reconcilia Paper y reloj de mercado"},
                {"id":"analysis","role":"Calcula señales técnicas"},
                {"id":"risk","role":"Pre-check local; Decision/Risk servidor es autoridad final"},
                {"id":"paper_execution","role":"Ejecuta únicamente por la ruta Paper endurecida"},
                {"id":"position_manager","role":"Gestiona lifecycle, ownership, SL/TP y reconciliación"},
            ],
        }


SUPERVISOR = StonksSupervisor()


def describe():
    return SUPERVISOR.describe()
