"""Adaptador do Decision Engine para Shadow Mode operacional.

O worker entrega somente o ``state_json`` congelado. Este módulo reconstrói um
``MarketSnapshot`` em memória, sem abrir MT5, sem ler Outcomes e sem persistir
qualquer decisão fora de ``shadow_runs``.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from po3.decision_engine.engine import DecisionEngine
from po3.models import MarketSnapshot, PriceLevel, PriceZone
from po3.ai_service import configured_model_name, send_message_detailed


def _datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc)
    if value:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            return (parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)
        except (TypeError, ValueError):
            pass
    return datetime.now(timezone.utc)


def _snapshot_from_state(state: dict[str, Any]) -> MarketSnapshot:
    """Reconstrói apenas estruturas derivadas do snapshot já congelado."""
    technical = state.get("tecnico") or {}
    levels: dict[str, list[PriceLevel]] = {}
    for timeframe, values in (technical.get("niveis") or {}).items():
        levels[timeframe] = [
            PriceLevel(str(item.get("codigo", "")), str(item.get("rotulo", "")), float(item.get("valor")), str(item.get("grupo", "")))
            for item in values or []
            if isinstance(item, dict) and item.get("valor") is not None
        ]
    zones: dict[str, list[PriceZone]] = {}
    for timeframe, values in (technical.get("zonas") or {}).items():
        zones[timeframe] = [
            PriceZone(
                kind=str(item.get("tipo", "")), direction=str(item.get("direcao", "")),
                lower=float(item.get("inferior")), upper=float(item.get("superior")),
                created_at=_datetime(item.get("criado_em") or state.get("timestamp")),
                timeframe=str(timeframe), status=str(item.get("status", "ATIVA")),
            )
            for item in values or []
            if isinstance(item, dict) and item.get("inferior") is not None and item.get("superior") is not None
        ]
    return MarketSnapshot(
        symbol=str(state.get("ativo") or ""), as_of=_datetime(state.get("timestamp")),
        last_price=state.get("preco_atual"), connected=bool((state.get("qualidade_dados") or {}).get("mt5_conectado", True)),
        source="MARKETSTATE_CONGELADO", bars=technical.get("candles") or {}, levels=levels, zones=zones,
        macro=(state.get("mercado_domestico") or {}).get("macro") or {},
    )


def build_shadow_decision_runner() -> tuple[Any, str]:
    """Cria o runner real e informa o modelo configurado sem fazer chamada ainda."""
    model = configured_model_name()
    engine = DecisionEngine(send_message_detailed, model)

    def run_frozen_state(state: dict[str, Any]) -> dict[str, Any]:
        snapshot = _snapshot_from_state(state)
        context = {
            "quotes": state.get("mercado_externo") or {},
            "calendar": state.get("calendario") or {},
            "news": {"headlines": state.get("noticias") or [], "statuses": state.get("fontes") or []},
        }
        return engine.run(snapshot, context).to_dict()

    return run_frozen_state, model

