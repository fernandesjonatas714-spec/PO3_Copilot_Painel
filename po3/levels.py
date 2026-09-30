from __future__ import annotations

from collections.abc import Sequence

from .models import PriceLevel, PriceZone


def previous_completed_bar(bars: Sequence[dict]) -> dict:
    """Retorna a barra concluida imediatamente anterior a barra atual."""
    if len(bars) < 2:
        raise ValueError("Sao necessarias pelo menos duas barras.")
    ordered = sorted(bars, key=lambda bar: bar["time"])
    return ordered[-2]


def _ohlc_levels(bar: dict, prefix: str, group: str) -> list[PriceLevel]:
    high = float(bar["high"])
    low = float(bar["low"])
    open_price = float(bar["open"])
    close = float(bar["close"])
    equilibrium = (high + low) / 2.0
    return [
        PriceLevel(f"P{prefix}H", f"Maxima {group} anterior", high, group),
        PriceLevel(f"P{prefix}L", f"Minima {group} anterior", low, group),
        PriceLevel(f"P{prefix}O", f"Abertura {group} anterior", open_price, group),
        PriceLevel(f"P{prefix}C", f"Fechamento {group} anterior", close, group),
        PriceLevel(f"P{prefix}50", f"Equilibrio 50% {group} anterior", equilibrium, group),
    ]


def build_context_levels(
    daily_bars: Sequence[dict],
    weekly_bars: Sequence[dict],
    monthly_bars: Sequence[dict],
) -> dict[str, list[PriceLevel]]:
    daily = _ohlc_levels(previous_completed_bar(daily_bars), "D", "diario")
    weekly_all = _ohlc_levels(previous_completed_bar(weekly_bars), "W", "semanal")
    monthly_all = _ohlc_levels(previous_completed_bar(monthly_bars), "M", "mensal")

    keep = {"PWH", "PWL", "PW50", "PMH", "PML", "PM50"}
    return {
        "M15": [level for level in weekly_all + monthly_all if level.code in keep],
        "M5": daily,
        "M1": [],
    }


def _closed(bars: Sequence[dict]) -> list[dict]:
    ordered = sorted(bars, key=lambda bar: bar["time"])
    return ordered[:-1] if len(ordered) > 1 else []


def _untouched(lower: float, upper: float, later_bars: Sequence[dict]) -> bool:
    return not any(float(bar["low"]) <= upper and float(bar["high"]) >= lower for bar in later_bars)


def build_active_zones(
    source_bars: Sequence[dict], timeframe: str, max_zones: int = 6
) -> list[PriceZone]:
    """Encontra FVGs e Single Candle OBs ativos no próprio período de origem."""
    bars = _closed(source_bars)
    if len(bars) < 3:
        return []

    zones: list[PriceZone] = []
    bodies = [abs(float(bar["close"]) - float(bar["open"])) for bar in bars]
    typical_body = sorted(bodies)[len(bodies) // 2] or 1.0

    for index in range(2, len(bars)):
        left = bars[index - 2]
        right = bars[index]
        later = bars[index + 1 :]
        if float(right["low"]) > float(left["high"]):
            lower, upper = float(left["high"]), float(right["low"])
            if _untouched(lower, upper, later):
                zones.append(PriceZone("FVG", "COMPRA", lower, upper, right["time"], timeframe))
        elif float(right["high"]) < float(left["low"]):
            lower, upper = float(right["high"]), float(left["low"])
            if _untouched(lower, upper, later):
                zones.append(PriceZone("FVG", "VENDA", lower, upper, right["time"], timeframe))

    for index in range(len(bars) - 1):
        candle = bars[index]
        impulse = bars[index + 1]
        candle_body = abs(float(candle["close"]) - float(candle["open"]))
        impulse_body = abs(float(impulse["close"]) - float(impulse["open"]))
        if impulse_body < max(candle_body * 1.5, typical_body * 1.5):
            continue
        direction = "COMPRA" if float(impulse["close"]) > float(impulse["open"]) else "VENDA"
        opposite = float(candle["close"]) < float(candle["open"]) if direction == "COMPRA" else float(candle["close"]) > float(candle["open"])
        if not opposite:
            continue
        lower, upper = float(candle["low"]), float(candle["high"])
        if _untouched(lower, upper, bars[index + 2 :]):
            zones.append(PriceZone("OB", direction, lower, upper, candle["time"], timeframe))

    unique = {(zone.kind, zone.direction, zone.lower, zone.upper): zone for zone in zones}
    return sorted(unique.values(), key=lambda zone: zone.created_at, reverse=True)[:max_zones]


def build_daily_zones(daily_bars: Sequence[dict], max_zones: int = 6) -> list[PriceZone]:
    """Compatibilidade: zonas D1 destinadas à projeção no M15."""
    return build_active_zones(daily_bars, "D1", max_zones)
