"""Calibração observacional V2; nunca altera decisões de produção.

O módulo somente vincula análises a MarketStates por igualdade canônica e
descreve o comportamento posterior dos Outcomes factuais disponíveis.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
import math
import sqlite3
from pathlib import Path
from statistics import median
from typing import Any

from po3.evaluation_engine import EVALUATION_VERSION, HORIZONS, sample_band
from po3.storage.market_repository import select_v2_evaluation_data
from po3.storage.migrations import CURRENT_SCHEMA_VERSION, migrate

CALIBRATION_VERSION = "1.0.0"
CONFIDENCES = ("ALTA", "MEDIA", "BAIXA")
BUY = "CONTEXTO_COMPRADOR"
SELL = "CONTEXTO_VENDEDOR"
ABSTENTIONS = {"AGUARDAR", "SEM_SETUP", "BLOQUEADO_POR_EVENTO", "INDETERMINADO"}
CANONICAL_KEYS = ("ativo", "timestamp", "preco_atual", "tecnico", "mercado_domestico",
                  "mercado_externo", "calendario", "noticias", "fontes", "qualidade_dados", "snapshot")
_METADATA_KEYS = {"captured_at_utc", "created_at", "observed_at_utc", "updated_at"}


def _normalize(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _normalize(item) for key, item in sorted(value.items()) if key not in _METADATA_KEYS}
    if isinstance(value, list):
        return [_normalize(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    return value


def canonical_state(value: dict) -> dict:
    """Seleciona apenas o conteúdo factual equivalente dos dois estados."""
    source = value.get("state") if isinstance(value.get("state"), dict) else value
    return _normalize({key: source.get(key) for key in CANONICAL_KEYS if key in source})


def state_hash(value: dict) -> str:
    payload = json.dumps(canonical_state(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _load_analysis(conn: sqlite3.Connection, analysis_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM analysis_runs WHERE id=?", (analysis_id,)).fetchone()


def _structured(row: sqlite3.Row) -> dict:
    try:
        context = json.loads(row["context_json"] or "{}")
        value = context.get("_structured", {})
        return value if isinstance(value, dict) else {}
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}


def _link_for(row: sqlite3.Row, states: list[dict]) -> dict:
    structured = _structured(row)
    candidate_state = structured.get("state") or {}
    digest = state_hash(candidate_state)
    candidates = [state for state in states if state.get("symbol") == row["symbol"] and state_hash(json.loads(state["state_json"])) == digest]
    link_status = "MATCHED" if len(candidates) == 1 else "AMBIGUOUS" if len(candidates) > 1 else "UNMATCHED"
    state_id = candidates[0]["id"] if link_status == "MATCHED" else None
    decisions = structured.get("decisoes", [])
    versions = structured.get("versoes", {})
    gate = structured.get("gate", {})
    consensus = structured.get("consenso", {})
    return {"analysis_run_id": row["id"], "market_state_id": state_id, "symbol": row["symbol"],
            "decision_state_hash": digest, "link_status": link_status,
            "decisions_json": json.dumps(decisions, ensure_ascii=False, default=str),
            "gate_status": gate.get("status") if isinstance(gate, dict) else None,
            "consensus_status": consensus.get("status") if isinstance(consensus, dict) else None,
            "model_configured": structured.get("modelo_configurado"),
            "model_used": structured.get("modelo_utilizado"),
            "fallback_used": int(bool(structured.get("fallback_utilizado"))),
            "repair_used": int(bool(structured.get("reparo_json_utilizado"))),
            "decision_engine_version": versions.get("decision_engine"),
            "prompt_version": versions.get("prompt"), "schema_version": CURRENT_SCHEMA_VERSION,
            "created_at": datetime.now(timezone.utc).isoformat()}


def _upsert_observation(conn: sqlite3.Connection, observation: dict) -> str:
    """Persiste o vínculo por analysis_run_id e retorna o status efetivamente salvo."""
    columns = list(observation)
    placeholders = ",".join("?" for _ in columns)
    assignments = ",".join(
        f"{column}=excluded.{column}" for column in columns if column != "analysis_run_id"
    )
    conn.execute(
        f"INSERT INTO decision_observations ({','.join(columns)}) VALUES ({placeholders}) "
        f"ON CONFLICT(analysis_run_id) DO UPDATE SET {assignments}",
        tuple(observation[column] for column in columns),
    )
    row = conn.execute(
        "SELECT link_status FROM decision_observations WHERE analysis_run_id=?",
        (observation["analysis_run_id"],),
    ).fetchone()
    return str(row[0])


def record_observation_for_analysis(analysis_id: int, db_path: str | Path) -> str:
    """Vincula uma análise uma única vez; falhas não são propagadas ao chat."""
    path = migrate(db_path) and Path(db_path)
    states, _ = select_v2_evaluation_data(path)
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        row = _load_analysis(conn, analysis_id)
        if row is None:
            return "UNMATCHED"
        return _upsert_observation(conn, _link_for(row, states))


def backfill_observations(db_path: str | Path) -> dict:
    path = migrate(db_path) and Path(db_path)
    states, _ = select_v2_evaluation_data(path)
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM analysis_runs ORDER BY id").fetchall()
        for row in rows:
            _upsert_observation(conn, _link_for(row, states))
    with sqlite3.connect(path) as conn:
        counts = {status: conn.execute("SELECT COUNT(*) FROM decision_observations WHERE link_status=?", (status,)).fetchone()[0]
                  for status in ("MATCHED", "UNMATCHED", "AMBIGUOUS")}
        counts["total_analysis_runs"] = len(rows)
    return counts


def _stats(values: list[float]) -> dict:
    values = [float(value) for value in values if value is not None]
    if not values:
        return {"median": None, "p25": None, "p75": None}
    ordered = sorted(values)
    def percentile(p):
        pos = (len(ordered) - 1) * p
        low = int(pos); high = min(low + 1, len(ordered) - 1)
        return ordered[low] + (ordered[high] - ordered[low]) * (pos - low)
    return {"median": median(ordered), "p25": percentile(.25), "p75": percentile(.75)}


def _directional_metrics(rows: list[dict]) -> dict:
    aligned = sum(row["directional_change"] > 0 for row in rows)
    opposed = sum(row["directional_change"] < 0 for row in rows)
    flat = sum(row["directional_change"] == 0 for row in rows)
    total = len(rows)
    changes = [row["directional_change"] for row in rows]
    return {"sample_size": total, "sample_band": sample_band(total), "aligned_count": aligned,
            "opposed_count": opposed, "flat_count": flat,
            "aligned_rate": aligned / total if total else None, "opposed_rate": opposed / total if total else None,
            "flat_rate": flat / total if total else None, **{f"{key}_directional_change_pct": value for key, value in _stats(changes).items()},
            "median_high_delta": _stats([row["high_delta"] for row in rows])['median'],
            "median_low_delta": _stats([row["low_delta"] for row in rows])['median']}


def _abstention_metrics(rows: list[dict]) -> dict:
    def values(field, absolute=False):
        result = []
        for row in rows:
            value = row.get(field)
            if value is not None:
                try:
                    result.append(abs(float(value)) if absolute else float(value))
                except (TypeError, ValueError):
                    pass
        return result
    return {"sample_size": len(rows), "sample_band": sample_band(len(rows)),
            "median_absolute_change": _stats(values("absolute_change"))["median"],
            "median_absolute_percentage_change": _stats(values("percentage_change", True))["median"],
            "median_high_delta": _stats(values("high_delta"))["median"],
            "median_low_delta": _stats(values("low_delta"))["median"]}


def calibration_report(db_path: str | Path, symbol: str | None = None, *, generated_at_utc: datetime | None = None) -> dict:
    """Retorna somente observações MATCHED e Outcomes DISPONIVEL."""
    path = Path(db_path)
    states, outcomes = select_v2_evaluation_data(path, symbol)
    observations = []
    if path.exists():
        uri = f"file:{path.resolve().as_posix()}?mode=ro"
        with sqlite3.connect(uri, uri=True) as conn:
            conn.row_factory = sqlite3.Row
            if symbol is None:
                query = "SELECT * FROM decision_observations WHERE link_status='MATCHED'"
                params = ()
            else:
                query = "SELECT * FROM decision_observations WHERE link_status='MATCHED' AND symbol=?"
                params = (symbol,)
            observations = [dict(row) for row in conn.execute(query, params).fetchall()]
    outcomes_by_key = {(row["market_state_id"], row["horizon_code"]): row for row in outcomes if row.get("status") == "DISPONIVEL"}
    result = {}
    abstentions = defaultdict(list)
    for horizon in HORIZONS:
        result[horizon] = {confidence: _directional_metrics([]) for confidence in CONFIDENCES}
        for observation in observations:
            decisions = json.loads(observation["decisions_json"] or "[]")
            operational = next((row for row in decisions if row.get("id_decisao") == "contexto_operacional"), None)
            if not operational:
                continue
            decision = str(operational.get("decisao", "INDETERMINADO")).upper()
            confidence = str(operational.get("confianca", "BAIXA")).upper()
            outcome = outcomes_by_key.get((observation["market_state_id"], horizon))
            if decision in ABSTENTIONS:
                if outcome:
                    abstentions[(horizon, decision)].append(outcome)
                continue
            if decision not in {BUY, SELL} or confidence not in CONFIDENCES or not outcome:
                continue
            try:
                change = float(outcome["percentage_change"])
            except (TypeError, ValueError):
                continue
            directional = change if decision == BUY else -change
            result[horizon][confidence].setdefault("_rows", []).append({"directional_change": directional,
                "high_delta": float(outcome["high_delta"]) if outcome["high_delta"] is not None else None,
                "low_delta": float(outcome["low_delta"]) if outcome["low_delta"] is not None else None})
        for confidence in CONFIDENCES:
            rows = result[horizon][confidence].pop("_rows", [])
            result[horizon][confidence] = _directional_metrics(rows)
    return {"calibration_version": CALIBRATION_VERSION,
            "evaluation_version": EVALUATION_VERSION,
            "generated_at_utc": (generated_at_utc or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat(),
            "symbol": symbol, "horizons": result,
            "abstentions": {f"{horizon}:{decision}": _abstention_metrics(rows) for (horizon, decision), rows in abstentions.items()},
            "observations": len(observations)}
