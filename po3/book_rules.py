from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from statistics import median
from typing import Iterable

from .models import MarketSnapshot


@dataclass(frozen=True)
class DetectionConfig:
    """Parâmetros mensuráveis da adaptação B3, ainda sujeitos a backtest."""

    accumulation_m15_bars: int = 4
    accumulation_max_atr: float = 3.0
    mss_lookback_m5: int = 5
    displacement_body_factor: float = 1.5
    ob_excellent_body_factor: float = 2.0


@dataclass(frozen=True)
class FairValueGap:
    direction: str
    lower: float
    upper: float
    created_at: datetime


@dataclass(frozen=True)
class OrderBlock:
    direction: str
    lower: float
    upper: float
    created_at: datetime
    validated_at: datetime
    validation: str


@dataclass
class PO3Detection:
    stage: int
    phase: str
    color: str
    summary: str
    direction: str | None = None
    accumulation_low: float | None = None
    accumulation_high: float | None = None
    accumulation_start: datetime | None = None
    accumulation_end: datetime | None = None
    sweep_time: datetime | None = None
    mss_time: datetime | None = None
    fvg: FairValueGap | None = None
    order_block: OrderBlock | None = None
    retest_time: datetime | None = None
    evidence: list[str] = field(default_factory=list)


def _closed(bars: Iterable[dict]) -> list[dict]:
    ordered = sorted(bars, key=lambda bar: bar["time"])
    return ordered[:-1] if len(ordered) > 1 else []


def _true_ranges(bars: list[dict]) -> list[float]:
    ranges: list[float] = []
    previous_close: float | None = None
    for bar in bars:
        high = float(bar["high"])
        low = float(bar["low"])
        if previous_close is None:
            value = high - low
        else:
            value = max(high - low, abs(high - previous_close), abs(low - previous_close))
        if value > 0:
            ranges.append(value)
        previous_close = float(bar["close"])
    return ranges


def _body(bar: dict) -> float:
    return abs(float(bar["close"]) - float(bar["open"]))


def _find_fvg(bars: list[dict], direction: str, after: datetime) -> FairValueGap | None:
    eligible = [bar for bar in bars if bar["time"] >= after]
    for index in range(2, len(eligible)):
        first = eligible[index - 2]
        third = eligible[index]
        if direction == "COMPRA" and float(third["low"]) > float(first["high"]):
            return FairValueGap(
                direction=direction,
                lower=float(first["high"]),
                upper=float(third["low"]),
                created_at=third["time"],
            )
        if direction == "VENDA" and float(third["high"]) < float(first["low"]):
            return FairValueGap(
                direction=direction,
                lower=float(third["high"]),
                upper=float(first["low"]),
                created_at=third["time"],
            )
    return None


def _find_retest(bars: list[dict], gap: FairValueGap) -> datetime | None:
    return _find_zone_retest(
        bars,
        gap.direction,
        gap.lower,
        gap.upper,
        gap.created_at,
    )


def _find_zone_retest(
    bars: list[dict],
    direction: str,
    lower: float,
    upper: float,
    after: datetime,
) -> datetime | None:
    for bar in bars:
        if bar["time"] <= after:
            continue
        overlaps = float(bar["low"]) <= upper and float(bar["high"]) >= lower
        if not overlaps:
            continue
        bullish_confirmation = (
            direction == "COMPRA"
            and float(bar["close"]) > float(bar["open"])
            and float(bar["close"]) >= upper
        )
        bearish_confirmation = (
            direction == "VENDA"
            and float(bar["close"]) < float(bar["open"])
            and float(bar["close"]) <= lower
        )
        if bullish_confirmation or bearish_confirmation:
            return bar["time"]
    return None


def _find_order_block(
    bars: list[dict],
    direction: str,
    sweep_time: datetime,
    displacement_time: datetime,
    gap: FairValueGap | None,
    excellent_body_factor: float,
) -> OrderBlock | None:
    """Localiza o Single Candle OB descrito nas páginas 89–93 do livro."""

    candidates = [
        (index, bar)
        for index, bar in enumerate(bars)
        if sweep_time <= bar["time"] < displacement_time
        and (
            (direction == "COMPRA" and float(bar["close"]) < float(bar["open"]))
            or (direction == "VENDA" and float(bar["close"]) > float(bar["open"]))
        )
    ]
    impulse_end = displacement_time + timedelta(minutes=5)
    for candidate_index, candidate in reversed(candidates):
        lower = float(candidate["low"])
        upper = float(candidate["high"])
        candle_size = upper - lower
        if candle_size <= 0:
            continue
        impulse = [bar for bar in bars if displacement_time <= bar["time"] < impulse_end]
        if not impulse:
            continue

        if direction == "COMPRA":
            breakout = [bar for bar in impulse if float(bar["close"]) > upper]
            favorable_distance = max(float(bar["high"]) for bar in impulse) - upper
            directional = lambda bar: float(bar["close"]) > float(bar["open"])
        else:
            breakout = [bar for bar in impulse if float(bar["close"]) < lower]
            favorable_distance = lower - min(float(bar["low"]) for bar in impulse)
            directional = lambda bar: float(bar["close"]) < float(bar["open"])
        if not breakout:
            continue

        validation = "BOA" if favorable_distance >= 2.0 * candle_size else "FRACA"
        prior_bodies = [
            _body(bar)
            for bar in bars[max(0, candidate_index - 20) : candidate_index]
            if _body(bar) > 0
        ]
        typical_body = median(prior_bodies) if prior_bodies else 0.0
        aggressive = any(
            directional(bar)
            and (typical_body == 0.0 or _body(bar) >= typical_body * excellent_body_factor)
            for bar in impulse
        )
        if validation == "BOA" and aggressive:
            validation = "EXCELENTE"

        if validation in {"BOA", "EXCELENTE"}:
            if direction == "COMPRA":
                target = upper + 2.0 * candle_size
                validated = next(bar for bar in impulse if float(bar["high"]) >= target)
            else:
                target = lower - 2.0 * candle_size
                validated = next(bar for bar in impulse if float(bar["low"]) <= target)
        else:
            validated = breakout[0]

        # O FVG não é obrigatório para existir OB, mas é registrado como confluência.
        _ = gap
        return OrderBlock(
            direction=direction,
            lower=lower,
            upper=upper,
            created_at=candidate["time"],
            validated_at=validated["time"],
            validation=validation,
        )
    return None


def _evaluate_sweep(
    m5: list[dict],
    m1: list[dict],
    sweep_index: int,
    direction: str,
    config: DetectionConfig,
) -> PO3Detection:
    sweep = m5[sweep_index]
    prior = m5[max(0, sweep_index - config.mss_lookback_m5) : sweep_index]
    result = PO3Detection(
        stage=2,
        phase="MANIPULAÇÃO",
        color="AMARELO",
        summary="Falso rompimento detectado; aguardando MSS e deslocamento.",
        direction=direction,
        sweep_time=sweep["time"],
        evidence=[f"Manipulação potencial de {direction.lower()} em {sweep['time']:%H:%M}."],
    )
    if not prior:
        return result

    if direction == "COMPRA":
        structure_level = max(float(bar["high"]) for bar in prior)
        confirms_mss = lambda bar: float(bar["close"]) > structure_level
        correct_body = lambda bar: float(bar["close"]) > float(bar["open"])
    else:
        structure_level = min(float(bar["low"]) for bar in prior)
        confirms_mss = lambda bar: float(bar["close"]) < structure_level
        correct_body = lambda bar: float(bar["close"]) < float(bar["open"])

    baseline_bodies = [_body(bar) for bar in m5[max(0, sweep_index - 20) : sweep_index] if _body(bar) > 0]
    typical_body = median(baseline_bodies) if baseline_bodies else 0.0
    later = m5[sweep_index + 1 :]
    mss_index: int | None = None
    for index, bar in enumerate(later):
        if confirms_mss(bar):
            mss_index = index
            break
    if mss_index is None:
        return result

    mss_bar = later[mss_index]
    displacement_window = later[mss_index : mss_index + 3]
    displacement = next(
        (
            bar
            for bar in displacement_window
            if correct_body(bar)
            and (typical_body == 0.0 or _body(bar) >= typical_body * config.displacement_body_factor)
        ),
        None,
    )
    if displacement is None:
        result.phase = "MSS"
        result.summary = "MSS detectado, mas o deslocamento ainda não atingiu o parâmetro experimental."
        result.mss_time = mss_bar["time"]
        result.evidence.append(f"MSS de {direction.lower()} em {mss_bar['time']:%H:%M}.")
        return result

    result.stage = 3
    result.phase = "DISTRIBUIÇÃO"
    result.summary = "MSS e deslocamento confirmados; aguardando FVG e retorno."
    result.mss_time = mss_bar["time"]
    result.evidence.extend(
        [
            f"MSS de {direction.lower()} em {mss_bar['time']:%H:%M}.",
            f"Deslocamento direcional em {displacement['time']:%H:%M}.",
        ]
    )

    gap = _find_fvg(m1, direction, displacement["time"])
    order_block = _find_order_block(
        m1,
        direction,
        sweep["time"],
        displacement["time"],
        gap,
        config.ob_excellent_body_factor,
    )
    if gap is None and order_block is None:
        return result
    result.stage = 4
    result.phase = "AGUARDANDO RETESTE"
    result.summary = "Zona de interesse formada durante a distribuição; aguardando retorno e confirmação."
    result.fvg = gap
    result.order_block = order_block
    if gap is not None:
        result.evidence.append(
            f"FVG {direction.lower()} entre {gap.lower:,.0f} e {gap.upper:,.0f}, criado às {gap.created_at:%H:%M}."
        )
    if order_block is not None:
        confluence = " com FVG no deslocamento" if gap is not None else ""
        result.evidence.append(
            f"Order Block {direction.lower()} {order_block.validation.lower()} entre "
            f"{order_block.lower:,.0f} e {order_block.upper:,.0f}, criado às "
            f"{order_block.created_at:%H:%M}{confluence}."
        )

    retests: list[datetime] = []
    if gap is not None:
        gap_retest = _find_retest(m1, gap)
        if gap_retest is not None:
            retests.append(gap_retest)
    if order_block is not None:
        ob_retest = _find_zone_retest(
            m1,
            direction,
            order_block.lower,
            order_block.upper,
            order_block.validated_at,
        )
        if ob_retest is not None:
            retests.append(ob_retest)
    if not retests:
        return result
    retest_time = min(retests)
    result.stage = 5
    result.phase = "SEQUÊNCIA COMPLETA"
    result.color = "VERDE"
    result.summary = "Reteste e continuidade confirmados; validar stop, alvo e R:R antes da decisão manual."
    result.retest_time = retest_time
    result.evidence.append(f"Reteste com confirmação em {retest_time:%H:%M}.")
    return result


def detect_book_po3(snapshot: MarketSnapshot, config: DetectionConfig | None = None) -> PO3Detection:
    """Detecta a sequência do livro usando somente candles concluídos."""

    config = config or DetectionConfig()
    m15 = _closed(snapshot.bars.get("M15", []))
    m5 = _closed(snapshot.bars.get("M5", []))
    m1 = _closed(snapshot.bars.get("M1", []))
    if len(m15) < config.accumulation_m15_bars or len(m5) < 3 or len(m1) < 3:
        return PO3Detection(0, "AGUARDANDO DADOS", "VERMELHO", "Histórico insuficiente para avaliar a sequência.")

    latest_session = m15[-1]["time"].date()
    session_m15 = [bar for bar in m15 if bar["time"].date() == latest_session]
    if len(session_m15) < config.accumulation_m15_bars:
        return PO3Detection(0, "AGUARDANDO ACUMULAÇÃO", "VERMELHO", "A janela inicial M15 ainda não terminou.")

    accumulation = session_m15[: config.accumulation_m15_bars]
    acc_low = min(float(bar["low"]) for bar in accumulation)
    acc_high = max(float(bar["high"]) for bar in accumulation)
    acc_width = acc_high - acc_low
    history_before_end = [bar for bar in m15 if bar["time"] <= accumulation[-1]["time"]][-20:]
    ranges = _true_ranges(history_before_end)
    typical_range = median(ranges) if ranges else 0.0
    narrow = typical_range == 0.0 or acc_width <= typical_range * config.accumulation_max_atr

    accumulation_end = accumulation[-1]["time"] + timedelta(minutes=15)
    base = PO3Detection(
        stage=1 if narrow else 0,
        phase="ACUMULAÇÃO" if narrow else "SEM FAIXA ESTREITA",
        color="AMARELO" if narrow else "VERMELHO",
        summary=(
            "Faixa inicial próxima da abertura identificada; aguardando falso rompimento."
            if narrow
            else "A faixa inicial excedeu o limite experimental; nenhum PO3 confirmado."
        ),
        accumulation_low=acc_low,
        accumulation_high=acc_high,
        accumulation_start=accumulation[0]["time"],
        accumulation_end=accumulation_end,
        evidence=[
            f"Faixa inicial M15: {acc_low:,.0f} a {acc_high:,.0f} ({config.accumulation_m15_bars} candles).",
            f"Amplitude/ATR típico: {(acc_width / typical_range):.2f}x." if typical_range else "ATR típico indisponível.",
        ],
    )
    if not narrow:
        return base

    session_m5 = [bar for bar in m5 if bar["time"].date() == latest_session]
    candidates: list[tuple[int, str]] = []
    for index, bar in enumerate(session_m5):
        if bar["time"] < accumulation_end:
            continue
        bullish_sweep = float(bar["low"]) < acc_low and float(bar["close"]) >= acc_low
        bearish_sweep = float(bar["high"]) > acc_high and float(bar["close"]) <= acc_high
        if bullish_sweep:
            candidates.append((index, "COMPRA"))
        if bearish_sweep:
            candidates.append((index, "VENDA"))
    if not candidates:
        return base

    session_m1 = [bar for bar in m1 if bar["time"].date() == latest_session]
    evaluated = [_evaluate_sweep(session_m5, session_m1, index, direction, config) for index, direction in candidates]
    best = max(evaluated, key=lambda item: (item.stage, item.sweep_time or datetime.min))
    best.accumulation_low = base.accumulation_low
    best.accumulation_high = base.accumulation_high
    best.accumulation_start = base.accumulation_start
    best.accumulation_end = base.accumulation_end
    best.evidence = base.evidence + best.evidence
    return best
