from __future__ import annotations
import json
from .schemas import DECISION_ENGINE_VERSION, PROMPT_VERSION, SCHEMA_VERSION

DECISION_INSTRUCTIONS = """Você atua como motor de decisões estruturadas do PO3 Copilot. Responda exclusivamente em JSON válido, sem markdown e sem narrativa. Use somente o estado factual fornecido. Não invente preços, horários, eventos, notícias ou níveis. Não altere dados ausentes. Use apenas as opções permitidas. Diferencie fato, cálculo e inferência. Não envie ordens e não substitua a decisão humana. Todos os textos devem estar em português do Brasil. Confiança é somente ALTA, MEDIA ou BAIXA; nunca é probabilidade."""

def build_decision_prompt(state: dict, validation: dict) -> str:
    ids = [
        {"id_decisao":"regime_macro","tipo":"CHOICE","pergunta":"Classifique o regime macroeconômico atual.","opcoes":["APETITE_A_RISCO","AVERSAO_A_RISCO","MISTO","INDETERMINADO"]},
        {"id_decisao":"contexto_domestico","tipo":"CHOICE","pergunta":"Classifique o contexto doméstico.","opcoes":["POSITIVO","NEGATIVO","NEUTRO","MISTO","INDETERMINADO"]},
        {"id_decisao":"contexto_tecnico","tipo":"CHOICE","pergunta":"Classifique o contexto técnico.","opcoes":["ALTISTA","BAIXISTA","NEUTRO","CONFLITANTE","INDETERMINADO"]},
        {"id_decisao":"risco_evento","tipo":"SCORE","pergunta":"Avalie o risco de evento de 0 a 10."},
        {"id_decisao":"conflito_contexto","tipo":"NOUL","pergunta":"Existe conflito relevante entre fatores técnicos, domésticos e macroeconômicos?","opcoes":["SIM","NÃO"]},
        {"id_decisao":"contexto_operacional","tipo":"CHOICE","pergunta":"Classifique o contexto operacional, sem recomendar ordem.","opcoes":["CONTEXTO_COMPRADOR","CONTEXTO_VENDEDOR","AGUARDAR","SEM_SETUP","BLOQUEADO_POR_EVENTO","INDETERMINADO"]},
    ]
    return DECISION_INSTRUCTIONS + "\nRetorne um objeto com a chave decisoes contendo exatamente os seis itens abaixo e campos: id_decisao, tipo, pergunta, decisao, confianca, status_evidencias, evidencias_conflitantes, dados_ausentes, evidencias, requer_revisao.\n" + json.dumps({"versao": [DECISION_ENGINE_VERSION, PROMPT_VERSION, SCHEMA_VERSION], "perguntas": ids, "validacao": validation, "estado": state}, ensure_ascii=False, default=str)

def build_narrative_prompt(state: dict, decisions: list[dict], gate: dict, consensus: dict, model: str | None) -> str:
    return "Responda em português do Brasil usando exclusivamente os dados abaixo. Gere exatamente três blocos: MACROECONOMIA E DIA A DIA; IMPACTO NA BOLSA; INSIGHT OPERACIONAL. Seja objetivo, diferencie fatos e inferências, não invente dados, não transforme contexto em ordem e respeite o gate. Não faça apresentação sobre sua identidade.\n" + json.dumps({"estado": state, "decisoes": decisions, "gate": gate, "consenso": consensus, "modelo": model}, ensure_ascii=False, default=str)