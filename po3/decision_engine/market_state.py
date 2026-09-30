"""Estado factual e normalizado do mercado para o Decision Engine."""
from __future__ import annotations
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Any
import json

@dataclass
class MarketState:
    ativo: str | None
    timestamp: str | None
    preco_atual: float | None
    tecnico: dict[str, Any]
    mercado_domestico: dict[str, Any]
    mercado_externo: dict[str, Any]
    calendario: dict[str, Any]
    noticias: list[dict[str, Any]]
    fontes: list[Any]
    qualidade_dados: dict[str, Any]
    snapshot: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, default=str)


def _safe_snapshot(snapshot: Any) -> dict[str, Any]:
    """Extrai somente dados factuais serializáveis, sem credenciais."""
    macro = getattr(snapshot, "macro", {}) or {}
    bars = {}
    for timeframe, rows in (getattr(snapshot, "bars", {}) or {}).items():
        bars[timeframe] = [
            {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in row.items()}
            for row in rows[-5:]
        ]
    return {
        "ativo": getattr(snapshot, "symbol", None),
        "timestamp": getattr(snapshot, "as_of", None),
        "preco_atual": getattr(snapshot, "last_price", None),
        "conectado": bool(getattr(snapshot, "connected", False)),
        "fonte": getattr(snapshot, "source", None),
        "candles": bars,
        "macro": macro,
        "niveis": {
            tf: [{"codigo": x.code, "rotulo": x.label, "valor": x.value, "grupo": x.group} for x in values]
            for tf, values in (getattr(snapshot, "levels", {}) or {}).items()
        },
        "zonas": {
            tf: [{"tipo": x.kind, "direcao": x.direction, "inferior": x.lower, "superior": x.upper, "status": x.status} for x in values]
            for tf, values in (getattr(snapshot, "zones", {}) or {}).items()
        },
    }


def build_market_state(snapshot: Any, context: dict[str, Any] | None = None) -> MarketState:
    context = context or {}
    raw = _safe_snapshot(snapshot)
    macro = raw.get("macro") or {}
    factors = macro.get("factors") or []
    leaders = macro.get("leaders") or []
    external = context.get("quotes") or {}
    calendar = context.get("calendar") or {}
    news = context.get("news") or {}
    missing = list(macro.get("missing") or [])
    if not raw.get("conectado"):
        missing.append("MT5 conectado")
    return MarketState(
        ativo=raw.get("ativo"),
        timestamp=raw.get("timestamp").isoformat() if hasattr(raw.get("timestamp"), "isoformat") else raw.get("timestamp"),
        preco_atual=raw.get("preco_atual"),
        tecnico={"candles": raw.get("candles", {}), "niveis": raw.get("niveis", {}), "zonas": raw.get("zonas", {}), "confluencia": raw.get("zonas", {}).get("M1", [])},
        mercado_domestico={"macro": macro, "fatores": factors, "lideres": leaders},
        mercado_externo=external,
        calendario=calendar,
        noticias=news.get("headlines", news.get("items", [])) if isinstance(news, dict) else [],
        fontes=news.get("statuses", []) if isinstance(news, dict) else [],
        qualidade_dados={"mt5_conectado": raw.get("conectado", False), "dados_ausentes": sorted(set(str(x) for x in missing)), "calendario_disponivel": bool(calendar.get("available", False)), "fontes_disponiveis": bool(news)},
        snapshot=raw,
    )