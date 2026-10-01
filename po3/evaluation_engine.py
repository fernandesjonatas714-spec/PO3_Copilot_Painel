"""Métricas descritivas e determinísticas da avaliação factual V2.

As funções novas deste módulo nunca interpretam Outcomes como trades e não
alteram confiança, prompts, MarketState ou qualquer decisão de produção.
As funções legadas permanecem disponíveis para compatibilidade da V1.
"""
from __future__ import annotations

from statistics import mean, median
from typing import Iterable

EVALUATION_VERSION = "1.0.0"
HORIZONS = ("5m", "15m", "30m", "60m")
FACTUAL_STATUS = "DISPONIVEL"
KNOWN_STATUSES = {"PENDENTE", "PENDENTE_DADOS", "DISPONIVEL", "SEM_DADO", "MERCADO_FECHADO"}


def direction_match(bias: str | None, change: float | None) -> bool | None:
    if not bias or change is None or bias.lower() in {"neutro", "neutral"}:
        return None
    b = bias.lower()
    return (change > 0) == ("compr" in b or "alta" in b)


def summarize(records: list[dict]) -> dict:
    """Compatibilidade V1; não é usada pela Analytics V2."""
    checked = [r for r in records if r.get("acerto") is not None]
    return {"total": len(records), "avaliados": len(checked), "acertos": sum(bool(r["acerto"]) for r in checked),
            "taxa_acerto": (sum(bool(r["acerto"]) for r in checked) / len(checked) if checked else None),
            "pendentes": sum(r.get("status") == "PENDENTE" for r in records)}


def calibration_buckets(records: list[dict]) -> dict:
    """Compatibilidade V1; não é usada pela Analytics V2."""
    out = {"Alta": [], "Média": [], "Baixa": []}
    for r in records:
        if r.get("confianca") in out:
            out[r["confianca"]].append(r)
    return {k: summarize(v) for k, v in out.items()}


def sample_band(size: int) -> str:
    if size < 30:
        return "INSUFICIENTE"
    if size < 100:
        return "PRELIMINAR"
    if size < 200:
        return "UTIL"
    return "ROBUSTA"


def _numbers(records: Iterable[dict], field: str) -> list[float]:
    values = []
    for row in records:
        value = row.get(field)
        if value is not None:
            try:
                values.append(float(value))
            except (TypeError, ValueError):
                continue
    return values


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * percentile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def descriptive_stats(records: Iterable[dict], field: str) -> dict:
    values = _numbers(records, field)
    if not values:
        return {"count": 0, "mean": None, "median": None, "min": None, "max": None, "p25": None, "p75": None}
    return {"count": len(values), "mean": mean(values), "median": median(values),
            "min": min(values), "max": max(values), "p25": _percentile(values, .25),
            "p75": _percentile(values, .75)}


def status_counts(records: Iterable[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in records:
        status = str(row.get("status") or "DESCONHECIDO")
        counts[status] = counts.get(status, 0) + 1
    return counts


def directional_distribution(records: Iterable[dict]) -> dict:
    values = _numbers(records, "percentage_change")
    positive = sum(value > 0 for value in values)
    negative = sum(value < 0 for value in values)
    flat = sum(value == 0 for value in values)
    total = len(values)
    rate = lambda value: value / total if total else None
    return {"positive": positive, "negative": negative, "zero": flat,
            "positive_move_rate": rate(positive), "negative_move_rate": rate(negative),
            "flat_move_rate": rate(flat)}


def evaluate_horizon(market_states: list[dict], outcomes: list[dict], horizon: str) -> dict:
    state_ids = {row.get("id") for row in market_states}
    rows = [row for row in outcomes if row.get("horizon_code") == horizon and row.get("market_state_id") in state_ids]
    available = [row for row in rows if row.get("status") == FACTUAL_STATUS and row.get("percentage_change") is not None]
    metrics = {field: descriptive_stats(available, field) for field in
               ("percentage_change", "absolute_change", "high_delta", "low_delta")}
    state_count = len(market_states)
    return {"horizon": horizon, "total_market_states": state_count, "total_outcomes": len(rows),
            "status": status_counts(rows), "available_sample_size": len(available),
            "coverage_rate": len(rows) / state_count if state_count else None,
            "sample_band": sample_band(len(available)), "metrics": metrics,
            "directional_distribution": directional_distribution(available)}


def data_quality(market_states: list[dict], outcomes: list[dict]) -> dict:
    state_ids = {row.get("id") for row in market_states}
    expected = {(state_id, horizon) for state_id in state_ids for horizon in HORIZONS}
    actual = [(row.get("market_state_id"), row.get("horizon_code")) for row in outcomes]
    available = [row for row in outcomes if row.get("status") == FACTUAL_STATUS]
    known = {row.get("horizon_code") for row in outcomes}
    by_symbol: dict[str, int] = {}
    for row in outcomes:
        symbol = str(row.get("symbol") or "DESCONHECIDO")
        by_symbol[symbol] = by_symbol.get(symbol, 0) + 1
    return {"market_states_without_expected_outcome": len(expected - set(actual)),
            "orphan_outcomes": sum(row.get("market_state_id") not in state_ids for row in outcomes),
            "duplicate_market_state_horizon": len(actual) - len(set(actual)),
            "available_without_future_price": sum(row.get("future_price") is None for row in available),
            "available_without_percentage_change": sum(row.get("percentage_change") is None for row in available),
            "start_price_invalid_or_null": sum(row.get("start_price") is None for row in outcomes),
            "unknown_statuses": sorted({str(row.get("status")) for row in outcomes if row.get("status") not in KNOWN_STATUSES}),
            "outcomes_by_symbol": by_symbol,
            "first_cutoff": min((row.get("cutoff_at_utc") for row in market_states), default=None),
            "last_cutoff": max((row.get("cutoff_at_utc") for row in market_states), default=None),
            "first_outcome_available": min((row.get("observed_at_utc") for row in available if row.get("observed_at_utc")), default=None),
            "last_outcome_available": max((row.get("observed_at_utc") for row in available if row.get("observed_at_utc")), default=None),
            "horizons_observed": sorted(known)}
