from __future__ import annotations
from dataclasses import dataclass, asdict

@dataclass
class DecisionGate:
    status: str
    motivos: list[str]
    mensagem: str
    def to_dict(self): return asdict(self)

def apply_gate(validation, decisions):
    if validation.bloqueado or "CALENDARIO" in validation.dados_ausentes:
        return DecisionGate("BLOQUEADO", validation.problemas or ["DADOS_CRITICOS_AUSENTES"], "Análise bloqueada: dados críticos insuficientes ou desatualizados.")
    if not decisions:
        return DecisionGate("BLOQUEADO", ["RESPOSTA_LLM_INVALIDA"], "Análise bloqueada: a resposta estruturada da IA não foi validada.")
    reasons = []
    if validation.status != "VALIDOS": reasons.append("DADOS_PARciais".upper())
    if any(d.requer_revisao or d.confianca == "BAIXA" or d.evidencias_conflitantes for d in decisions): reasons.append("REVISAO_POR_CONFIANCA_OU_CONFLITO")
    if any(d.status_evidencias == "CONFLITANTES" for d in decisions): reasons.append("CONFLITO_CRITICO_FONTES")
    if reasons: return DecisionGate("REVISAO", reasons, "Requer revisão: há dados parciais, baixa confiança ou conflito de evidências.")
    return DecisionGate("VALIDO", [], "Contexto estruturado validado; decisão operacional permanece manual.")