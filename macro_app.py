from __future__ import annotations

from datetime import datetime
import json
import os
import sqlite3
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
import re

from po3.mt5_reader import MT5ReadError, read_snapshot
from po3.external_data import fetch_official_calendar, fetch_daily_context, filter_relevant_events, get_next_high_impact_event
from po3.ai_service import OpenRouterError, configured_model_name, send_message, send_message_detailed
from po3.decision_engine import DecisionEngine
from po3.decision_engine.narrative import generate_narrative
from po3.learning_store import record_ai_error, recent_analyses, save_analysis
from po3.analytics import build_evaluation_report
from po3.v2_config import EVALUATION_ENGINE_ENABLED, JEV_SHADOW_ENABLED, SUPERVISOR_AI_ENABLED
from po3.jev_comparison import compare_market_state
from po3.operational_supervisor import build_supervisor_snapshot, supervisor_ai_context, supervisor_ai_gate

DEFAULT_TERMINAL = r"C:\Program Files\Clear Investimentos MT5 Terminal\terminal64.exe"

st.set_page_config(page_title="PO3 Copilot B3", page_icon=":material/monitoring:", layout="wide")
st.markdown("""
<style>
.stApp{background:#0d1117;color:#e6edf3}.block-container{max-width:1480px;padding:.55rem 1rem 1rem}
[data-testid="stSidebar"]{background:#11161d;border-right:1px solid #30363d}
.brand{display:flex;align-items:center;gap:.8rem;margin:.2rem 0 1.25rem}.brand-mark{width:40px;height:40px;border-radius:12px;background:#0b7d3e;color:white;display:grid;place-items:center;font-weight:800;font-size:1.15rem}.brand-title{font-size:1.18rem;font-weight:800;line-height:1.1}.brand-sub{color:#758093;font-size:.72rem;letter-spacing:.08em;text-transform:uppercase;margin-top:.22rem}
.topline{display:flex;justify-content:space-between;align-items:center;margin-bottom:.7rem}.asset-title{font-size:1.55rem;font-weight:800}.asset-meta{color:#8b949e;font-size:.82rem}.live-dot{display:inline-block;width:8px;height:8px;border-radius:50%;background:#3fb950;margin-right:6px}.source-chip{display:inline-flex;gap:.35rem;align-items:center;background:#161b22;color:#aab4c3;border:1px solid #30363d;border-radius:999px;padding:.3rem .65rem;font-size:.72rem;font-weight:600}
.period{background:#161b22;border:1px solid #30363d;border-radius:9px;padding:.75rem .65rem;text-align:center;min-height:66px}.period.active{background:#1b2734;border:1.5px solid #3b82f6;box-shadow:0 3px 10px #1373e12b}.period strong{display:block;color:#f0f6fc;font-size:.83rem}.period span{display:block;color:#3fb950;font-size:.7rem;font-weight:700;margin-top:.2rem}.period.off span{color:#8b949e;font-weight:500}
.period span.sell{color:#ff7b72}.period span.neutral{color:#f4c45d}.period span.nodata{color:#8b949e;font-weight:500}
.section-title{font-size:.93rem;font-weight:800;margin:.35rem 0 .7rem}.muted{color:#8b949e;font-size:.78rem}.card{background:#161b22;border:1px solid #30363d;border-radius:14px;padding:1rem 1.05rem;box-shadow:0 2px 10px #0008;height:100%}.card-head{display:flex;justify-content:space-between;align-items:center;font-weight:700;color:#f0f6fc}.card-head span{color:#8b949e;font-size:.75rem;font-weight:500}
.gauge-wrap{text-align:center;padding:.1rem 0 .2rem}.gauge{width:156px;height:78px;margin:.35rem auto .55rem;border-radius:156px 156px 0 0;background:conic-gradient(from 270deg at 50% 100%,#e53935 0deg,#efb14b 78deg,#dfe4e8 90deg,#72bf94 102deg,#00883e 180deg);position:relative;overflow:hidden}.gauge:after{content:'';position:absolute;inset:13px 13px 0;border-radius:143px 143px 0 0;background:#161b22}.needle{position:absolute;z-index:2;bottom:0;left:50%;width:3px;height:62px;background:#aab4c3;transform-origin:bottom center;border-radius:3px;transform:rotate(var(--rot))}.hub{position:absolute;z-index:3;bottom:-4px;left:calc(50% - 5px);width:10px;height:10px;border-radius:50%;background:#aab4c3}.gauge-value{font-size:1.05rem;font-weight:800;margin-bottom:.2rem}.pill{display:inline-block;border-radius:999px;padding:.38rem .8rem;background:#123522;color:#56d68c;font-weight:800;font-size:.8rem}.pill.red{background:#3a1e25;color:#ff8d9a}.pill.yellow{background:#3d3017;color:#f4c45d}.summary{font-size:1.6rem;font-weight:800;margin:.75rem 0 .3rem}.summary.green{color:#56d68c}.summary.red{color:#ff8d9a}.summary.yellow{color:#f4c45d}.notice{border-radius:10px;padding:.65rem .8rem;background:#202733;color:#aab4c3;font-size:.78rem;margin-top:.75rem}.notice.green{background:#123522;color:#56d68c}.notice.red{background:#3a1e25;color:#ff8d9a}
.kpi-grid{display:grid;grid-template-columns:repeat(6,1fr);gap:.45rem;margin:.35rem 0 .6rem}.kpi{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:.42rem .55rem;min-height:45px}.kpi span{display:block;color:#8b949e;font-size:.64rem}.kpi strong{display:block;color:#f0f6fc;font-size:.86rem;margin-top:.15rem}.kpi strong.positive{color:#3fb950}.kpi strong.negative{color:#ff7b72}
.main-grid{display:grid;grid-template-columns:1.1fr 1fr 1.15fr;gap:.55rem;margin:.45rem 0}.bottom-grid{display:grid;grid-template-columns:1.55fr 1fr;gap:.55rem;margin-top:.55rem}.panel-card{background:#161b22;border:1px solid #30363d;border-radius:10px;padding:.55rem .65rem;min-height:0}.center-panel{display:flex;flex-direction:column;align-items:center}.center-panel .gauge-wrap{transform:scale(.83);transform-origin:top center;margin-bottom:-1.15rem}.panel-title{font-size:.78rem;font-weight:800;color:#f0f6fc;margin-bottom:.4rem}.tf-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:.35rem}.tf-card{background:#202733;border:1px solid #30363d;border-radius:7px;padding:.42rem .3rem;text-align:center;min-height:42px}.tf-card b{display:block;color:#f0f6fc;font-size:.7rem}.tf-card span{display:block;color:#8b949e;font-size:.63rem;margin-top:.12rem;font-weight:700}.tf-card.positive span{color:#3fb950}.tf-card.negative span{color:#ff7b72}.tf-card.neutral span{color:#f4c45d}.tf-card.active{border-color:#3b82f6;background:#1b2734}.compact-table{width:100%;border-collapse:collapse;font-size:.66rem}.compact-table th{color:#8b949e;text-align:left;font-weight:600;padding:.24rem .25rem;border-bottom:1px solid #30363d}.compact-table td{padding:.24rem .25rem;color:#d1d5db;border-bottom:1px solid #242a33}.compact-table td.positive{color:#3fb950;font-weight:700}.compact-table td.negative{color:#ff7b72;font-weight:700}.compact-table td.neutral{color:#f4c45d;font-weight:700}.compact-table td.high-impact{color:#ff7b72;font-weight:800}.compact-table td.medium-impact{color:#f4c45d;font-weight:800}.compact-table td.low-impact{color:#8b949e}.use-list{margin:.15rem 0 .45rem;padding-left:1.15rem;color:#c9d1d9;font-size:.7rem;line-height:1.5}.empty{color:#8b949e;font-size:.7rem}@media (max-width:1100px){.kpi-grid{grid-template-columns:repeat(3,1fr)}.main-grid,.bottom-grid{grid-template-columns:1fr}.center-panel{align-items:stretch}}
.question-button button{font-size:.60rem!important;line-height:1.05!important;padding:.16rem .28rem!important;min-height:0!important;height:25px!important;margin:0!important}.question-button{margin-bottom:.12rem!important}
div[data-testid="stButton"] button{font-size:.60rem!important;line-height:1.05!important;padding:.16rem .28rem!important;min-height:0!important;height:25px!important}
.ai-status{color:#3fb950;font-size:.78rem;font-weight:800;margin-bottom:.35rem}
.daily-analysis{font-size:.78rem;line-height:1.42;color:#d1d5db}.daily-analysis h1,.daily-analysis h2,.daily-analysis h3{font-size:.9rem;color:#f0f6fc;margin:.45rem 0 .25rem}.daily-analysis ul{margin:.15rem 0 .35rem;padding-left:1.1rem}.daily-analysis strong{color:#f0f6fc}
</style>
""", unsafe_allow_html=True)


def score_value(value) -> float:
    try:
        return max(-100.0, min(100.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def bias(score: float) -> tuple[str, str]:
    if score >= 20: return "Compra Forte", "green"
    if score >= 7: return "Compra", "green"
    if score <= -20: return "Venda Forte", "red"
    if score <= -7: return "Venda", "red"
    return "Neutro", "yellow"


def gauge(label: str, score: float, note: str, large: bool = False) -> str:
    name, tone = bias(score)
    rot = (score / 100.0) * 90
    size = "width:200px;height:100px" if large else ""
    pill_class = "" if tone == "green" else tone
    return f'''<div class="gauge-wrap"><div class="muted">{label}</div><div class="gauge" style="--rot:{rot:.1f}deg;{size}"><div class="needle"></div><div class="hub"></div></div><div class="gauge-value">{name}</div><span class="pill {pill_class}">{score:+.1f}</span><div class="muted" style="margin-top:.45rem">{note}</div></div>'''


def pct(value):
    return "—" if value is None else f"{float(value)*100:+.2f}%"


def sign_style(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return ""
    if number > 0:
        return "color: #3fb950; font-weight: 700"
    if number < 0:
        return "color: #ff7b72; font-weight: 700"
    return "color: #f4c45d; font-weight: 700"


def _tone_class(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "neutral"
    return "positive" if number > 0 else "negative" if number < 0 else "neutral"


def _compact_table(headers, rows, numeric_columns=()):
    head = "".join(f"<th>{h}</th>" for h in headers)
    body = []
    for row in rows:
        cells = []
        for index, value in enumerate(row):
            impact = str(value).upper()
            cls = "high-impact" if impact == "ALTO" else "medium-impact" if impact == "MÉDIO" else "low-impact" if impact == "BAIXO" else (_tone_class(value) if index in numeric_columns else "")
            cells.append(f'<td class="{cls}">{value}</td>')
        body.append("<tr>" + "".join(cells) + "</tr>")
    return f'<table class="compact-table"><thead><tr>{head}</tr></thead><tbody>{"".join(body)}</tbody></table>'


@st.cache_data(ttl=1800, show_spinner=False)
def _economic_calendar():
    return fetch_official_calendar()


@st.cache_data(ttl=900, show_spinner=False)
def _external_context():
    """Atualiza calendário e manchetes para o chat IA sem consultar a cada interação."""
    return fetch_daily_context()


def _daily_analysis_prompt(snapshot, context) -> str:
    macro = snapshot.macro or {}
    payload = {
        "data_consulta": datetime.now().astimezone().isoformat(),
        "ativo": snapshot.symbol,
        "preco_mt5": snapshot.last_price,
        "macro_mt5": macro,
        "calendario": context.get("calendar", {}),
        "manchetes_fontes_permitidas": context.get("news", {}),
        "cotacoes_externas_autorizadas": context.get("quotes", {}),
        "regras_indicadores": {
            "PO3_D1_Objetivos_M15": "Somente FVG no timeframe do gráfico (M15 ou D1), até 6 zonas mais recentes. Toque ou pavio não mitiga; somente fechamento além do limite invalida o FVG.",
            "PO3_Confluencia_M15_M5_M1": "Usa M5 e M15 somente como contexto interno: exige zona maior válida e, depois, zona M1 totalmente dentro dela e na mesma direção. No gráfico M1, exibe somente a zona de confirmação M1; não interpretar áreas macro desenhadas pelo indicador. Toque/pavio não invalida, fechamento além do limite invalida; entrada no centro da zona M1; risco mínimo de 10 pontos; níveis operacionais no M1.",
        },
    }
    return json.dumps(_json_safe(payload), ensure_ascii=False, default=str)


def _json_safe(value, seen=None):
    """Converte dados do painel sem quebrar quando houver referência circular."""
    if seen is None:
        seen = set()
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    marker = id(value)
    if marker in seen:
        return "[referência circular omitida]"
    if isinstance(value, dict):
        seen.add(marker)
        result = {str(key): _json_safe(item, seen) for key, item in value.items()}
        seen.remove(marker)
        return result
    if isinstance(value, (list, tuple, set)):
        seen.add(marker)
        result = [_json_safe(item, seen) for item in value]
        seen.remove(marker)
        return result
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _run_daily_analysis_legacy(snapshot, context=None):
    context = context or fetch_daily_context()
    answer = send_message(
        "Faça uma análise diária limpa e objetiva para operar o WIN usando exclusivamente os dados JSON abaixo. "
        "Responda em português, sem apresentação sobre quem você é, sem repetir que a execução é manual, sem seção de limitações, "
        "sem listar erros técnicos das fontes e sem repetir o JSON. Só explique sua identidade se o usuário perguntar diretamente. "
        "Mantenha exatamente estes três blocos: MACROECONOMIA E DIA A DIA; IMPACTO NA BOLSA; INSIGHT OPERACIONAL. "
        "Inclua cenário Brasil/exterior, dólar, juros, petróleo, bolsas, fatores do WIN, eventos com data/horário/valores, "
        "sentimento da Bolsa, líderes, convergência entre tempos e cenários de compra/venda. "
        "Regra obrigatória: para operações no WIN, considerar o viés do dia como vendedor/defensivo quando o cenário "
        "macro estiver negativo ou misto, exigindo confirmação técnica antes de qualquer entrada. Mesmo em viés comprador, "
        "a entrada depende do setup técnico e da decisão manual. Diferencie fato de inferência, não invente dados e escreva "
        "apenas 'sem leitura' no item correspondente quando faltar informação essencial. Não envie ordens nem dê garantia. "
        "Use somente o campo horario_leitura do JSON como horário da análise; não invente, recalcule ou substitua esse horário. "
        "Se o horário não estiver disponível, escreva 'horário não disponível'.\n\n" +
        _daily_analysis_prompt(snapshot, context),
        system_instruction=(
            "REGRA ABSOLUTA: responda sempre e exclusivamente em português do Brasil. Não use inglês em títulos, frases, rótulos ou explicações; preserve apenas nomes próprios, símbolos e nomes oficiais de fontes. "
            "Você é o analista macro do PO3 Copilot B3. Use somente o JSON fornecido. "
            "O painel é somente leitura e a decisão é manual. Fontes permitidas: InfoMoney, Valor Econômico, "
            "Investing.com Brasil, E-Investidor Estadão, Money Times, TradingView, Investing.com, Yahoo Finance, "
            "CNBC, MarketWatch e CME Group; calendário do Investing. "
            "Controle internamente a qualidade das fontes, sem listar limitações técnicas na resposta. Nunca trate a previsão como resultado realizado. "
            "Regra anti-alucinação: use exclusivamente os valores presentes no JSON. Não complete lacunas com memória, estimativa ou conhecimento externo. "
            "Prioridade: MT5 para WIN, DOL, IBOV, juros e fatores do painel; depois calendário autorizado; depois manchetes e cotações externas autorizadas. "
            "Se um dado não estiver presente, responda 'não disponível'. Use horario_leitura como único horário oficial; não escreva outro horário nem faça nova conversão. "
            "Não inclua frases introdutórias sobre ser o PO3 Copilot, interpretar MT5, não executar ordens ou exigir decisão manual. "
            "Essas informações só devem aparecer se o usuário perguntar diretamente sobre sua identidade ou função. "
            "Para WIN, DOL, IBOV, juros e fatores macro do painel, priorize os dados atuais do MT5. Para Nasdaq, S&P 500, VIX, Gold e petróleo, "
            "use as cotações externas autorizadas no JSON. Quando responder, use ✅ para fato confirmado, ⚠️ para atenção e 🔎 para inferência. "
            "Marque como fato somente o que estiver no JSON e como inferência toda interpretação. "
            "Antes do horário do evento, o viés é provável e compara previsão com anterior; após o horário, o viés "
            "confirmado compara atual com previsão. Preserve exatamente a estrutura solicitada: os três blocos MACROECONOMIA E DIA A DIA, IMPACTO NA BOLSA e INSIGHT OPERACIONAL, nessa ordem. Não crie novos blocos nem troque os títulos."
        ),
    )
    return answer, context


def _decision_engine_enabled() -> bool:
    return os.getenv("DECISION_ENGINE_ENABLED", "true").strip().lower() not in {"0", "false", "nao", "não", "off"}


def _run_daily_analysis(snapshot):
    context = fetch_daily_context()
    if not _decision_engine_enabled():
        return _run_daily_analysis_legacy(snapshot, context)
    try:
        def detailed(message, **kwargs):
            return send_message_detailed(
                message,
                **kwargs,
                system_instruction="Responda exclusivamente em JSON válido, em português do Brasil, conforme o schema solicitado. Não invente dados e não produza narrativa.",
            )
        structured = DecisionEngine(detailed, configured_model_name()).run(snapshot, context)
        if structured.decisions and not structured.error:
            def narrative_call(message):
                return send_message_detailed(message, system_instruction="Responda somente com os três blocos narrativos solicitados, sempre em português do Brasil. Não invente dados.")
            narrative_result = generate_narrative(narrative_call, structured.state, structured.decisions, structured.gate, structured.consensus, structured.model_used)
            structured.narrative = narrative_result["content"]
            structured.model_used = narrative_result.get("model_used") or structured.model_used
            structured.fallback_used = structured.fallback_used or bool(narrative_result.get("fallback_used"))
            return structured.narrative, {**context, "_structured": structured.to_dict()}
        answer, legacy_context = _run_daily_analysis_legacy(snapshot, {**context, "_structured": structured.to_dict()})
        return answer, {**legacy_context, "_structured": structured.to_dict()}
    except Exception as exc:
        return _run_daily_analysis_legacy(snapshot, {**context, "_structured_error": type(exc).__name__})


def _render_structured_summary(data: dict) -> None:
    if not data:
        return
    gate = data.get("gate", {})
    validation = data.get("validation", {})
    decision_rows = {x.get("id_decisao"): x for x in data.get("decisoes", [])}
    decisions = {key: row.get("decisao") for key, row in decision_rows.items()}
    labels = {
        "APETITE_A_RISCO": "Apetite a risco", "AVERSAO_A_RISCO": "Aversão a risco", "MISTO": "Misto",
        "INDETERMINADO": "Indeterminado", "POSITIVO": "Positivo", "NEGATIVO": "Negativo", "NEUTRO": "Neutro",
        "ALTISTA": "Altista", "BAIXISTA": "Baixista", "CONFLITANTE": "Conflitante",
        "CONTEXTO_COMPRADOR": "Contexto comprador", "CONTEXTO_VENDEDOR": "Contexto vendedor",
        "AGUARDAR": "Aguardar confirmação", "SEM_SETUP": "Sem setup válido",
        "SIM": "Sim", "NAO": "Não", "NÃO": "Não",
    }
    def label(key):
        return labels.get(str(decisions.get(key, "INDETERMINADO")), str(decisions.get(key, "Indisponível")))
    with st.expander("Decisão estruturada", expanded=False):
        cols = st.columns(3)
        cols[0].metric("Regime macro", label("regime_macro"))
        cols[1].metric("Contexto doméstico", label("contexto_domestico"))
        cols[2].metric("Contexto técnico", label("contexto_tecnico"))
        cols = st.columns(3)
        cols[0].metric("Risco de evento", decisions.get("risco_evento", "—"))
        cols[1].metric("Conflito de contexto", label("conflito_contexto"))
        cols[2].metric("Contexto operacional", label("contexto_operacional"))
        rank = {"BAIXA": 0, "MÉDIA": 1, "MEDIA": 1, "ALTA": 2}
        confidences = [str(row.get("confianca", "BAIXA")).upper() for row in decision_rows.values()]
        conservative = min(confidences, key=lambda value: rank.get(value, 0)) if confidences else "BAIXA"
        confidence_label = {"ALTA": "Alta", "MÉDIA": "Média", "MEDIA": "Média", "BAIXA": "Baixa"}.get(conservative, "Baixa")
        evidence = [str(row.get("status_evidencias", "INSUFICIENTES")).title() for row in decision_rows.values()]
        evidence_label = ", ".join(sorted(set(evidence))) if evidence else "Indisponível"
        data_label = str(validation.get("status", "INDISPONÍVEIS")).title()
        st.caption(f"Confiança geral conservadora: {confidence_label}")
        st.caption(f"Qualidade dos dados: {data_label} · Qualidade das evidências: {evidence_label}")
        st.caption(f"Status do Decision Gate: {str(gate.get('status', 'BLOQUEADO')).title()}")
        st.caption(f"Modelo realmente utilizado: {data.get('modelo_utilizado') or 'não disponível'}")
        st.caption(f"Fallback utilizado: {'Sim' if data.get('fallback_utilizado') else 'Não'}")
        consensus = data.get("consenso", {}).get("status")
        if consensus and consensus != "NAO_EXECUTADA":
            text = "consenso" if consensus == "CONSENSO" else "divergência — revisão recomendada"
            second_model = data.get("segunda_modelo_utilizado") or "não disponível"
            st.caption(f"Segunda análise: executada · modelo {second_model} · {text}")
        else:
            st.caption("Segunda análise: não acionada · consenso/divergência: não aplicável")
        if data.get("reparo_json_utilizado"):
            st.caption("Reparo controlado do JSON: utilizado uma vez")


def _render_audio_button(text: str) -> None:
    """Botão de leitura local; o navegador fala sem enviar o texto a outro serviço."""
    clean = re.sub(r"[✅⚠️🔎📅📋❌✔️☑️]", "", str(text))
    clean = re.sub(r"[*_`#]+", "", clean)
    clean = re.sub(r"\s+", " ", clean).strip()
    payload = json.dumps(clean, ensure_ascii=False)
    components.html(
        f"""
        <button id="po3-speak" style="border:1px solid #3b82f6;background:#1b2734;color:#e6edf3;border-radius:8px;padding:7px 12px;cursor:pointer;font-weight:700">🔊 Ouvir análise</button>
        <button id="po3-stop" style="border:1px solid #30363d;background:#161b22;color:#aab4c3;border-radius:8px;padding:7px 12px;cursor:pointer;margin-left:6px">■ Parar</button>
        <script>
        const po3Text = {payload};
        const speak = () => {{ const synth=window.speechSynthesis; synth.cancel(); const voices=synth.getVoices(); const preferred=['Microsoft Francisca Online (Natural) - Portuguese (Brazil)','Microsoft Francisca - Portuguese (Brazil)','Google português do Brasil','Microsoft Maria - Portuguese (Brazil)']; const voice=preferred.map(n=>voices.find(v=>v.name===n)).find(Boolean) || voices.find(v=>/^pt-BR/i.test(v.lang)) || voices.find(v=>/^pt/i.test(v.lang)); const u=new SpeechSynthesisUtterance(po3Text); u.lang='pt-BR'; if(voice) u.voice=voice; u.rate=0.88; u.pitch=1.04; u.volume=1; synth.speak(u); }};
        document.getElementById('po3-speak').addEventListener('click', speak);\n        window.speechSynthesis.onvoiceschanged = () => {{}};
        document.getElementById('po3-stop').addEventListener('click', () => window.speechSynthesis.cancel());
        </script>
        """,
        height=52,
    )


def render_panel(snapshot):
    macro = snapshot.macro or {}
    score = score_value(macro.get("score"))
    name, tone = bias(score)
    market = macro.get("market", {})
    factors = macro.get("factors", [])
    leaders = macro.get("leaders", [])
    frames = macro.get("frames", {})

    st.markdown(f'''<div class="topline"><div><div class="asset-title">{snapshot.symbol}</div><div class="asset-meta"><span class="live-dot"></span>MT5 conectado · somente leitura · {snapshot.as_of.strftime('%d/%m/%Y %H:%M:%S')}</div></div><div class="source-chip">⟳ atualização automática</div></div>''', unsafe_allow_html=True)

    kpis = [
        ("Ativo", snapshot.symbol, ""),
        ("Último preço", f"{snapshot.last_price:,.0f}".replace(",", "."), ""),
        ("5 barras", pct(market.get("return_short")), _tone_class(market.get("return_short"))),
        ("20 barras", pct(market.get("return_long")), _tone_class(market.get("return_long"))),
        ("Volatilidade", "—" if market.get("volatility") is None else f"{market['volatility']*100:.3f}%", ""),
        ("Atualizado", snapshot.as_of.strftime("%H:%M:%S"), ""),
    ]
    st.markdown('<div class="kpi-grid">' + "".join(f'<div class="kpi"><span>{label}</span><strong class="{cls}">{value}</strong></div>' for label, value, cls in kpis) + '</div>', unsafe_allow_html=True)

    frame_keys = ["M1", "M5", "M15", "M30", "H1", "H4", "D1", "W1", "MN1"]
    labels = ["1 min", "5 min", "15 min", "30 min", "1 hora", "4 horas", "Diário", "Semanal", "Mensal"]
    timeframe_rows = []
    for label, key in zip(labels, frame_keys):
        data = frames.get(key, {})
        status = bias(score_value(data.get("score")))[0] if data.get("available") and data.get("score") is not None else "Sem dados"
        cls = "active" if key == "M15" else _tone_class(data.get("score"))
        timeframe_rows.append(f'<div class="tf-card {cls}"><b>{label}</b><span>{status}</span></div>')
    tf_html = "".join(timeframe_rows)
    confidence = str(macro.get("confidence", "baixa")).upper()
    aviso = "Compra preferencial" if tone == "green" else "Venda preferencial" if tone == "red" else "Sem direção predominante"
    leaders_rows = []
    for item in leaders:
        leaders_rows.append([item.get("ativo", "—"), item.get("simbolo", "—"), f"{float(item.get('direcao', 0)):+.2f}"])
    factors_rows = []
    for item in factors:
        factors_rows.append([item.get("grupo", "—"), item.get("simbolo", "—"), f"{float(item.get('direcao', 0)):+.3f}", f"{float(item.get('correlacao', 0)):+.3f}", f"{float(item.get('contribuicao', 0)):+.3f}"])
    leaders_html = _compact_table(["Ativo", "Símbolo", "Direção"], leaders_rows, numeric_columns=(2,)) if leaders_rows else '<div class="empty">Ações líderes ainda não disponíveis.</div>'
    factors_html = _compact_table(["Grupo", "Símbolo", "Direção", "Correlação", "Peso"], factors_rows, numeric_columns=(2, 3, 4)) if factors_rows else '<div class="empty">Sem fatores macro suficientes.</div>'

    st.markdown(f'''<div class="main-grid"><section class="panel-card"><div class="panel-title">Sinais por tempo</div><div class="tf-grid">{tf_html}</div></section><section class="panel-card center-panel"><div class="panel-title">Resumo ponderado</div>{gauge("Direção do ambiente", score, f"Confiança {confidence}", True)}<div class="summary {tone}">{name} · {score:+.1f}</div><div class="notice {tone}">{aviso}, confirme no setup técnico do WIN.</div></section><section class="panel-card"><div class="panel-title">Ações líderes da B3</div>{leaders_html}</section></div>''', unsafe_allow_html=True)

    left, right = st.columns([1.55, 1])
    with left:
        st.markdown(f'<section class="panel-card"><div class="panel-title">Correlações externas e domésticas</div>{factors_html}</section>', unsafe_allow_html=True)
    with right:
        with st.container(height=220, border=True):
            st.markdown('<div class="panel-title">Perguntas para IA</div>', unsafe_allow_html=True)
            questions = [
                "1. Qual é o viés do mercado hoje?",
                "2. Quais eventos podem mover o WIN?",
                "3. Como estão Nasdaq, S&P, dólar, juros, petróleo, ouro e VIX?",
                "4. Há alinhamento entre os tempos gráficos?",
                "5. O setup está alinhado ao viés macro?",
                "6. O que valida uma compra?",
                "7. O que valida uma venda?",
                "8. Quando devo ficar de fora?",
            ]
            for index, question in enumerate(questions):
                if st.button(question, key=f"ai_question_{index}", use_container_width=True):
                    st.session_state["pending_ai_question"] = question
                    st.rerun()

    st.markdown('<div class="panel-card" style="margin-top:.55rem"><div class="panel-title">Panorama do pregão</div></div>', unsafe_allow_html=True)
    if st.button("Análise do dia", key="daily_analysis", type="primary", help="Busca o contexto disponível agora e gera uma leitura macro para o pregão"):
        st.session_state["daily_analysis_status"] = "Consultando fontes e IA..."
        with st.spinner("Consultando calendário, manchetes autorizadas e dados do painel..."):
            try:
                answer, context = _run_daily_analysis(snapshot)
                analysis_id = save_analysis(snapshot, context, answer)
                st.session_state["daily_analysis_answer"] = answer
                st.session_state["daily_analysis_structured"] = context.get("_structured", {})
                st.session_state["daily_analysis_id"] = analysis_id
                st.session_state["daily_analysis_at"] = datetime.now().astimezone().strftime("%d/%m/%Y %H:%M:%S")
                st.session_state["daily_analysis_sources"] = context.get("news", {}).get("statuses", [])
                st.session_state["daily_analysis_status"] = "Análise concluída."
            except OpenRouterError as exc:
                record_ai_error("analise_do_dia", type(exc).__name__, str(exc), "fallback/retentativa controlada")
                st.session_state["daily_analysis_answer"] = f"Não foi possível gerar a análise: {exc}"
                st.session_state["daily_analysis_sources"] = []
                st.session_state["daily_analysis_status"] = f"A consulta terminou com erro controlado: {exc}"
            except Exception as exc:
                detail = str(exc).strip()
                if any(secret in detail.lower() for secret in ("api_key", "authorization", "bearer")):
                    detail = "falha de autenticação (detalhe protegido)"
                record_ai_error("analise_do_dia", type(exc).__name__, detail, "registro seguro; nenhuma regra alterada")
                st.session_state["daily_analysis_answer"] = f"A análise não pôde ser concluída: {type(exc).__name__}. {detail or 'Verifique a conexão e tente novamente.'}"
                st.session_state["daily_analysis_sources"] = []
                st.session_state["daily_analysis_status"] = "A consulta terminou com erro controlado."
    if st.session_state.get("daily_analysis_status"):
        st.caption(st.session_state["daily_analysis_status"])
    if st.session_state.get("daily_analysis_answer"):
        st.markdown(f'<div class="notice" style="margin-top:.55rem"><b>Análise registrada em {st.session_state.get("daily_analysis_at", "—")}</b></div>', unsafe_allow_html=True)
        st.markdown(f'<div class="daily-analysis">{st.session_state["daily_analysis_answer"]}</div>', unsafe_allow_html=True)
        _render_structured_summary(st.session_state.get("daily_analysis_structured", {}))
        _render_audio_button(st.session_state["daily_analysis_answer"])
        sources = st.session_state.get("daily_analysis_sources", [])
        if sources:
            st.caption("Consulta das fontes: " + " · ".join(sources))

    calendar = _economic_calendar()
    if calendar.get("available"):
        calendar = {**calendar, "events": filter_relevant_events(calendar.get("events", []))}
    with st.expander("Dados econômicos e externos · abrir", expanded=False):
        if st.button("Atualizar calendário", key="refresh_calendar", help="Limpa o cache e consulta as fontes oficiais novamente"):
            _economic_calendar.clear()
            st.rerun()
        st.caption(f"Calendário Econômico · horários em America/Sao_Paulo · fonte: {calendar.get('source', 'não disponível')}.")
        if calendar.get("available") and calendar.get("events"):
            next_high = get_next_high_impact_event(calendar["events"])
            if next_high and next_high.get("datetime"):
                minutes = int((next_high["datetime"] - datetime.now(next_high["datetime"].tzinfo)).total_seconds() // 60)
                alert = "ALERTA: evento de alto impacto em " if minutes < 15 else "Atenção: evento de alto impacto em " if minutes <= 30 else "Próximo evento de alto impacto em "
                st.info(f"{alert}{max(0, minutes)} min · {next_high['evento']} às {next_high['hora']}")
            rows = [[e.get("data", "—"), e["hora"], e["pais"], e["evento"], e["impacto"], e["anterior"], e["previsao"], e["resultado"], e.get("vies", "Sem leitura")] for e in calendar["events"]]
            st.markdown(_compact_table(["Data", "Horário", "País", "Evento", "Impacto", "Anterior", "Previsão", "Atual", "Viés provável"], rows, numeric_columns=()), unsafe_allow_html=True)
        elif calendar.get("available"):
            st.info("Nenhum evento econômico relevante dos EUA encontrado para hoje.")
        else:
            st.info(f"Calendário econômico temporariamente indisponível. {calendar.get('message', '')}")
    missing = [item for item in macro.get("missing", []) if str(item).strip().lower() != "volatilidade"]
    if missing:
        st.caption("Grupos sem dados no MT5: " + ", ".join(missing))


def _local_chat_answer(question: str, snapshot) -> str:
    """Respostas locais baseadas apenas no snapshot atual do painel."""
    q = question.lower().strip()
    macro = snapshot.macro or {}
    score = score_value(macro.get("score"))
    name, _ = bias(score)
    frames = macro.get("frames", {})
    if any(word in q for word in ("direção", "direcao", "viés", "vies", "mercado", "comprador", "vendedor")):
        return f"O viés macro calculado agora é {name}, com score {score:+.1f}. Isso é filtro de contexto; a entrada continua dependendo do setup técnico e da decisão manual."
    if "preço" in q or "preco" in q or "cotação" in q or "cotacao" in q:
        return f"O último preço recebido do MT5 para {snapshot.symbol} é {snapshot.last_price:,.0f}.".replace(",", ".")
    if "m15" in q or "15" in q:
        data = frames.get("M15", {})
        return f"No M15, o painel está em {bias(score_value(data.get('score')))[0] if data.get('score') is not None else 'sem dados'}, usando candles fechados e score {score_value(data.get('score')):+.1f}."
    if "m5" in q or "5 minutos" in q:
        data = frames.get("M5", {})
        return f"No M5, o painel está em {bias(score_value(data.get('score')))[0] if data.get('score') is not None else 'sem dados'}, com score {score_value(data.get('score')):+.1f}."
    if "m1" in q or "1 minuto" in q:
        data = frames.get("M1", {})
        return f"No M1, o painel está em {bias(score_value(data.get('score')))[0] if data.get('score') is not None else 'sem dados'}, com score {score_value(data.get('score')):+.1f}."
    if "correla" in q or "extern" in q or "dólar" in q or "dolar" in q:
        factors = macro.get("factors", [])
        if not factors:
            return "Ainda não há fatores macro suficientes no MT5 para calcular as correlações."
        itens = ", ".join(f"{x.get('grupo')} {float(x.get('contribuicao', 0)):+.2f}" for x in factors[:6])
        return f"As contribuições calculadas agora são: {itens}. Sinal positivo favorece o score comprador; negativo pesa para venda."
    if "líder" in q or "lider" in q or "ação" in q or "acao" in q:
        leaders = macro.get("leaders", [])
        if not leaders:
            return "Não há ações líderes disponíveis no MT5 neste momento."
        itens = ", ".join(f"{x.get('simbolo')} {float(x.get('direcao', 0)):+.2f}" for x in leaders[:8])
        return f"Ações líderes lidas no MT5: {itens}."
    if "fvg" in q or "order block" in q:
        return "O chat local não substitui a leitura dos indicadores no gráfico. Use os indicadores FVG/OB nos tempos correspondentes; o painel não envia ordens."
    return "Posso responder sobre direção macro, preço, M15, M5, M1, correlações, ações líderes e leitura dos indicadores. Pergunte, por exemplo: 'Qual é o viés do WIN agora?'"


def _ai_market_context(snapshot) -> str:
    """Serializa apenas o snapshot atual, sem credenciais ou dados de execução."""
    bars = {}
    for timeframe in ("D1", "M15", "M5", "M1"):
        rows = snapshot.bars.get(timeframe, [])[-3:]
        bars[timeframe] = [
            {
                "hora": row["time"].isoformat() if hasattr(row.get("time"), "isoformat") else str(row.get("time")),
                "open": row.get("open"), "high": row.get("high"),
                "low": row.get("low"), "close": row.get("close"),
                "volume": row.get("tick_volume"),
            }
            for row in rows
        ]
    macro = snapshot.macro or {}
    frames = {
        name: {key: value for key, value in data.items() if key in {"score", "bias", "confidence", "factors", "leaders", "missing"}}
        for name, data in (macro.get("frames") or {}).items()
    }
    context = {
        "ativo": snapshot.symbol,
        "horario_leitura": snapshot.as_of.isoformat(),
        "preco_atual": snapshot.last_price,
        "fonte_preco": snapshot.source,
        "candles_fechados_recentes": bars,
        "niveis": [{"codigo": x.code, "rotulo": x.label, "valor": x.value, "grupo": x.group} for values in snapshot.levels.values() for x in values],
        "macro_por_tempo": frames,
        "zonas": [
            {"tipo": z.kind, "direcao": z.direction, "inferior": z.lower, "superior": z.upper, "tempo": z.timeframe, "status": z.status}
            for values in snapshot.zones.values() for z in values
        ],
        "regras_dos_indicadores_mt5": {
            "PO3_D1_Objetivos_M15": {
                "timeframes": ["M15", "D1"],
                "regra": "Calcula FVG e Order Block no timeframe do gráfico; mantém zonas não tocadas, ordena da mais recente e exibe no máximo 6 zonas com bloco colorido e linha de 50%.",
                "invalidacao": "Toque ou entrada na faixa deixa de ser zona intocada.",
            },
            "PO3_Confluencia_M15_M5_M1": {
                "timeframes": ["M5", "M15", "M1"],
                "regra": "Usa somente FVGs em M5, M15 e M1. Procura um FVG maior válido e exige que o FVG M1 surja depois, esteja totalmente dentro dele e tenha a mesma direção. No gráfico M1, exibe somente a confirmação FVG M1; as zonas macro M5/M15 não são plotadas.",
                "invalidacao": "A zona é invalidada por fechamento além do limite; pavio ou toque isolado não bastam.",
                "entrada_stop": "Entrada no centro da zona M1; stop no limite da zona de contexto; ignora risco inferior a 10 pontos.",
                "niveis": "Entrada, stop e alvos são desenhados no M1; existem cinco alvos em múltiplos de risco.",
            },
        },
    }
    return json.dumps(context, ensure_ascii=False, default=str)


def render_local_chat(snapshot) -> None:
    # Recolhido por padrão para manter o painel principal em uma única tela.
    with st.expander("Chat IA do painel · abrir para perguntar", expanded=bool(st.session_state.get("chat_open", False))):
        st.markdown(f'<div class="ai-status">IA · OpenRouter · <span class="ai-model">{configured_model_name()}</span></div>', unsafe_allow_html=True)
        history = st.session_state.setdefault("local_chat_history", [])
        for role, message in history[-8:]:
            with st.chat_message(role):
                st.write(message)
        selected_question = st.session_state.pop("pending_ai_question", None)
        prompt = selected_question or st.chat_input("Pergunte sobre o WIN, M15, M5, M1 ou as correlações...")
        if prompt:
            st.session_state["chat_open"] = True
            external = {}
            try:
                external = _external_context()
                answer = send_message(
                    f"Pergunta do usuário:\n{prompt}\n\nDados atuais do PO3 Copilot (JSON):\n{_ai_market_context(snapshot)}"
                    f"\n\nCalendário e fontes externas autorizadas (JSON):\n{json.dumps(external, ensure_ascii=False, default=str)}",
                    system_instruction=(
                        "REGRA ABSOLUTA: responda sempre e exclusivamente em português do Brasil. Não misture inglês em nenhuma explicação, título ou rótulo; preserve apenas nomes próprios, símbolos e nomes oficiais. "
                        "Você é o assistente do PO3 Copilot. Use somente os JSONs fornecidos na mensagem. "
                            "Se perguntarem quem você é, diga que é o PO3 Copilot, um assistente de análise macro e operacional do WIN. "
                        "Explique que sua função é interpretar dados do MT5, calendário e fontes autorizadas; você não é humano, "
                            "não envia ordens e não substitui a decisão manual. Fora desse tipo de pergunta, não repita essa apresentação. "
                            "Não comece respostas normais com avisos institucionais sobre o PO3 Copilot, MT5 ou execução manual. "
                        "Aplique também as regras do painel: leitura macro é filtro de contexto, os sinais técnicos "
                        "são somente leitura, e a execução é manual. Não invente preços, direções, eventos, notícias "
                        "ou sinais. Se um dado não estiver nos JSONs, diga que não está disponível. Diferencie fato, "
                        "cálculo e inferência. Responda em português. As fontes externas autorizadas são InfoMoney, "
                        "Valor Econômico, Investing.com, E-Investidor, Money Times, TradingView, Yahoo Finance, CNBC, "
                        "MarketWatch e CME Group. No calendário, Atual só deve ser considerado divulgado quando o "
                        "horário do evento já passou. Para o ativo principal, use sempre o símbolo atual do snapshot e nunca presuma WINV26. "
                        "Quando o vencimento mudar, continue usando automaticamente o ativo atual do MT5. Para Nasdaq e demais ativos externos, "
                        "use as cotações autorizadas disponíveis no JSON. Use ✅ para fato confirmado, ⚠️ para atenção e 🔎 para inferência. "
                        "Interprete os indicadores conforme regras_dos_indicadores_mt5: não misture PO3_D1_Objetivos_M15 com PO3_Confluencia_M15_M5_M1. "
                        "No D1_Objetivos_M15, toque invalida a condição de zona intocada; na Confluencia_M15_M5_M1, M5/M15 são contexto interno e não devem ser tratados como zonas visuais no M1; pavio ou toque isolado não invalida, apenas fechamento além do limite. "
                        "Só descreva uma zona, confluência, entrada, stop ou alvo se ela estiver presente no JSON; as regras são critérios de interpretação e não autorizam inventar níveis. "
                        "Antes da divulgação, calcule apenas viés provável comparando "
                        "Previsão com Anterior; depois, compare Atual com Previsão. Se não houver dados suficientes, "
                        "diga sem leitura. Preserve a estrutura pedida pelo usuário e não a substitua por outro formato. Para a análise do dia, use sempre os três blocos fixos: MACROECONOMIA E DIA A DIA; IMPACTO NA BOLSA; INSIGHT OPERACIONAL."
                    ),
                )
            except OpenRouterError as exc:
                answer = f"Não foi possível consultar a IA: {exc}"
            try:
                save_analysis(snapshot, {"tipo": "pergunta_chat", "pergunta": prompt, "fontes": external}, answer)
            except Exception:
                # A persistência é auxiliar; uma falha local não pode interromper o chat.
                pass
            history.extend([("user", prompt), ("assistant", answer)])
            st.rerun()



def render_collection_status(symbol: str) -> None:
    """Exibe status persistido; a interface nunca inicia coleta."""
    from po3.storage.market_repository import collection_status
    from po3.v2_config import AUTO_DATA_COLLECTION
    status = collection_status(symbol, os.path.join(os.path.dirname(__file__), "data", "po3_learning.sqlite"))
    worker = "Ativo" if status.get("status") == "ATIVA" else ("Erro" if status.get("status") == "ERRO" else "Inativo")
    feed = status.get("feed_status", "SEM_DADOS")
    feed_label = "Atual" if feed == "ATUAL" else ("Atrasado" if feed in {"MT5_DATA_STALE", "MT5_FEED_REALLY_STALE"} else ("Mercado fechado" if feed == "SEM_NOVO_CANDLE_MERCADO_FECHADO" else feed))
    lag = status.get("feed_lag_seconds")
    lag_text = "—" if lag is None else f"{lag:.0f} s"
    alignment = status.get("clock_alignment_status") or "-"
    offset = status.get("detected_offset_seconds")
    offset_text = "-" if offset is None else f"{offset:+.0f} s"
    with st.container(border=True):
        st.caption("Coleta histórica")
        st.write(f"Worker: {worker} · Feed MT5: {feed_label}")
        st.caption(f"Clock MT5: {alignment} ({offset_text})")
        st.caption(f"Último M1: {status.get('last_closed_at_utc') or status.get('ultimo_m1') or '—'} · Atraso: {lag_text}")
        st.caption(f"Último MarketState: {status.get('ultimo_market_state') or '—'} · Outcomes pendentes: {status.get('outcomes_pendentes', 0)}")


def _supervisor_ai_text(snapshot: dict) -> str | None:
    """Gera explicação somente em mudança relevante e respeitando cooldown."""
    if not SUPERVISOR_AI_ENABLED:
        return None
    now = datetime.now().astimezone()
    decision = supervisor_ai_gate(snapshot, st.session_state, now)
    if not decision["should_call"]:
        st.session_state["last_supervisor_status"] = decision["status"]
        return st.session_state.get("last_supervisor_ai_text")
    try:
        text = send_message(
            "Explique em português do Brasil o estado operacional do PO3 Copilot usando somente os fatos do JSON. "
            "Não recomende compra ou venda, não indique trades, não altere parâmetros e não invente dados.",
            system_instruction="Você é a IA explicativa do Supervisor Operacional. Responda apenas sobre status técnico e coleta factual.\n\n" + supervisor_ai_context(snapshot),
        )
    except Exception as exc:
        text = f"A explicação da IA está indisponível ({type(exc).__name__}); o estado determinístico continua ativo."
    st.session_state["last_supervisor_hash"] = decision["hash"]
    st.session_state["last_supervisor_status"] = decision["status"]
    st.session_state["last_supervisor_ai_at"] = now
    st.session_state["last_supervisor_ai_text"] = text
    return text


def _local_time(value: str | None) -> str:
    if not value:
        return "—"
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone().strftime("%H:%M")
    except (TypeError, ValueError):
        return "—"


def _display_status(value: str | None) -> str:
    return {"OPERACAO_NORMAL": "Operação normal", "VALIDANDO_CAUSALIDADE": "Validando causalidade",
            "AGUARDANDO_SESSAO": "Aguardando sessão", "ATENCAO_FEED": "Atenção ao feed",
            "ATENCAO_CLOCK": "Atenção ao clock", "ATENCAO_LEASE": "Atenção ao lease",
            "ATENCAO_AUTO_DECISION": "Atenção à IA oficial", "ATENCAO_SHADOW": "Atenção ao Jev",
            "ATENCAO_BANCO": "Atenção ao banco"}.get(str(value), str(value or "Indisponível").replace("_", " ").title())


def _decision_label(value: str | None) -> str:
    return {"CONTEXTO_COMPRADOR": "Comprador", "CONTEXTO_VENDEDOR": "Vendedor",
            "AGUARDAR": "Aguardar", "SEM_SETUP": "Sem setup", "INDETERMINADO": "Indeterminado",
            "REVISAO": "Revisão", "DIVERGENCIA": "Divergência", "CONSENSO": "Consenso",
            "ALTA": "Alta", "MEDIA": "Média", "MÉDIA": "Média", "BAIXA": "Baixa"}.get(str(value), str(value or "Indisponível"))


def _latest_jev(db_path: str, symbol: str) -> dict:
    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM jev_shadow_runs WHERE symbol=? ORDER BY cutoff_at_utc DESC,id DESC LIMIT 1", (symbol,)).fetchone()
            return dict(row) if row else {}
    except sqlite3.Error:
        return {}


def _render_diagnostic(snapshot: dict, symbol: str) -> None:
    db_path = os.path.join(os.path.dirname(__file__), "data", "po3_learning.sqlite")
    collector = snapshot.get("collector", {})
    latest = snapshot.get("latest_market_state") or {}
    o1 = snapshot.get("o1_validation", {})
    security = snapshot.get("security", {})
    jev = _latest_jev(db_path, symbol)
    with st.expander("Diagnóstico técnico", expanded=False):
        st.markdown("**Collector**")
        st.write({"Status": collector.get("status"), "Feed": collector.get("feed_liveness_status"),
                  "Atraso (s)": collector.get("feed_lag_seconds"), "Último M1": collector.get("last_closed_at_utc"),
                  "Último tick": collector.get("normalized_tick_at_utc"),
                  "Clock": collector.get("clock_alignment_status"), "Offset (s)": collector.get("detected_offset_seconds")})
        st.markdown("**MarketState**")
        st.write({"ID": latest.get("id"), "Cutoff UTC": latest.get("cutoff_at_utc"),
                  "Open bar start": latest.get("start_bar_open_time"), "Start price": latest.get("start_price"),
                  "Start price status": latest.get("start_price_status"), "State hash": latest.get("state_hash")})
        st.markdown("**Validação O1**")
        st.write({"Status": o1.get("status"), "Estados válidos": f"{o1.get('valid_states', 0)}/{o1.get('required_states', 3)}",
                  "State IDs": o1.get("state_ids", []), "Detalhe": o1.get("details")})
        st.markdown("**Banco / Outcomes**")
        db = snapshot.get("database", {})
        outcomes = snapshot.get("outcomes", {})
        st.write({"Integridade": db.get("integrity_status"), "Market bars M1": db.get("market_bars_m1", 0),
                  "MarketStates": db.get("market_states", 0), "Decision observations": db.get("decision_observations", 0),
                  "Outcomes": db.get("observed_outcomes", 0), "Shadow runs": db.get("shadow_runs", 0),
                  "Disponíveis": outcomes.get("por_status", {}).get("DISPONIVEL", 0),
                  "Pendentes": outcomes.get("por_status", {}).get("PENDENTE", 0),
                  "Pendente dados": outcomes.get("por_status", {}).get("PENDENTE_DADOS", 0),
                  "5m": outcomes.get("por_horizon", {}).get("5m", 0), "15m": outcomes.get("por_horizon", {}).get("15m", 0),
                  "30m": outcomes.get("por_horizon", {}).get("30m", 0), "60m": outcomes.get("por_horizon", {}).get("60m", 0)})
        st.markdown("**Workers / leases**")
        try:
            with sqlite3.connect(db_path) as conn:
                conn.row_factory = sqlite3.Row
                leases = [dict(row) for row in conn.execute("SELECT collector_name,owner_id,heartbeat_at,expires_at FROM collector_leases WHERE symbol=? ORDER BY collector_name", (symbol,))]
            st.dataframe(leases, hide_index=True, width="stretch")
        except sqlite3.Error:
            st.caption("Leases indisponíveis.")
        st.markdown("**Flags**")
        st.write({key: security.get(key) for key in ("AUTO_DECISION_ENGINE", "SHADOW_MODE_ENABLED", "CALIBRATION_ENABLED", "MODEL_BENCHMARK_ENABLED", "REPLAY_ENABLED")})
        st.markdown("**Shadow técnico**")
        st.write({key: jev.get(key) for key in ("id", "market_state_id", "cutoff_at_utc", "status", "created_at_utc", "finished_at_utc", "error_type", "error_message")})


def render_operational_supervisor(symbol: str) -> None:
    """Visão principal compacta e diagnóstico técnico somente leitura."""
    db_path = os.path.join(os.path.dirname(__file__), "data", "po3_learning.sqlite")
    try:
        snapshot = build_supervisor_snapshot(db_path, symbol)
    except Exception as exc:
        st.error(f"Supervisor indisponível: {type(exc).__name__}")
        return
    session = snapshot["session"]
    collector = snapshot["collector"]
    security = snapshot["security"]
    official = snapshot.get("official_analysis", {}).get("latest") or {}
    jev = _latest_jev(db_path, symbol)
    feed = collector.get("feed_liveness_status") or collector.get("status")
    collection = "OK" if (not session.get("market_active") or feed in {"LIVE", "ATUAL", "SEM_NOVO_CANDLE_MERCADO_FECHADO"}) else ("ATENÇÃO" if feed else "ERRO")
    official_status = official.get("status") or "PROCESSANDO"
    ai_status = "OK" if official_status == "OK" else "PROCESSANDO" if official_status == "PROCESSANDO" else "ERRO" if official_status == "ERRO" else "ATENÇÃO"
    with st.container(border=True):
        st.title(f"PO3 COPILOT — {symbol}")
        st.subheader("Status")
        cols = st.columns(4)
        cols[0].metric("Status geral", _display_status(snapshot.get("overall_status")))
        cols[1].metric("Mercado", "ABERTO" if session.get("market_active") else "FECHADO")
        cols[2].metric("Coleta", collection)
        cols[3].metric("IA oficial", ai_status)
        st.subheader("Decisão oficial")
        context = _decision_label(official.get("context_operational"))
        st.markdown(f"### {context}")
        dcols = st.columns(5)
        dcols[0].metric("Confiança", _decision_label(official.get("confidence")))
        dcols[1].metric("Gate", _decision_label(official.get("gate_status")))
        dcols[2].metric("Consenso", _decision_label(official.get("consensus_status")))
        dcols[3].metric("Modelo", official.get("model_used") or official.get("model_configured") or "Indisponível")
        dcols[4].metric("Última análise", _local_time(official.get("created_at_utc")))
        if official.get("narrative"):
            st.markdown(official["narrative"])
    alerts = []
    if session.get("market_active") and feed not in {"LIVE", "ATUAL"}:
        alerts.append("Feed MT5 atrasado ou indisponível")
    if collector.get("clock_alignment_status") not in {"ALIGNED", "OFFSET_DETECTED"}:
        alerts.append("Clock MT5 com alinhamento instável")
    if not snapshot.get("lease", {}).get("active"):
        alerts.append("Collector indisponível")
    if security.get("AUTO_DECISION_ENGINE") and official.get("status") == "ERRO":
        alerts.append("IA oficial com erro")
    latest_state = snapshot.get("latest_market_state") or {}
    try:
        with sqlite3.connect(db_path) as conn:
            state_row = conn.execute("SELECT state_json FROM market_states WHERE id=?", (latest_state.get("id"),)).fetchone()
        quality = json.loads(state_row[0]).get("qualidade_dados", {}) if state_row else {}
        if quality.get("calendario_disponivel") is False:
            alerts.append("Calendário indisponível")
    except (sqlite3.Error, TypeError, ValueError):
        pass
    if security.get("SHADOW_MODE_ENABLED") and jev.get("status") == "ERRO":
        alerts.append("Jev indisponível")
    if alerts:
        st.warning(" · ".join(f"⚠ {item}" for item in alerts))
    _render_diagnostic(snapshot, symbol)
    ai_text = _supervisor_ai_text(snapshot)
    if ai_text and alerts:
        st.caption(ai_text)


def render_evaluation(symbol: str) -> None:
    """Área somente leitura; não coleta, não chama LLM e não altera o banco."""
    if not EVALUATION_ENGINE_ENABLED:
        return
    db_path = os.path.join(os.path.dirname(__file__), "data", "po3_learning.sqlite")
    try:
        report = build_evaluation_report(db_path, symbol)
    except Exception as exc:
        with st.expander("Avaliação V2", expanded=False):
            st.caption(f"Avaliação indisponível: {type(exc).__name__}")
        return
    with st.expander("Avaliação V2", expanded=False):
        st.caption(f"Versão {report['evaluation_version']} · geração UTC {report['generated_at_utc']}")
        if not report["market_states"]:
            st.info("Nenhum MarketState factual disponível para avaliação.")
            return
        for horizon, item in report["horizons"].items():
            sample = item["available_sample_size"]
            st.markdown(f"**Horizonte: {horizon}** · Amostra disponível: **{sample}** · Maturidade: **{item['sample_band']}**")
            if sample < 30:
                st.caption("Amostra insuficiente para interpretação robusta.")
            elif sample < 100:
                st.caption("Amostra preliminar.")
            elif sample < 200:
                st.caption("Amostra utilizável para análise descritiva.")
            else:
                st.caption("Amostra mais robusta para análise descritiva.")
            status = item["status"]
            st.write("Cobertura:", " · ".join(f"{key}: {value}" for key, value in sorted(status.items())) or "Sem Outcomes")
            stats = item["metrics"]["percentage_change"]
            st.write({"Mediana %": stats["median"], "P25": stats["p25"], "P75": stats["p75"],
                      "High delta mediano": item["metrics"]["high_delta"]["median"],
                      "Low delta mediano": item["metrics"]["low_delta"]["median"]})
            distribution = item["directional_distribution"]
            st.caption(f"Movimento futuro — Positivo: {distribution['positive']} · Negativo: {distribution['negative']} · Neutro: {distribution['zero']}")
        quality = report["data_quality"]
        with st.expander("Qualidade dos dados", expanded=False):
            st.json(quality)


def render_jev_shadow(symbol: str) -> None:
    """Exibe o Jev somente como comparação observacional e somente leitura."""
    db_path = os.path.join(os.path.dirname(__file__), "data", "po3_learning.sqlite")
    with st.expander("JEV SHADOW — EXPERIMENTAL", expanded=False):
        st.caption("Jev Shadow é experimental e não altera a decisão oficial.")
        try:
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM jev_shadow_runs WHERE symbol=? ORDER BY cutoff_at_utc DESC,id DESC LIMIT 1", (symbol,)).fetchone()
            official = conn.execute("SELECT * FROM official_decision_runs WHERE symbol=? ORDER BY cutoff_at_utc DESC,id DESC LIMIT 1", (symbol,)).fetchone()
            conn.close()
        except Exception as exc:
            st.warning(f"Jev Shadow indisponível: {type(exc).__name__}")
            return
        if not JEV_SHADOW_ENABLED:
            st.info("Desativado — JEV_SHADOW_ENABLED=false")
            return
        if row is None:
            st.info("Aguardando o primeiro MarketState elegível.")
            return
        try:
            answers = json.loads(row["answers_json"] or "[]")
        except (TypeError, ValueError):
            answers = []
        jev_context = next((item.get("normalized_answer") for item in answers
                            if item.get("decision_id") == "contexto_operacional"), "—")
        cols = st.columns(6)
        cols[0].metric("Status", row["status"])
        cols[1].metric("Modelo", row["model_used"] or row["model_configured"])
        cols[2].metric("Contexto Jev", jev_context or "—")
        cols[3].metric("Acordo Oficial × Jev", "—")
        cols[4].metric("Latência", f"{row['duration_seconds'] or 0:.2f}s")
        cols[5].metric("Custo (US$)", f"{float(row['cost_usd'] or 0):.8f}")
        if row["status"] != "OK":
            st.warning(row["error_message"] or row["status"])
            return
        official_items = {}
        if official is not None:
            try:
                official_items = {item.get("id_decisao"): item for item in json.loads(official["decisions_json"]).get("decisoes", [])}
            except (TypeError, ValueError, AttributeError):
                official_items = {}
        comparison = compare_market_state(db_path, row["market_state_id"])
        rows = []
        for answer in answers:
            key = answer.get("decision_id")
            official_value = official_items.get(key, {}).get("decisao")
            jev_value = answer.get("normalized_answer")
            agreement = comparison.get(f"agreement_{key}")
            if key == "risco_evento":
                agreement = comparison.get("risk_event_absolute_difference") == 0
            rows.append({"Decisão": key, "Oficial": official_value or "—", "Jev": jev_value or "—",
                         "Acordo": "SIM" if agreement is True else "NÃO" if agreement is False else "—",
                         "Confidence Jev": answer.get("confidence") or "—"})
        cols[3].metric("Acordo Oficial × Jev", f"{comparison.get('exact_agreement_count', 0)}/6")
        if st.checkbox("Mostrar detalhes das 6 decisões", value=False, key="jev_show_details"):
            st.dataframe(rows, hide_index=True, width="stretch")
        score = next((answer for answer in answers if answer.get("decision_id") == "risco_evento"), {})
        noul = next((answer for answer in answers if answer.get("decision_id") == "conflito_contexto"), {})
        st.caption(f"Risco evento oficial: {official_items.get('risco_evento', {}).get('decisao', '—')} · Jev: {score.get('normalized_answer', '—')} · diferença: {comparison.get('risk_event_absolute_difference', '—')}")
        st.caption(f"NOUL probability: {noul.get('noul_probability', '—')} · Acordo total: {comparison.get('exact_agreement_count', 0)}/6")

with st.sidebar:
    st.markdown('<div class="brand"><div class="brand-mark">P3</div><div><div class="brand-title">PO3 Copilot B3</div><div class="brand-sub">Painel macro operacional</div></div></div>', unsafe_allow_html=True)
    st.markdown("**Configuração de leitura**")
    symbol = st.text_input("Ativo principal", "WINV26").strip().upper() or "WINV26"
    terminal = st.text_input("Terminal MT5", DEFAULT_TERMINAL)
    auto = st.toggle("Atualização automática", True)
    seconds = st.slider("Intervalo de atualização", 5, 60, 15, 5)
    st.caption("Conexão somente leitura. O painel não envia ordens.")

@st.fragment(run_every=f"{seconds}s" if auto else None)
def live():
    try:
        snapshot = read_snapshot(terminal, symbol)
        st.session_state["latest_snapshot"] = snapshot
    except MT5ReadError as exc:
        st.session_state["snapshot_error"] = str(exc)

@st.fragment(run_every="15s")
def supervisor_live():
    render_operational_supervisor(symbol)

supervisor_live()
live()
render_jev_shadow(symbol)
if "latest_snapshot" in st.session_state:
    render_evaluation(symbol)
if "latest_snapshot" in st.session_state:
    render_local_chat(st.session_state["latest_snapshot"])

with st.expander("Histórico de análises", expanded=False):
    history_rows = recent_analyses(20)
    if history_rows:
        st.dataframe([
            {"Data/hora": x["data_hora"], "Ativo": x["ativo"], "Regime macro": x["regime_macro"], "Contexto técnico": x["contexto_tecnico"], "Contexto operacional": x["contexto_operacional"], "Status": x["status"], "Modelo": x["modelo"]}
            for x in history_rows
        ], hide_index=True, width="stretch")
    else:
        st.caption("Nenhuma análise registrada ainda.")
