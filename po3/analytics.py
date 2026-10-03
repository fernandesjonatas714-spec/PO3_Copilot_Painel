"""Montagem read-only dos relatórios descritivos da avaliação V2."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from po3.evaluation_engine import EVALUATION_VERSION, HORIZONS, data_quality, evaluate_horizon
from po3.storage.market_repository import select_v2_evaluation_data, select_v2_m1_bars

SAO_PAULO = ZoneInfo("America/Sao_Paulo")
AGGREGATED_HORIZONS = ("Diário", "Semanal", "Mensal")


def _temporal(states: list[dict], outcomes: list[dict]) -> list[dict]:
    state_by_id = {row.get("id"): row for row in states}
    grouped: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    for outcome in outcomes:
        if outcome.get("status") != "DISPONIVEL" or outcome.get("percentage_change") is None:
            continue
        state = state_by_id.get(outcome.get("market_state_id"))
        if not state or not state.get("cutoff_at_utc"):
            continue
        cutoff = datetime.fromisoformat(str(state["cutoff_at_utc"])).astimezone(SAO_PAULO)
        horizon = str(outcome.get("horizon_code") or "DESCONHECIDO")
        grouped[(cutoff.date().isoformat(), f"{cutoff.hour:02d}h", horizon)].append(outcome)
    rows = []
    for (date, hour, horizon), values in sorted(grouped.items()):
        def median(field):
            numbers = [float(row[field]) for row in values if row.get(field) is not None]
            if not numbers:
                return None
            numbers.sort()
            middle = len(numbers) // 2
            return numbers[middle] if len(numbers) % 2 else (numbers[middle - 1] + numbers[middle]) / 2
        rows.append({"date": date, "hour": hour, "horizon": horizon, "available": len(values),
                     "median_percentage_change": median("percentage_change"),
                     "median_high_delta": median("high_delta"),
                     "median_low_delta": median("low_delta")})
    return rows


def _bar_datetime(value) -> datetime:
    parsed = datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(SAO_PAULO)


def _period_key(local_dt: datetime, horizon: str):
    if horizon == "Diário":
        return local_dt.date()
    if horizon == "Semanal":
        start = local_dt.date() - timedelta(days=local_dt.weekday())
        return start
    return (local_dt.year, local_dt.month)


def _period_end(key, horizon: str) -> date:
    if horizon == "Diário":
        return key + timedelta(days=1)
    if horizon == "Semanal":
        return key + timedelta(days=7)
    year, month = key
    return date(year + (month == 12), 1 if month == 12 else month + 1, 1)


def _complete_period(rows: list[dict], key, horizon: str, generated_local: datetime) -> bool:
    """Exige período encerrado e evidência factual de abertura/fechamento."""
    if horizon == "Diário":
        if key > generated_local.date() or (key == generated_local.date() and generated_local.time() < time(18, 30)):
            return False
    elif _period_end(key, horizon) > generated_local.date():
        return False
    local_times = [_bar_datetime(row["timestamp_utc"]) for row in rows]
    if not local_times:
        return False
    # A sessão configurada do WIN começa às 09:00 e termina às 18:30.
    # Para semanas/meses, feriados são aceitos: só o primeiro/último pregão
    # factual precisa cobrir a abertura e o fechamento da sessão observada.
    return min(local_times).time() <= time(9, 0) and max(local_times).time() >= time(18, 29)


def _aggregated_horizon(bars: list[dict], horizon: str, generated_at_utc: datetime) -> dict:
    grouped: dict[object, list[dict]] = defaultdict(list)
    for bar in bars:
        try:
            grouped[_period_key(_bar_datetime(bar["timestamp_utc"]), horizon)].append(bar)
        except (KeyError, TypeError, ValueError):
            continue
    generated_local = generated_at_utc.astimezone(SAO_PAULO)
    records = []
    for key, rows in sorted(grouped.items(), key=lambda item: item[0]):
        rows.sort(key=lambda row: row["timestamp_utc"])
        if not _complete_period(rows, key, horizon, generated_local):
            continue
        try:
            start_price = float(rows[0]["open"])
            final_price = float(rows[-1]["close"])
            period_high = max(float(row["high"]) for row in rows)
            period_low = min(float(row["low"]) for row in rows)
        except (KeyError, TypeError, ValueError):
            continue
        if start_price <= 0:
            continue
        absolute_change = final_price - start_price
        records.append({
            "absolute_change": absolute_change,
            "high_delta": period_high - start_price,
            "low_delta": period_low - start_price,
            "percentage_change": absolute_change / start_price * 100,
        })
    metrics = {field: _stats(records, field) for field in
               ("percentage_change", "absolute_change", "high_delta", "low_delta")}
    return {
        "horizon": horizon,
        "total_market_states": 0,
        "total_outcomes": len(records),
        "status": {"DISPONIVEL": len(records)} if records else {},
        "available_sample_size": len(records),
        "coverage_rate": None,
        "sample_band": _sample_band(len(records)),
        "metrics": metrics,
        "directional_distribution": _directional(records),
    }


def _stats(records: list[dict], field: str) -> dict:
    values = sorted(float(row[field]) for row in records if row.get(field) is not None)
    if not values:
        return {"count": 0, "mean": None, "median": None, "min": None, "max": None, "p25": None, "p75": None}
    def percentile(pct):
        if len(values) == 1:
            return values[0]
        position = (len(values) - 1) * pct
        lower = int(position)
        upper = min(lower + 1, len(values) - 1)
        return values[lower] + (values[upper] - values[lower]) * (position - lower)
    middle = len(values) // 2
    med = values[middle] if len(values) % 2 else (values[middle - 1] + values[middle]) / 2
    return {"count": len(values), "mean": sum(values) / len(values), "median": med,
            "min": values[0], "max": values[-1], "p25": percentile(.25), "p75": percentile(.75)}


def _sample_band(size: int) -> str:
    if size < 30:
        return "INSUFICIENTE"
    if size < 100:
        return "PRELIMINAR"
    if size < 200:
        return "UTIL"
    return "ROBUSTA"


def _directional(records: list[dict]) -> dict:
    positive = sum(float(row["absolute_change"]) > 0 for row in records)
    negative = sum(float(row["absolute_change"]) < 0 for row in records)
    zero = len(records) - positive - negative
    total = len(records)
    rate = lambda value: value / total if total else None
    return {"positive": positive, "negative": negative, "zero": zero,
            "positive_move_rate": rate(positive), "negative_move_rate": rate(negative),
            "flat_move_rate": rate(zero)}


def build_evaluation_report(db_path: str, symbol: str | None = None, *, generated_at_utc: datetime | None = None) -> dict:
    """Gera um relatório sem qualquer INSERT/UPDATE/DELETE no banco."""
    states, outcomes = select_v2_evaluation_data(db_path, symbol)
    generated = generated_at_utc or datetime.now(timezone.utc)
    if generated.tzinfo is None:
        generated = generated.replace(tzinfo=timezone.utc)
    bars = select_v2_m1_bars(db_path, symbol)
    symbols = sorted({str(row.get("symbol")) for row in states + outcomes if row.get("symbol")})
    return {"evaluation_version": EVALUATION_VERSION,
            "generated_at_utc": generated.astimezone(timezone.utc).isoformat(),
            "symbol": symbol or (symbols[0] if len(symbols) == 1 else None),
            "symbols": symbols,
            "market_states": len(states),
            "outcomes": len(outcomes),
            "horizons": {**{horizon: evaluate_horizon(states, outcomes, horizon) for horizon in HORIZONS},
                         **{horizon: _aggregated_horizon(bars, horizon, generated) for horizon in AGGREGATED_HORIZONS}},
            "data_quality": data_quality(states, outcomes),
            "temporal": _temporal(states, outcomes)}
