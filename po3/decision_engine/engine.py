from __future__ import annotations
from dataclasses import dataclass, asdict
import json, re
from datetime import datetime
from .market_state import MarketState, build_market_state
from .validator import validate_market_state
from .schemas import Decision, validate_decision, DECISION_ENGINE_VERSION, PROMPT_VERSION, SCHEMA_VERSION
from .prompts import build_decision_prompt
from .gate import apply_gate
from .consensus import compare

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
    def to_dict(self):
        return {"versoes":{"decision_engine":DECISION_ENGINE_VERSION,"prompt":PROMPT_VERSION,"schema":SCHEMA_VERSION},"state":self.state.to_dict(),"validation":self.validation.to_dict(),"decisoes":[x.to_dict() for x in self.decisions],"segunda_analise":[x.to_dict() for x in self.second_decisions],"gate":self.gate.to_dict(),"consenso":self.consensus,"modelo_configurado":self.model_configured,"modelo_utilizado":self.model_used,"fallback_utilizado":self.fallback_used,"erro":self.error}

class DecisionEngine:
    def __init__(self, send_detailed, configured_model): self.send_detailed=send_detailed; self.configured_model=configured_model
    def _parse(self, text, meta):
        match=re.search(r"\{.*\}", text or "", re.S)
        if not match: raise ValueError("JSON estruturado não encontrado")
        obj=json.loads(match.group(0)); raw=obj.get("decisoes")
        if not isinstance(raw,list) or len(raw)!=6: raise ValueError("a resposta não contém exatamente seis decisões")
        out=[]
        for item in raw:
            item=dict(item); item.update({"modelo_configurado":meta.get("model_configured"),"modelo_utilizado":meta.get("model_used"),"fallback_utilizado":meta.get("fallback_used",False),"data_hora":datetime.now().astimezone().isoformat()}); out.append(validate_decision(item))
        return out
    def _call(self, state, validation):
        result=self.send_detailed(build_decision_prompt(state.to_dict(), validation.to_dict()))
        return self._parse(result["content"], result), result
    def run(self, snapshot, context):
        state=build_market_state(snapshot, context); validation=validate_market_state(state)
        gate=apply_gate(validation, []) if validation.bloqueado else None
        if gate:
            return StructuredAnalysis(state,validation,[],[],gate,{"status":"NAO_EXECUTADA","divergencias":[]},None,None,False,error="dados insuficientes")
        try: decisions, meta=self._call(state, validation)
        except Exception as exc:
            gate=apply_gate(validation, []); return StructuredAnalysis(state,validation,[],[],gate,{"status":"NAO_EXECUTADA","divergencias":[]},None,None,False,error=str(exc))
        gate=apply_gate(validation, decisions)
        second=[]
        if gate.status=="REVISAO" or any(x.confianca=="BAIXA" for x in decisions):
            try: second,_=self._call(state, validation)
            except Exception: second=[]
        consensus=compare(decisions, second)
        return StructuredAnalysis(state,validation,decisions,second,gate,consensus,meta.get("model_configured"),meta.get("model_used"),bool(meta.get("fallback_used")),error=None)