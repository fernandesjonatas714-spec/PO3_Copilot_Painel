from __future__ import annotations

from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

from po3.book_rules import DetectionConfig, PO3Detection, detect_book_po3
from po3.demo_data import build_demo_snapshot
from po3.engine import ChecklistState, calculate_rr, context_messages, status_from_checklist
from po3.models import MarketSnapshot
from po3.mt5_reader import MT5ReadError, read_snapshot
from po3.options_data import auto_download_b3, find_latest_csv, load_options_csv, option_summary


DEFAULT_TERMINAL = r"C:\Program Files\Clear Investimentos MT5 Terminal\terminal64.exe"


st.set_page_config(
    page_title="PO3 Copilot B3",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    .stApp { background: #0f1115; color: #d1d4dc; }
    [data-testid="stSidebar"] { background: #151922; }
    .block-container { padding-top: 1.2rem; max-width: 1600px; }
    .po3-header { display:flex; align-items:center; justify-content:space-between; margin-bottom:1rem; }
    .po3-title { font-size:1.65rem; font-weight:750; letter-spacing:.02em; }
    .safe-badge { background:#173b2d; color:#7ce3ad; border:1px solid #286047; padding:.35rem .7rem; border-radius:999px; font-size:.82rem; }
    .status-card { border-radius:14px; padding:1rem 1.1rem; border:1px solid #2b3240; background:#171b24; min-height:96px; }
    .status-card .label { color:#8e99aa; font-size:.78rem; text-transform:uppercase; letter-spacing:.08em; }
    .status-card .value { font-size:1.35rem; font-weight:750; margin-top:.35rem; }
    .banner { border-radius:12px; padding:.85rem 1rem; margin:.5rem 0 1rem 0; font-weight:650; }
    .banner-verde { background:#173b2d; color:#86efac; border:1px solid #286047; }
    .banner-amarelo { background:#443515; color:#fde68a; border:1px solid #715b27; }
    .banner-vermelho { background:#481f25; color:#fda4af; border:1px solid #74323c; }
    .small-note { color:#8e99aa; font-size:.82rem; }
    div[data-testid="stMetric"] { background:#171b24; border:1px solid #2b3240; padding:.75rem; border-radius:12px; }
    </style>
    """,
    unsafe_allow_html=True,
)


def points(value: float) -> str:
    return f"{value:,.0f}".replace(",", ".")


def frame(snapshot: MarketSnapshot, timeframe: str) -> pd.DataFrame:
    data = snapshot.bars.get(timeframe, [])
    if not data:
        return pd.DataFrame(columns=["time", "open", "high", "low", "close", "tick_volume"])
    return pd.DataFrame(data).sort_values("time")


def render_levels(snapshot: MarketSnapshot, timeframe: str) -> None:
    levels = snapshot.levels.get(timeframe, [])
    if not levels:
        st.caption("Sem níveis automáticos neste tempo gráfico.")
        return
    table = pd.DataFrame(
        [{"Código": level.code, "Nível": level.label, "Preço": points(level.value)} for level in levels]
    )
    st.dataframe(table, hide_index=True, width="stretch")


def render_zones(snapshot: MarketSnapshot, timeframe: str) -> None:
    zones = snapshot.zones.get(timeframe, [])
    if not zones:
        st.caption("Sem FVGs ou Order Blocks diários ativos.")
        return
    table = pd.DataFrame(
        [
            {
                "Tipo": zone.kind,
                "Direção": zone.direction,
                "Zona": f"{points(zone.lower)} — {points(zone.upper)}",
                "Criada em": zone.created_at.strftime("%d/%m/%Y"),
                "Status": zone.status,
            }
            for zone in zones
        ]
    )
    st.dataframe(table, hide_index=True, width="stretch")


def render_chart(snapshot: MarketSnapshot, timeframe: str) -> None:
    data = frame(snapshot, timeframe)
    if data.empty:
        st.warning(f"Sem candles disponíveis para {timeframe}.")
        return
    base_chart = (
        alt.Chart(data)
        .mark_line(color="#26a69a", strokeWidth=2)
        .encode(
            x=alt.X(
                "time:T",
                title=None,
                axis=alt.Axis(format="%H:%M", grid=False, labelColor="#8e99aa"),
            ),
            y=alt.Y(
                "close:Q",
                title="Preço",
                scale=alt.Scale(zero=False, nice=True),
                axis=alt.Axis(gridColor="#2b3240", labelColor="#8e99aa", titleColor="#8e99aa"),
            ),
            tooltip=[
                alt.Tooltip("time:T", title="Hora", format="%d/%m %H:%M"),
                alt.Tooltip("close:Q", title="Preço", format=",.0f"),
            ],
        )
        .properties(height=240)
    )
    zones = snapshot.zones.get(timeframe, [])
    if zones:
        zone_data = pd.DataFrame(
            [
                {
                    "start": zone.created_at,
                    "end": data.iloc[-1]["time"],
                    "lower": zone.lower,
                    "upper": zone.upper,
                    "kind": f"{zone.kind} D1 · {zone.direction}",
                }
                for zone in zones
            ]
        )
        zone_chart = (
            alt.Chart(zone_data)
            .mark_rect(opacity=0.2)
            .encode(
                x=alt.X("start:T", title=None),
                x2="end:T",
                y=alt.Y("lower:Q", title="Preço"),
                y2="upper:Q",
                color=alt.Color(
                    "kind:N",
                    title="Objetivo D1",
                    scale=alt.Scale(range=["#42a5f5", "#ef5350"]),
                ),
                tooltip=[
                    alt.Tooltip("kind:N", title="Zona"),
                    alt.Tooltip("lower:Q", title="Mínimo", format=",.0f"),
                    alt.Tooltip("upper:Q", title="Máximo", format=",.0f"),
                ],
            )
        )
        chart = alt.layer(zone_chart, base_chart).resolve_scale(y="shared")
    else:
        chart = base_chart
    chart = chart.configure_view(strokeOpacity=0)
    st.altair_chart(chart, width="stretch")
    last_closed = data.iloc[-2] if len(data) > 1 else data.iloc[-1]
    cols = st.columns(4)
    for column, label, value in zip(
        cols,
        ["Abertura", "Máxima", "Mínima", "Fechamento"],
        [last_closed["open"], last_closed["high"], last_closed["low"], last_closed["close"]],
    ):
        column.metric(label, points(float(value)))


def render_checklist() -> ChecklistState:
    st.subheader("Checklist manual de decisão")
    c1, c2, c3 = st.columns(3)
    context_ok = c1.checkbox("M15: contexto definido", key="context_ok")
    sweep_ok = c1.checkbox("M5: sweep/manipulação", key="sweep_ok")
    mss_ok = c2.checkbox("M5: MSS e deslocamento", key="mss_ok")
    poi_ok = c2.checkbox("M1: FVG ou Order Block", key="poi_ok")
    retest_ok = c3.checkbox("M1: reteste confirmado", key="retest_ok")
    rr_ok = c3.checkbox("R:R mínimo atendido", key="rr_ok")
    return ChecklistState(context_ok, sweep_ok, mss_ok, poi_ok, retest_ok, rr_ok)


def render_book_detection(detection: PO3Detection) -> None:
    st.subheader("Leitura automática · Regra do livro")
    st.markdown(
        f'<div class="banner banner-{detection.color.lower()}">'
        f'{detection.phase} — {detection.summary}</div>',
        unsafe_allow_html=True,
    )
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Direção em avaliação", detection.direction or "Ainda não definida")
    if detection.accumulation_low is not None and detection.accumulation_high is not None:
        c2.metric(
            "Faixa de acumulação",
            f"{points(detection.accumulation_low)} — {points(detection.accumulation_high)}",
        )
    else:
        c2.metric("Faixa de acumulação", "Aguardando")
    if detection.fvg is not None:
        c3.metric("FVG M1", f"{points(detection.fvg.lower)} — {points(detection.fvg.upper)}")
    else:
        c3.metric("FVG M1", "Ainda não formado")
    if detection.order_block is not None:
        c4.metric(
            f"Order Block · {detection.order_block.validation}",
            f"{points(detection.order_block.lower)} — {points(detection.order_block.upper)}",
        )
    else:
        c4.metric("Order Block M1", "Ainda não validado")

    if detection.evidence:
        st.dataframe(
            pd.DataFrame(
                [{"Etapa": index, "Evidência": item} for index, item in enumerate(detection.evidence, start=1)]
            ),
            hide_index=True,
            width="stretch",
        )
    with st.expander("Sequência obrigatória do livro", expanded=False):
        st.markdown(
            "**Acumulação → falso rompimento/Judas Swing → rejeição ou MSS → "
            "distribuição → retorno ao FVG/Order Block → confirmação de continuidade.**"
        )
        st.caption(
            "O Single Candle Order Block é classificado como fraco, bom ou excelente. "
            "Stop, alvo, Mitigation Block e a decisão final permanecem manuais."
        )


def render_operation_planner() -> None:
    with st.expander("Planejador manual de operação", expanded=False):
        st.caption("Somente cálculo. Este painel não possui botão nem função de envio de ordem.")
        direction = st.radio("Direção", ["Compra", "Venda"], horizontal=True)
        c1, c2, c3 = st.columns(3)
        entry = c1.number_input("Entrada potencial", min_value=0.0, step=5.0, format="%.1f")
        stop = c2.number_input("Stop técnico", min_value=0.0, step=5.0, format="%.1f")
        target = c3.number_input("Alvo", min_value=0.0, step=5.0, format="%.1f")
        if entry and stop and target:
            ratio = calculate_rr(direction, entry, stop, target)
            if ratio is None:
                st.warning("Entrada, stop e alvo não formam uma operação válida nessa direção.")
            else:
                st.metric("Risco/retorno calculado", f"1 : {ratio:.2f}")


def render_options_panel(options_folder: str, auto_fetch: bool) -> None:
    st.subheader("Opções do índice · fonte gratuita")
    if auto_fetch:
        auto_download_b3(options_folder)
    latest = find_latest_csv(options_folder)
    if latest is None:
        st.info("Nenhuma cadeia encontrada. Coloque um CSV público da B3 na pasta de opções para atualizar automaticamente.")
        st.caption("Colunas exigidas: expiry, strike, type (C/P), last e volume.")
        return
    try:
        data = load_options_csv(latest)
    except (OSError, ValueError, pd.errors.ParserError) as exc:
        st.error(f"Não foi possível ler a cadeia: {exc}")
        return
    summary = option_summary(data)
    cols = st.columns(4)
    cols[0].metric("Linhas", f"{len(data):,}".replace(",", "."))
    cols[1].metric("Critério", "Volume diário")
    cols[2].metric("Maior Call · OI", "—" if summary["call_strike"] is None else points(float(summary["call_strike"])))
    cols[3].metric("Maior Put · OI", "—" if summary["put_strike"] is None else points(float(summary["put_strike"])))
    levels = summary["levels"]
    if not levels.empty:
        st.dataframe(levels.rename(columns={"strike": "Strike", "type": "Tipo", "volume": "Volume"}), hide_index=True, width="stretch")
    st.caption(f"Arquivo: {latest.name} · atualização {pd.Timestamp(latest.stat().st_mtime, unit='s').strftime('%d/%m/%Y %H:%M')}")


def render_macro(macro: dict) -> None:
    st.subheader("Viés macro operacional do WIN")
    if not macro or not macro.get("available"):
        st.warning("Não há dados macro suficientes no MT5 para calcular o viés.")
        return
    score = float(macro.get("score") or 0)
    bias = str(macro.get("bias", "indisponível")).upper()
    confidence = str(macro.get("confidence", "baixa")).upper()
    color = "#43d17a" if score >= 20 else "#f05d66" if score <= -20 else "#f2c14e"
    pct = max(0, min(100, (score + 100) / 2))
    st.markdown(
        f'''<div style="border:1px solid #303847;border-radius:16px;background:#171b24;padding:18px">
        <div style="display:flex;justify-content:space-between;align-items:center">
        <span style="font-size:1.55rem;font-weight:750;color:{color}">{bias}</span>
        <span style="color:#9aa5b5">confiança {confidence}</span></div>
        <div style="margin:16px 0 6px;height:18px;border-radius:12px;background:linear-gradient(90deg,#f05d66 0%,#f2c14e 50%,#43d17a 100%);position:relative">
        <div style="position:absolute;left:{pct}%;top:-7px;width:4px;height:32px;background:#fff;border-radius:3px;box-shadow:0 0 0 2px #101319"></div></div>
        <div style="display:flex;justify-content:space-between;color:#9aa5b5;font-size:.78rem"><span>-100 vendedor</span><b style="color:#e8edf5">{score:+.1f}</b><span>+100 comprador</span></div></div>''',
        unsafe_allow_html=True,
    )
    factors = macro.get("factors", [])
    if factors:
        table = pd.DataFrame(factors)
        table["direcao"] = table["direcao"].map(lambda x: f"{x:+.2f}")
        table["correlacao"] = table["correlacao"].map(lambda x: f"{x:+.2f}")
        table["contribuicao"] = table["contribuicao"].map(lambda x: f"{x:+.3f}")
        st.dataframe(table.rename(columns={"grupo":"Grupo","simbolo":"Símbolo","direcao":"Direção 20 barras","correlacao":"Correlação WIN","contribuicao":"Contribuição"}), hide_index=True, width="stretch")
    missing = macro.get("missing", [])
    if missing:
        st.caption("Ainda não disponíveis no MT5: " + ", ".join(missing) + ".")
    st.caption("Score baseado somente nos símbolos realmente encontrados no MT5. Correlação não é sinal isolado.")


def render_snapshot(snapshot: MarketSnapshot, detection_config: DetectionConfig, options_folder: str) -> None:
    connection = "MT5 conectado" if snapshot.connected else "Modo demonstração"
    cards = st.columns(4)
    values = [
        ("Ativo", snapshot.symbol),
        ("Último preço", points(snapshot.last_price)),
        ("Fonte", connection),
        ("Atualização", snapshot.as_of.strftime("%H:%M:%S")),
    ]
    for column, (label, value) in zip(cards, values):
        column.markdown(
            f'<div class="status-card"><div class="label">{label}</div><div class="value">{value}</div></div>',
            unsafe_allow_html=True,
        )
    if snapshot.account:
        st.subheader("Conta MT5 · somente leitura")
        account_cols = st.columns(5)
        labels = [("Saldo", "balance"), ("Patrimônio", "equity"), ("Margem usada", "margin"), ("Margem livre", "margin_free"), ("Nível de margem", "margin_level")]
        for column, (label, key) in zip(account_cols, labels):
            value = snapshot.account.get(key)
            if value is None:
                text_value = "—"
            elif key == "margin_level":
                text_value = f"{value:,.1f}%".replace(",", "X").replace(".", ",").replace("X", ".")
            else:
                text_value = f"R$ {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
            column.metric(label, text_value)

    detection = detect_book_po3(snapshot, detection_config)
    render_book_detection(detection)

    state = render_checklist()
    color, message = status_from_checklist(state)
    st.markdown(
        f'<div class="banner banner-{color.lower()}">{color} — {message}. Decisão e execução permanecem manuais.</div>',
        unsafe_allow_html=True,
    )

    for message_text in context_messages(snapshot):
        st.caption(message_text)

    tab_m15, tab_m5, tab_m1, tab_macro, tab_timeline = st.tabs(
        ["M15 · Contexto", "M5 · Estrutura", "M1 · Entrada", "Macro e opções", "Memória do pregão"]
    )
    with tab_m15:
        left, right = st.columns([1.6, 1])
        with left:
            render_chart(snapshot, "M15")
        with right:
            st.subheader("Objetivos D1 projetados no M15")
            render_zones(snapshot, "M15")
            st.subheader("Semana e mês anteriores")
            render_levels(snapshot, "M15")
    with tab_m5:
        left, right = st.columns([1.6, 1])
        with left:
            render_chart(snapshot, "M5")
        with right:
            st.subheader("Pregão anterior")
            render_levels(snapshot, "M5")
    with tab_m1:
        render_chart(snapshot, "M1")
        st.info("M1 reservado para FVG/OB, reteste e entrada de alta precisão.")
    with tab_macro:
        render_macro(snapshot.macro)
        render_options_panel(options_folder, auto_fetch_options)
        st.caption("A direção macro vem da leitura somente leitura do MT5; opções são contexto, não sinal automático.")
    with tab_timeline:
        events = snapshot.events
        if events:
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "Hora": event.time.strftime("%H:%M:%S"),
                            "Evento": event.title,
                            "Detalhe": event.detail,
                        }
                        for event in events
                    ]
                ),
                hide_index=True,
                width="stretch",
            )
        else:
            st.caption("Nenhum evento registrado ainda.")

    render_operation_planner()
    for note in snapshot.notes:
        st.caption(note)


st.markdown(
    '<div class="po3-header"><div class="po3-title">PO3 Copilot B3</div>'
    '<div class="safe-badge">SOMENTE LEITURA · EXECUÇÃO MANUAL</div></div>',
    unsafe_allow_html=True,
)

with st.sidebar:
    st.header("Conexão")
    mode = st.selectbox(
        "Fonte dos dados",
        ["Demonstração", "MT5 local — somente leitura"],
        index=1,
    )
    symbol = st.text_input("Ativo", value="WINV26").strip().upper() or "WINV26"
    terminal_path = st.text_input("Caminho do terminal", value=DEFAULT_TERMINAL)
    auto_update = st.toggle("Atualização automática", value=True)
    refresh_seconds = st.slider("Intervalo", min_value=2, max_value=30, value=5, step=1)
    options_folder = st.text_input("Pasta CSV de opções", value=str(Path(__file__).parent.parent / "data" / "opcoes"))
    auto_fetch_options = st.toggle("Buscar opções públicas B3", value=True)
    with st.expander("Parâmetros experimentais B3", expanded=False):
        st.caption("Quantificam termos qualitativos do livro e ainda precisam de backtest.")
        accumulation_bars = st.slider("Janela inicial M15 · candles", 3, 8, 4)
        accumulation_atr = st.slider("Amplitude máxima · ATR", 1.5, 5.0, 3.0, 0.25)
        mss_lookback = st.slider("Estrutura do MSS · candles M5", 3, 10, 5)
        displacement_factor = st.slider("Deslocamento · corpo típico", 1.0, 3.0, 1.5, 0.1)
        ob_excellent_factor = st.slider("Agressão excelente do OB · corpo típico", 1.5, 4.0, 2.0, 0.25)
    st.divider()
    st.caption("O painel não solicita login ou senha e não oferece comandos de negociação.")


run_every = f"{refresh_seconds}s" if auto_update else None
detection_config = DetectionConfig(
    accumulation_m15_bars=accumulation_bars,
    accumulation_max_atr=accumulation_atr,
    mss_lookback_m5=mss_lookback,
    displacement_body_factor=displacement_factor,
    ob_excellent_body_factor=ob_excellent_factor,
)


@st.fragment(run_every=run_every)
def live_panel() -> None:
    if mode == "Demonstração":
        render_snapshot(build_demo_snapshot(symbol), detection_config, options_folder)
        return
    try:
        render_snapshot(read_snapshot(terminal_path, symbol), detection_config, options_folder)
    except MT5ReadError as exc:
        st.error(str(exc))
        st.info("Abra o MT5 com o ativo visível ou use o modo Demonstração.")


live_panel()

st.markdown(
    '<p class="small-note">V2 experimental: PO3, FVG/Order Block, score macro do WIN e velocímetro. Dados ausentes ficam sinalizados; stop, alvo e execução permanecem manuais até validação estatística.</p>',
    unsafe_allow_html=True,
)
