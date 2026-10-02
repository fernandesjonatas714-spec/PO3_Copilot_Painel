"""Schemas sem dependência adicional para decisões estruturadas."""
from __future__ import annotations
from dataclasses import dataclass, asdict, field
from typing import Any

DECISION_ENGINE_VERSION = "1.1.0"
PROMPT_VERSION = "1.1.0"
SCHEMA_VERSION = "1.1.0"

CHOICES = {
    "regime_macro": {"APETITE_A_RISCO", "AVERSAO_A_RISCO", "MISTO", "INDETERMINADO"},
    "contexto_domestico": {"POSITIVO", "NEGATIVO", "NEUTRO", "MISTO", "INDETERMINADO"},
    "contexto_tecnico": {"ALTISTA", "BAIXISTA", "NEUTRO", "CONFLITANTE", "INDETERMINADO"},
    "contexto_operacional": {"CONTEXTO_COMPRADOR", "CONTEXTO_VENDEDOR", "AGUARDAR", "SEM_SETUP", "INDETERMINADO"},
}
DECISION_TYPES = {"regime_macro": "CHOICE", "contexto_domestico": "CHOICE", "contexto_tecnico": "CHOICE", "risco_evento": "SCORE", "conflito_contexto": "NOUL", "contexto_operacional": "CHOICE"}

@dataclass
class Decision:
    id_decisao: str
    tipo: str
    pergunta: str
    decisao: str
    confianca: str = "BAIXA"
    status_evidencias: str = "INSUFICIENTES"
    evidencias_conflitantes: bool = False
    dados_ausentes: list[str] = field(default_factory=list)
    evidencias: list[str] = field(default_factory=list)
    requer_revisao: bool = False
    modelo_configurado: str | None = None
    modelo_utilizado: str | None = None
    fallback_utilizado: bool = False
    data_hora: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def validate_decision(item: dict[str, Any]) -> Decision:
    required = {"id_decisao", "tipo", "pergunta", "decisao"}
    if not required.issubset(item):
        raise ValueError("decisão sem campos obrigatórios")
    key, kind = str(item["id_decisao"]), str(item["tipo"])
    if key not in DECISION_TYPES or kind != DECISION_TYPES[key]:
        raise ValueError(f"tipo inválido para {key}")
    decision = str(item["decisao"]).upper()
    if kind == "CHOICE" and decision not in CHOICES[key]:
        raise ValueError(f"opção inválida para {key}")
    if kind == "NOUL" and decision not in {"SIM", "NAO", "NÃO"}:
        raise ValueError("NOUL deve ser SIM ou NÃO")
    if kind == "SCORE":
        try: score = float(decision)
        except ValueError as exc: raise ValueError("SCORE inválido") from exc
        if not 0 <= score <= 10: raise ValueError("SCORE fora da escala 0-10")
        decision = str(int(score)) if score.is_integer() else str(score)
    if str(item.get("confianca", "BAIXA")).upper() not in {"ALTA", "MEDIA", "MÉDIA", "BAIXA"}:
        raise ValueError("confiança inválida")
    status = str(item.get("status_evidencias", "INSUFICIENTES")).upper()
    if status not in {"COMPLETAS", "PARCIAIS", "INSUFICIENTES", "CONFLITANTES"}:
        raise ValueError("status de evidências inválido")
    item = dict(item)
    item["decisao"] = decision
    item["tipo"] = kind
    item["confianca"] = "MEDIA" if item.get("confianca", "").upper() in {"MÉDIA", "MEDIA"} else item.get("confianca", "BAIXA").upper()
    item["status_evidencias"] = status
    return Decision(**{k: item[k] for k in Decision.__dataclass_fields__ if k in item})
