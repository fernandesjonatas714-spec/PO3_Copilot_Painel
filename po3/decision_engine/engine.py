from __future__ import annotations

from dataclasses import dataclass
import inspect
import json
import re
from datetime import datetime

from .market_state import MarketState, build_market_state
from .validator import validate_market_state
from .schemas import Decision, validate_decision, DECISION_ENGINE_VERSION, PROMPT_VERSION, SCHEMA_VERSION
from .prompts import build_decision_prompt, build_repair_prompt
from .gate import apply_gate
from .consensus import compare
from po3.ai_service import FREE_MODEL_PRIORITY

EXPECTED_DECISION_IDS = {"regime_macro", "contexto_domestico", "contexto_tecnico", "risco_evento", "conflito_contexto", "contexto_operacional"}

@dataclass
class StructuredAnalysis:
    state: MarketState
    validation: object
    decisions: list[Decision]
    second_decisions: list[Decision]
    gate: object
    consensus: dict
    model_configured: str | None
    model_used: str | None
    fallback_used: bool
    narrative: str | None = None
    error: str | None = None
    second_model_used: str | None = None
    second_fallback_used: bool = False
    repair_used: bool = False
    model_attempts: list[str] | None = None
    second_model_attempts: list[str] | None = None
    narrative_model_used: str | None = None
    narrative_fallback_used: bool = False

    def to_dict(self):
        return {"versoes": {"decision_engine": DECISION_ENGINE_VERSION, "prompt": PROMPT_VERSION, "schema": SCHEMA_VERSION}, "state": self.state.to_dict(), "validation": self.validation.to_dict(), "decisoes": [x.to_dict() for x in self.decisions], "segunda_analise": [x.to_dict() for x in self.second_decisions], "gate": self.gate.to_dict(), "consenso": self.consensus, "modelo_configurado": self.model_configured, "modelo_utilizado": self.model_used, "model_used": self.model_used, "decision_model_used": self.model_used, "decision_model_attempts": self.model_attempts or [], "decision_fallback_used": self.fallback_used, "decision_repair_used": self.repair_used, "model_attempts": self.model_attempts or [], "fallback_utilizado": self.fallback_used, "segunda_modelo_utilizado": self.second_model_used, "segunda_model_attempts": self.second_model_attempts or [], "segunda_fallback_utilizado": self.second_fallback_used, "reparo_json_utilizado": self.repair_used, "narrative_model_used": self.narrative_model_used, "narrative_fallback_used": self.narrative_fallback_used, "modelo_narrativa_utilizado": self.narrative_model_used, "fallback_narrativa_utilizado": self.narrative_fallback_used, "narrativa": self.narrative, "erro": self.error}

class DecisionEngine:
    def __init__(self, send_detailed, configured_model):
        self.send_detailed = send_detailed
        self.configured_model = configured_model
        self.last_attempts = []
        self.last_repair_used = False

    def _supports_model_selection(self) -> bool:
        try:
            parameters = inspect.signature(self.send_detailed).parameters.values()
            return any(parameter.name == "model_override" or
                       parameter.kind == inspect.Parameter.VAR_KEYWORD
                       for parameter in parameters)
        except (TypeError, ValueError):
            return False

    def _request(self, message: str, model: str):
        if self._supports_model_selection():
            return self.send_detailed(message, model_override=model, allow_model_fallback=False)
        return self.send_detailed(message)

    def _parse(self, text, meta):
        match = re.search(r"\{.*\}", text or "", re.S)
        if not match:
            raise ValueError("JSON estruturado nao encontrado")
        obj = json.loads(match.group(0)); raw = obj.get("decisoes")
        if not isinstance(raw, list) or len(raw) != 6:
            raise ValueError("a resposta nao contem exatamente seis decisoes")
        received_ids = {str(item.get("id_decisao")) for item in raw if isinstance(item, dict)}
        if received_ids != EXPECTED_DECISION_IDS:
            raise ValueError("a resposta nao contem as seis decisoes obrigatorias")
        out = []
        for item in raw:
            item = dict(item); item.update({"modelo_configurado": meta.get("model_configured"), "modelo_utilizado": meta.get("model_used"), "fallback_utilizado": meta.get("fallback_used", False), "data_hora": datetime.now().astimezone().isoformat()}); out.append(validate_decision(item))
        return out

    def _call(self, state, validation):
        prompt = build_decision_prompt(state.to_dict(), validation.to_dict()); candidates = [self.configured_model]
        if self._supports_model_selection():
            candidates += [m for m in FREE_MODEL_PRIORITY if m != self.configured_model and m.endswith(":free")]
        attempts = []; last_error = None; repair_used_any = False
        self.last_attempts = attempts
        self.last_repair_used = False
        for candidate in candidates:
            attempts.append(candidate)
            try:
                result = dict(self._request(prompt, candidate) or {}); result.setdefault("model_configured", self.configured_model); result.setdefault("model_used", candidate); result["fallback_used"] = bool(result.get("fallback_used")) or candidate != self.configured_model; result["model_attempts"] = list(attempts)
                try:
                    return self._parse(result["content"], result), result, repair_used_any
                except Exception as first_error:
                    repair_used_any = True
                    self.last_repair_used = True
                    repaired = dict(self._request(build_repair_prompt(result.get("content", ""), str(first_error)), candidate) or {}); repaired.setdefault("model_configured", self.configured_model); repaired.setdefault("model_used", candidate); repaired["fallback_used"] = bool(repaired.get("fallback_used")) or candidate != self.configured_model; repaired["model_attempts"] = list(attempts)
                    try:
                        return self._parse(repaired["content"], repaired), repaired, repair_used_any
                    except Exception as repair_error:
                        last_error = repair_error
            except Exception as exc:
                last_error = exc
        raise ValueError("nenhum modelo produziu JSON estruturado valido") from last_error

    def run(self, snapshot, context):
        return self.run_market_state(build_market_state(snapshot, context))

    def run_market_state(self, state: MarketState):
        validation = validate_market_state(state); gate = apply_gate(validation, []) if validation.bloqueado else None
        # Calendário ausente é dado crítico mesmo quando a validação geral fica
        # em PARCIAIS. O bloqueio precisa ocorrer antes de qualquer chamada LLM.
        if validation.bloqueado or "CALENDARIO" in validation.dados_ausentes:
            gate = apply_gate(validation, [])
            return StructuredAnalysis(state, validation, [], [], gate, {"status": "NAO_EXECUTADA", "divergencias": []}, None, None, False, error="DADOS_CRITICOS_AUSENTES", model_attempts=[])
        try:
            decisions, meta, repaired = self._call(state, validation)
        except Exception:
            gate = apply_gate(validation, []); return StructuredAnalysis(state, validation, [], [], gate, {"status": "NAO_EXECUTADA", "divergencias": []}, self.configured_model, None, False, error="RESPOSTA_LLM_INVALIDA", repair_used=self.last_repair_used, model_attempts=list(self.last_attempts))
        gate = apply_gate(validation, decisions); second, second_meta, second_repaired = [], {}, False
        if gate.status == "REVISAO" or any(x.confianca == "BAIXA" for x in decisions):
            try: second, second_meta, second_repaired = self._call(state, validation)
            except Exception: second = []
        return StructuredAnalysis(state, validation, decisions, second, gate, compare(decisions, second), meta.get("model_configured"), meta.get("model_used"), bool(meta.get("fallback_used")), error=None, second_model_used=second_meta.get("model_used"), second_fallback_used=bool(second_meta.get("fallback_used")), repair_used=repaired or second_repaired, model_attempts=meta.get("model_attempts", []), second_model_attempts=second_meta.get("model_attempts", []))
