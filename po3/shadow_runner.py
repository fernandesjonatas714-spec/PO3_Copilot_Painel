"""Adaptador do Decision Engine para Shadow Mode operacional.

O worker entrega somente o ``state_json`` congelado. Este módulo reconstrói um
``MarketSnapshot`` em memória, sem abrir MT5, sem ler Outcomes e sem persistir
qualquer decisão fora de ``shadow_runs``.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any

from po3.decision_engine.engine import DecisionEngine
from po3.decision_engine.market_state import MarketState
from po3.ai_service import configured_model_name, send_message_detailed


def _hydrate_market_state(state: dict[str, Any]) -> MarketState:
    """Hidrata o JSON congelado sem recalcular ou completar campos."""
    if not isinstance(state, dict):
        raise ValueError("MarketState congelado inválido: objeto JSON esperado")
    required = ("ativo", "timestamp", "preco_atual", "tecnico", "mercado_domestico",
                "mercado_externo", "calendario", "noticias", "fontes", "qualidade_dados", "snapshot")
    missing = [key for key in required if key not in state]
    if missing:
        raise ValueError(f"MarketState congelado inválido: campos ausentes {missing}")
    try:
        datetime.fromisoformat(str(state["timestamp"]).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ValueError("MarketState congelado inválido: timestamp inválido") from exc
    return MarketState(**{key: deepcopy(state[key]) for key in required})


def build_shadow_decision_runner() -> tuple[Any, str]:
    """Cria o runner real e informa o modelo configurado sem fazer chamada ainda."""
    model = configured_model_name()
    engine = DecisionEngine(send_message_detailed, model)

    def run_frozen_state(state: dict[str, Any]) -> dict[str, Any]:
        return engine.run_market_state(_hydrate_market_state(state)).to_dict()

    return run_frozen_state, model
