"""Contrato versionado das seis perguntas do Jev Shadow O5A."""
from __future__ import annotations

JEV_QUESTION_VERSION = "1.0.0"

JEV_QUESTIONS = {
    "regime_macro": {
        "type": "choice",
        "options": ["APETITE_A_RISCO", "AVERSAO_A_RISCO", "MISTO", "INDETERMINADO"],
        "question": "Classifique o regime macroeconômico atual usando somente os fatores macro presentes no estado.",
        "instructions": "Não invente fatores ausentes; responda uma única opção.",
        "criteria": {"APETITE_A_RISCO": "fatores predominantemente favoráveis a risco", "AVERSAO_A_RISCO": "fatores predominantemente defensivos", "MISTO": "sinais relevantes conflitantes", "INDETERMINADO": "dados insuficientes"},
    },
    "contexto_domestico": {
        "type": "choice",
        "options": ["POSITIVO", "NEGATIVO", "NEUTRO", "MISTO", "INDETERMINADO"],
        "question": "Classifique o contexto doméstico brasileiro relevante para WIN/B3 usando somente o estado fornecido.",
        "instructions": "Não invente notícias ou indicadores ausentes; responda uma única opção.",
        "criteria": {"POSITIVO": "contexto favorável", "NEGATIVO": "contexto desfavorável", "NEUTRO": "sem direção dominante", "MISTO": "sinais conflitantes", "INDETERMINADO": "dados insuficientes"},
    },
    "contexto_tecnico": {
        "type": "choice",
        "options": ["ALTISTA", "BAIXISTA", "NEUTRO", "CONFLITANTE", "INDETERMINADO"],
        "question": "Classifique o contexto técnico usando somente indicadores, preço, estrutura e sinais já calculados.",
        "instructions": "Não recalcule indicadores ausentes; responda uma única opção.",
        "criteria": {"ALTISTA": "estrutura favorável à alta", "BAIXISTA": "estrutura favorável à baixa", "NEUTRO": "sem direção dominante", "CONFLITANTE": "sinais técnicos conflitantes", "INDETERMINADO": "dados insuficientes"},
    },
    "risco_evento": {
        "type": "score",
        "min": 0,
        "max": 9,
        "levels": {str(i): f"Nível de risco de evento {i} de 9." for i in range(10)},
        "question": "Avalie o risco de evento usando somente eventos e calendário presentes no estado.",
        "instructions": "Escolha um nível inteiro entre 0 e 9; risco alto é informacional e não bloqueia.",
        "criteria": [f"nível {i}: risco de evento {i} de 9" for i in range(10)],
    },
    "conflito_contexto": {
        "type": "noul",
        "question": "Existe conflito relevante entre fatores técnicos, domésticos e macroeconômicos?",
        "instructions": "Informe a probabilidade numérica de conflito NOUL entre 0 e 1.",
        "criteria": {"true": "probabilidade >= 0,50 resulta em SIM", "false": "probabilidade < 0,50 resulta em NAO"},
    },
    "contexto_operacional": {
        "type": "choice",
        "options": ["CONTEXTO_COMPRADOR", "CONTEXTO_VENDEDOR", "AGUARDAR", "SEM_SETUP", "INDETERMINADO"],
        "question": "Classifique o contexto operacional sem recomendar, criar ou executar ordem.",
        "instructions": "Classifique o contexto, sem recomendar, criar ou executar ordem.",
        "criteria": {"CONTEXTO_COMPRADOR": "leitura conjunta compradora", "CONTEXTO_VENDEDOR": "leitura conjunta vendedora", "AGUARDAR": "incerteza ou conflito relevante", "SEM_SETUP": "sem configuração reconhecível", "INDETERMINADO": "dados insuficientes"},
    },
}


def build_jev_questions() -> dict:
    """Retorna uma cópia serializável para evitar mutação do contrato global."""
    import copy
    return copy.deepcopy(JEV_QUESTIONS)
