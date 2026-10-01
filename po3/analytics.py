"""Montagem read-only dos relatórios descritivos da avaliação V2."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from po3.evaluation_engine import EVALUATION_VERSION, HORIZONS, data_quality, evaluate_horizon
from po3.storage.market_repository import select_v2_evaluation_data

SAO_PAULO = ZoneInfo("America/Sao_Paulo")


def _temporal(states: list[dict], outcomes: list[dict]) -> list[dict]:
    state_by_id = {row.get("id"): row for row in states}
    grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for outcome in outcomes:
        if outcome.get("status") != "DISPONIVEL" or outcome.get("percentage_change") is None:
            continue
        state = state_by_id.get(outcome.get("market_state_id"))
        if not state or not state.get("cutoff_at_utc"):
            continue
        cutoff = datetime.fromisoformat(str(state["cutoff_at_utc"])).astimezone(SAO_PAULO)
        grouped[(cutoff.date().isoformat(), f"{cutoff.hour:02d}h")].append(outcome)
    rows = []
    for (date, hour), values in sorted(grouped.items()):
        def median(field):
            numbers = [float(row[field]) for row in values if row.get(field) is not None]
            if not numbers:
                return None
            numbers.sort()
            middle = len(numbers) // 2
            return numbers[middle] if len(numbers) % 2 else (numbers[middle - 1] + numbers[middle]) / 2
        rows.append({"date": date, "hour": hour, "available": len(values),
                     "median_percentage_change": median("percentage_change"),
                     "median_high_delta": median("high_delta"),
                     "median_low_delta": median("low_delta")})
    return rows


def build_evaluation_report(db_path: str, symbol: str | None = None, *, generated_at_utc: datetime | None = None) -> dict:
    """Gera um relatório sem qualquer INSERT/UPDATE/DELETE no banco."""
    states, outcomes = select_v2_evaluation_data(db_path, symbol)
    symbols = sorted({str(row.get("symbol")) for row in states + outcomes if row.get("symbol")})
    return {"evaluation_version": EVALUATION_VERSION,
            "generated_at_utc": (generated_at_utc or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat(),
            "symbol": symbol or (symbols[0] if len(symbols) == 1 else None),
            "symbols": symbols,
            "market_states": len(states),
            "outcomes": len(outcomes),
            "horizons": {horizon: evaluate_horizon(states, outcomes, horizon) for horizon in HORIZONS},
            "data_quality": data_quality(states, outcomes),
            "temporal": _temporal(states, outcomes)}
