"""Benchmark observacional e somente leitura do Decision Engine V2."""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
import sqlite3
from pathlib import Path
from typing import Any, Iterable

from po3.evaluation_engine import sample_band

BENCHMARK_VERSION = "1.0.0"
EXPECTED_DECISION_IDS = (
    "regime_macro", "contexto_domestico", "contexto_tecnico",
    "risco_evento", "conflito_contexto", "contexto_operacional",
)
VALID_CONFIDENCES = {"ALTA", "MEDIA", "BAIXA"}
VALID_EVIDENCE = {"COMPLETAS", "PARCIAIS", "INSUFICIENTES", "CONFLITANTES"}
VALID_GATES = {"VALIDO", "REVISAO", "BLOQUEADO"}
VALID_CONSENSUS = {"CONSENSO", "DIVERGENCIA", "NAO_EXECUTADA"}


def _json(value: Any, default: Any = None) -> Any:
    try:
        return json.loads(value) if isinstance(value, str) else default
    except (TypeError, ValueError, json.JSONDecodeError):
        return default


def _rate(count: int, total: int) -> float | None:
    return count / total if total else None


def _distribution(values: Iterable[str], total: int) -> dict[str, dict[str, float | int]]:
    counts = Counter(values)
    return {key: {"count": count, "rate": _rate(count, total)} for key, count in sorted(counts.items())}


def _read_observations(db_path: str | Path, symbol: str | None) -> list[dict]:
    path = Path(db_path)
    if not path.exists():
        return []
    uri = f"file:{path.resolve().as_posix()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as conn:
        conn.row_factory = sqlite3.Row
        query = "SELECT * FROM decision_observations ORDER BY id"
        params: tuple = ()
        if symbol is not None:
            query = "SELECT * FROM decision_observations WHERE symbol=? ORDER BY id"
            params = (symbol,)
        return [dict(row) for row in conn.execute(query, params).fetchall()]


def _parse_row(row: dict) -> tuple[list[dict] | None, dict[str, int]]:
    parsed = _json(row.get("decisions_json"), None)
    quality = {"invalid_decisions_json": int(not isinstance(parsed, list)),
               "incomplete_decision_sets": 0, "duplicate_decision_ids": 0,
               "unknown_decision_ids": 0, "unknown_confidence_values": 0,
               "unknown_evidence_status": 0}
    if not isinstance(parsed, list):
        return None, quality
    ids = [item.get("id_decisao") for item in parsed if isinstance(item, dict)]
    quality["duplicate_decision_ids"] = int(len(ids) != len(set(ids)))
    quality["unknown_decision_ids"] = sum(item not in EXPECTED_DECISION_IDS for item in ids)
    quality["incomplete_decision_sets"] = int(
        len(parsed) != len(EXPECTED_DECISION_IDS)
        or set(ids) != set(EXPECTED_DECISION_IDS)
        or any(not isinstance(item, dict) for item in parsed)
    )
    for item in parsed:
        if isinstance(item, dict):
            quality["unknown_confidence_values"] += int(str(item.get("confianca", "")).upper() not in VALID_CONFIDENCES)
            quality["unknown_evidence_status"] += int(str(item.get("status_evidencias", "")).upper() not in VALID_EVIDENCE)
    return parsed, quality


def _model_metrics(rows: list[dict]) -> dict:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get("model_used") or "DESCONHECIDO")].append(row)
    result = {}
    for model, group in sorted(grouped.items()):
        total = len(group)
        fallback = sum(bool(row.get("fallback_used")) for row in group)
        repair = sum(bool(row.get("repair_used")) for row in group)
        result[model] = {"count": total, "sample_band": sample_band(total),
                         "fallback_count": fallback, "fallback_rate": _rate(fallback, total),
                         "repair_count": repair, "repair_rate": _rate(repair, total)}
    return result


def _state_stability(rows: list[dict]) -> dict:
    groups: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        if row.get("decision_state_hash"):
            groups[str(row["decision_state_hash"])].append(row)
    repeated = {digest: group for digest, group in groups.items() if len(group) >= 2}
    full = gate = 0
    agreement: dict[str, list[bool]] = defaultdict(list)
    confidence: dict[str, list[bool]] = defaultdict(list)
    for group in repeated.values():
        maps, confidence_maps = [], []
        for row in group:
            parsed, _ = _parse_row(row)
            maps.append({item.get("id_decisao"): item.get("decisao") for item in (parsed or []) if isinstance(item, dict)})
            confidence_maps.append({item.get("id_decisao"): item.get("confianca") for item in (parsed or []) if isinstance(item, dict)})
        full += int(len({tuple(mapping.get(key) for key in EXPECTED_DECISION_IDS) for mapping in maps}) == 1)
        gate += int(len({row.get("gate_status") for row in group}) == 1)
        for key in EXPECTED_DECISION_IDS:
            values = [mapping.get(key) for mapping in maps]
            agreement[key].append(len(set(values)) == 1)
            values = [mapping.get(key) for mapping in confidence_maps]
            confidence[key].append(len(set(values)) == 1)
    count = len(repeated)
    return {"repeated_state_groups": count,
            "repeated_observations": sum(len(group) for group in repeated.values()),
            "exact_full_decision_agreement_count": full,
            "exact_full_decision_agreement_rate": _rate(full, count),
            "agreement_by_decision": {key: {"count": sum(values), "rate": _rate(sum(values), len(values))} for key, values in sorted(agreement.items())},
            "gate_agreement_rate": _rate(gate, count),
            "confidence_agreement_by_decision": {key: _rate(sum(values), len(values)) for key, values in sorted(confidence.items())}}


def _cross_model(rows: list[dict]) -> dict:
    groups: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        if row.get("decision_state_hash"):
            groups[str(row["decision_state_hash"])].append(row)
    comparisons = []
    agreement: dict[str, list[bool]] = defaultdict(list)
    for digest, group in sorted(groups.items()):
        models = sorted({str(row.get("model_used") or "DESCONHECIDO") for row in group})
        if len(models) < 2:
            continue
        by_model = {}
        maps = []
        for row in group:
            parsed, _ = _parse_row(row)
            mapping = {item.get("id_decisao"): item.get("decisao") for item in (parsed or []) if isinstance(item, dict)}
            maps.append(mapping)
            by_model[str(row.get("model_used") or "DESCONHECIDO")] = mapping
        for key in EXPECTED_DECISION_IDS:
            values = [mapping.get(key) for mapping in maps]
            agreement[key].append(len(set(values)) == 1)
        comparisons.append({"state_hash": digest, "models": models, "decisions_by_model": by_model})
    return {"cross_model_state_groups": len(comparisons), "comparisons": comparisons,
            "per_decision_cross_model_agreement_rate": {key: _rate(sum(values), len(values)) for key, values in sorted(agreement.items())}}


def benchmark_report(db_path: str | Path, symbol: str | None = None, *, generated_at_utc: datetime | None = None) -> dict:
    """Gera relatório em SQLite ``mode=ro``; nunca executa migração ou escrita."""
    rows = _read_observations(db_path, symbol)
    usable, quality = [], Counter()
    for row in rows:
        _, row_quality = _parse_row(row)
        quality.update(row_quality)
        if not any(row_quality[key] for key in ("invalid_decisions_json", "incomplete_decision_sets", "duplicate_decision_ids", "unknown_decision_ids")):
            usable.append(row)
    quality.update({"missing_model_configured": sum(not row.get("model_configured") for row in rows),
                    "missing_model_used": sum(not row.get("model_used") for row in rows),
                    "unknown_gate_status": sum(str(row.get("gate_status") or "") not in VALID_GATES for row in rows),
                    "unknown_consensus_status": sum(str(row.get("consensus_status") or "") not in VALID_CONSENSUS for row in rows)})
    decisions_report = {}
    for decision_id in EXPECTED_DECISION_IDS:
        responses, confidences, evidence = [], [], []
        for row in usable:
            parsed, _ = _parse_row(row)
            item = next((item for item in (parsed or []) if item.get("id_decisao") == decision_id), None)
            if item:
                responses.append(str(item.get("decisao") or "DESCONHECIDO"))
                confidences.append(str(item.get("confianca") or "DESCONHECIDO"))
                evidence.append(str(item.get("status_evidencias") or "DESCONHECIDO"))
        decisions_report[decision_id] = {"responses": _distribution(responses, len(responses)),
                                         "confidence": _distribution(confidences, len(confidences)),
                                         "evidence_status": _distribution(evidence, len(evidence))}
    stability = _state_stability(usable)
    cross_model = _cross_model(usable)
    return {"benchmark_version": BENCHMARK_VERSION,
            "generated_at_utc": (generated_at_utc or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat(),
            "symbol": symbol, "total_observations": len(rows), "usable_observations": len(usable),
            "sample_band": sample_band(len(usable)), "models": _model_metrics(rows),
            "gate_distribution": _distribution((str(row.get("gate_status") or "DESCONHECIDO") for row in usable), len(usable)),
            "consensus_distribution": _distribution((str(row.get("consensus_status") or "DESCONHECIDO") for row in usable), len(usable)),
            "decisions": decisions_report, "stability": stability,
            "repeated_state_groups": stability["repeated_state_groups"],
            "repeated_observations": stability["repeated_observations"],
            "cross_model": cross_model,
            "cross_model_state_groups": cross_model["cross_model_state_groups"],
            "per_decision_cross_model_agreement_rate": cross_model["per_decision_cross_model_agreement_rate"],
            "latency_status": "INDISPONIVEL",
            "data_quality": dict(sorted(quality.items()))}


def compare(runs_a: list[dict], runs_b: list[dict]) -> dict:
    """Compatibilidade legada; não é usado pelo benchmark V2."""
    return {"versao_a": len(runs_a), "versao_b": len(runs_b), "diferenca": len(runs_b) - len(runs_a)}
