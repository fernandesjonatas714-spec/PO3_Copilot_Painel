"""Comparação observacional Jev x decisão oficial, sem escrita ou Outcomes."""
from __future__ import annotations
import json
import sqlite3
from pathlib import Path


def compare_market_state(db_path: str | Path, market_state_id: int) -> dict:
    uri = f"file:{Path(db_path).resolve().as_posix()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as conn:
        conn.row_factory = sqlite3.Row
        official = conn.execute("SELECT * FROM official_decision_runs WHERE market_state_id=? ORDER BY id DESC LIMIT 1", (market_state_id,)).fetchone()
        jev = conn.execute("SELECT * FROM jev_shadow_runs WHERE market_state_id=? ORDER BY id DESC LIMIT 1", (market_state_id,)).fetchone()
    if official is None or jev is None:
        return {"status": "INDISPONIVEL", "market_state_id": market_state_id}
    try: official_items = {x.get("id_decisao"): x for x in json.loads(official["decisions_json"]).get("decisoes", [])}
    except Exception: official_items = {}
    try: jev_items = {x.get("decision_id", x.get("id_decisao")): x for x in json.loads(jev["answers_json"])}
    except Exception: jev_items = {}
    result = {}
    exact = 0
    for key in ("regime_macro", "contexto_domestico", "contexto_tecnico", "conflito_contexto", "contexto_operacional"):
        left = official_items.get(key, {}).get("decisao"); right = jev_items.get(key, {}).get("normalized_answer", jev_items.get(key, {}).get("answer"))
        result[f"agreement_{key}"] = left == right if left is not None and right is not None else None
        exact += int(result[f"agreement_{key}"] is True)
    official_score = official_items.get("risco_evento", {}).get("decisao"); jev_score = jev_items.get("risco_evento", {}).get("normalized_answer")
    try: result["risk_event_absolute_difference"] = abs(float(official_score) - float(jev_score))
    except (TypeError, ValueError): result["risk_event_absolute_difference"] = None
    if result["risk_event_absolute_difference"] == 0: exact += 1
    result.update({"market_state_id": market_state_id, "status": "OK", "exact_agreement_count": exact,
                   "jev_status": jev["status"], "official_status": official["status"]})
    return result


def jev_report(db_path: str | Path, symbol: str | None = None) -> dict:
    uri = f"file:{Path(db_path).resolve().as_posix()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as conn:
        where = " WHERE symbol=?" if symbol else ""; args = (symbol,) if symbol else ()
        rows = conn.execute(f"SELECT status,cost_usd,duration_seconds FROM jev_shadow_runs{where}", args).fetchall()
    costs = [float(row[1] or 0) for row in rows]
    return {"symbol": symbol, "jev_calls": len(rows), "successful_calls": sum(row[0] == "OK" for row in rows),
            "blocked_before_call": sum(row[0] == "BLOQUEADO" for row in rows), "errors": sum(row[0] == "ERRO" for row in rows),
            "total_cost_usd": sum(costs), "average_cost_usd": sum(costs) / len(costs) if costs else None,
            "latencies": [row[2] for row in rows if row[2] is not None]}
