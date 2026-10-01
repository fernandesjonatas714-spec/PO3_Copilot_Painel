from __future__ import annotations
from dataclasses import dataclass, asdict
from datetime import datetime
from zoneinfo import ZoneInfo
from .market_state import MarketState

@dataclass
class ValidationResult:
    status: str
    problemas: list[str]
    dados_ausentes: list[str]
    atualidade_minutos: float | None
    def to_dict(self): return asdict(self)
    @property
    def bloqueado(self): return self.status in {"INSUFICIENTES", "DESATUALIZADOS"}


def validate_market_state(state: MarketState, max_age_minutes: int = 30) -> ValidationResult:
    problemas, ausentes = [], list(state.qualidade_dados.get("dados_ausentes", []))
    if not state.ativo: problemas.append("ATIVO_AUSENTE")
    if state.preco_atual is None: problemas.append("PRECO_AUSENTE")
    if not state.qualidade_dados.get("mt5_conectado"): problemas.append("MT5_DESATUALIZADO")
    age = None
    try:
        stamp = datetime.fromisoformat(str(state.timestamp))
        now = datetime.now(stamp.tzinfo or ZoneInfo("America/Sao_Paulo"))
        age = max(0.0, (now - stamp).total_seconds() / 60)
        if age > max_age_minutes: problemas.append("DADOS_DESATUALIZADOS")
    except (TypeError, ValueError): problemas.append("TIMESTAMP_INVALIDO")
    if not state.qualidade_dados.get("calendario_disponivel"): ausentes.append("CALENDARIO")
    if problemas and any(x in problemas for x in ("MT5_DESATUALIZADO", "PRECO_AUSENTE", "ATIVO_AUSENTE", "DADOS_DESATUALIZADOS")):
        status = "DESATUALIZADOS" if "DADOS_DESATUALIZADOS" in problemas else "INSUFICIENTES"
    elif problemas or ausentes: status = "PARCIAIS"
    else: status = "VALIDOS"
    return ValidationResult(status, sorted(set(problemas)), sorted(set(ausentes)), age)