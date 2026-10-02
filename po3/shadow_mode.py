"""Shadow Mode observacional V2, separado do fluxo operacional.

Por padrão permanece desativado. Quando habilitado explicitamente, executa um
runner injetado sobre MarketStates congelados e persiste somente em shadow_runs.
Não chama OpenRouter, não lê Outcomes e não executa ordens.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from time import perf_counter
from typing import Any, Callable

from po3.calibration import state_hash
from po3.evaluation_engine import sample_band
from po3.replay_engine import sanitize_replay_state
from po3.decision_engine.schemas import DECISION_ENGINE_VERSION, PROMPT_VERSION
from po3.v2_config import SHADOW_MODE_ENABLED
from po3.run_recovery import ORPHAN_RUN_STALE_SECONDS, run_is_recoverable
from po3.ai_analysis_window import ensure_ai_analysis_baseline, is_ai_analysis_window_open

SHADOW_MODE_VERSION = "1.0.0"
SCHEMA_VERSION = "2.0.0"


def _connect_ro(path: str | Path) -> sqlite3.Connection:
    uri = f"file:{Path(path).resolve().as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _structured(result: Any) -> dict:
    value = result.get("result") if isinstance(result, dict) and isinstance(result.get("result"), dict) else result
    return value if isinstance(value, dict) else {}


def _field(result: dict, key: str) -> Any:
    nested = result.get(key)
    if isinstance(nested, dict):
        return nested.get("status")
    return result.get(f"{key}_status")


def _run_values(result: Any) -> tuple[str, str | None, int, int, str | None, str | None, str]:
    value = _structured(result)
    decisions = value.get("decisoes", [])
    return (json.dumps(decisions, ensure_ascii=False, default=str), value.get("modelo_utilizado") or value.get("model_used"),
            int(bool(value.get("fallback_utilizado", value.get("fallback_used", False)))),
            int(bool(value.get("reparo_json_utilizado", value.get("repair_used", False)))),
            _field(value, "gate"), _field(value, "consenso"), json.dumps(value, ensure_ascii=False, default=str))


def _state_row(db_path: str | Path, market_state_id: int) -> dict | None:
    with _connect_ro(db_path) as conn:
        row = conn.execute("SELECT id,symbol,cutoff_at_utc,state_json,state_hash,decision_engine_version,prompt_version,schema_version FROM market_states WHERE id=?", (market_state_id,)).fetchone()
        if row is None:
            return None
        state = json.loads(row["state_json"])
        if not isinstance(state, dict):
            raise ValueError("state_json do MarketState não é um objeto")
        return {"id": row["id"], "symbol": row["symbol"], "cutoff_at_utc": row["cutoff_at_utc"],
                "state": state, "state_hash": state_hash(state),
                "decision_engine_version": row["decision_engine_version"], "prompt_version": row["prompt_version"],
                "schema_version": row["schema_version"]}


def run_shadow_for_market_state(db_path: str | Path, market_state_id: int, decision_runner: Callable[[dict], Any], *,
                                model_configured: str = "UNSPECIFIED", shadow_mode_version: str = SHADOW_MODE_VERSION,
                                decision_engine_version: str | None = None, prompt_version: str | None = None,
                                worker_owner_id: str | None = None,
                                stale_timeout_seconds: int = ORPHAN_RUN_STALE_SECONDS) -> dict:
    """Executa uma vez por configuração; flag desligada não chama runner nem grava."""
    if not SHADOW_MODE_ENABLED:
        return {"status": "DESABILITADO", "created": False, "runner_called": False}
    state = _state_row(db_path, market_state_id)
    if state is None:
        return {"status": "ERRO", "created": False, "error_type": "MarketStateNaoEncontrado"}
    engine_version = decision_engine_version or DECISION_ENGINE_VERSION
    prompt = prompt_version or PROMPT_VERSION
    now = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("BEGIN IMMEDIATE")
        existing = conn.execute("SELECT * FROM shadow_runs WHERE market_state_id=? AND shadow_mode_version=? AND decision_engine_version=? AND prompt_version=? AND model_configured=?",
                                (market_state_id, shadow_mode_version, engine_version, prompt, model_configured)).fetchone()
        if existing is not None:
            if not run_is_recoverable(db_path, existing, status="RUNNING",
                                      worker_owner_id=worker_owner_id,
                                      stale_timeout_seconds=stale_timeout_seconds):
                conn.commit()
                return {"status": existing["status"], "created": False, "runner_called": False,
                        "shadow_run_id": existing["id"], "reason": "IDEMPOTENTE"}
            conn.execute("""UPDATE shadow_runs SET status='RUNNING', error_type=NULL,
                           error_message=NULL, worker_owner_id=?, recovered_after_restart=1
                           WHERE id=?""", (worker_owner_id, existing["id"]))
            run_id = int(existing["id"])
            recovered = True
        else:
            cursor = conn.execute("""INSERT INTO shadow_runs
            (market_state_id,symbol,cutoff_at_utc,state_hash,shadow_mode_version,decision_engine_version,prompt_version,schema_version,model_configured,decisions_json,status,created_at_utc)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (state["id"], state["symbol"], state["cutoff_at_utc"], state["state_hash"], shadow_mode_version, engine_version, prompt,
             state["schema_version"] or SCHEMA_VERSION, model_configured, "[]", "RUNNING", now))
            run_id = cursor.lastrowid
            conn.execute("UPDATE shadow_runs SET worker_owner_id=? WHERE id=?", (worker_owner_id, run_id))
            recovered = False
        conn.commit()
    payload = sanitize_replay_state(state["state"])
    started = perf_counter()
    try:
        result = decision_runner(payload)
        decisions_json, model_used, fallback, repair, gate, consensus, _ = _run_values(result)
        status, error_type, error_message = "OK", None, None
    except Exception as exc:
        decisions_json, model_used, fallback, repair, gate, consensus = "[]", None, 0, 0, None, None
        status, error_type, error_message = "ERRO", type(exc).__name__, str(exc)
    duration = perf_counter() - started
    with sqlite3.connect(db_path) as conn:
        conn.execute("UPDATE shadow_runs SET model_used=?,fallback_used=?,repair_used=?,gate_status=?,consensus_status=?,decisions_json=?,status=?,error_type=?,error_message=?,duration_seconds=? WHERE id=?",
                     (model_used, fallback, repair, gate, consensus, decisions_json, status, error_type, error_message, duration, run_id))
    return {"status": status, "created": True, "recovered": recovered, "runner_called": True, "shadow_run_id": run_id,
            "market_state_id": market_state_id, "model_used": model_used}


def process_pending_shadow_states(db_path: str | Path, decision_runner: Callable[[dict], Any], *, limit: int = 10,
                                  model_configured: str = "UNSPECIFIED", shadow_mode_version: str = SHADOW_MODE_VERSION,
                                  decision_engine_version: str = DECISION_ENGINE_VERSION,
                                  prompt_version: str = PROMPT_VERSION, symbol: str | None = None,
                                  worker_owner_id: str | None = None,
                                  stale_timeout_seconds: int = ORPHAN_RUN_STALE_SECONDS,
                                  enforce_window: bool = False,
                                  now: datetime | None = None) -> dict:
    if not SHADOW_MODE_ENABLED:
        return {"found": 0, "created": 0, "ignored": 0, "OK": 0, "ERRO": 0, "DESABILITADO": 0}
    if enforce_window and not is_ai_analysis_window_open(now):
        return {"found": 0, "created": 0, "ignored": 0, "OK": 0, "ERRO": 0, "status": "FORA_JANELA_IA"}
    baseline = ensure_ai_analysis_baseline(db_path, symbol or "WINV26", now=now) if enforce_window else None
    with _connect_ro(db_path) as conn:
        clauses = ["NOT EXISTS (SELECT 1 FROM shadow_runs AS r WHERE r.market_state_id=s.id AND r.shadow_mode_version=? AND r.decision_engine_version=? AND r.prompt_version=? AND r.model_configured=? AND r.status <> 'RUNNING')"]
        params: list[Any] = [shadow_mode_version, decision_engine_version, prompt_version, model_configured]
        if symbol is not None:
            clauses.append("s.symbol=?")
            params.append(symbol)
        if enforce_window and baseline:
            _, baseline_id, baseline_cutoff = baseline
            if baseline_cutoff is None:
                clauses.append("s.id > ?")
                params.append(baseline_id)
            else:
                clauses.append("(s.cutoff_at_utc > ? OR (s.cutoff_at_utc = ? AND s.id > ?))")
                params.extend([baseline_cutoff, baseline_cutoff, baseline_id])
        rows = conn.execute(f"""SELECT s.id
            FROM market_states AS s
            WHERE {' AND '.join(clauses)}
            ORDER BY s.cutoff_at_utc ASC,s.id ASC
            LIMIT ?""", tuple(params + [max(0, int(limit))])).fetchall()
    summary = {"found": len(rows), "created": 0, "ignored": 0, "OK": 0, "ERRO": 0}
    eligible = []
    for row in rows:
        with _connect_ro(db_path) as conn:
            existing = conn.execute(
                """SELECT * FROM shadow_runs WHERE market_state_id=? AND shadow_mode_version=?
                   AND decision_engine_version=? AND prompt_version=? AND model_configured=?""",
                (row["id"], shadow_mode_version, decision_engine_version, prompt_version, model_configured),
            ).fetchone()
        if existing is None or run_is_recoverable(db_path, existing, status="RUNNING",
                                                   worker_owner_id=worker_owner_id,
                                                   stale_timeout_seconds=stale_timeout_seconds):
            eligible.append(row)
        if len(eligible) >= max(0, int(limit)):
            break
    for row in eligible:
        result = run_shadow_for_market_state(db_path, row["id"], decision_runner, model_configured=model_configured,
                                              shadow_mode_version=shadow_mode_version,
                                              decision_engine_version=decision_engine_version, prompt_version=prompt_version,
                                              worker_owner_id=worker_owner_id,
                                              stale_timeout_seconds=stale_timeout_seconds)
        if result.get("created"):
            summary["created"] += 1
        else:
            summary["ignored"] += 1
        if result.get("status") in ("OK", "ERRO"):
            summary[result["status"]] += 1
    return summary


def shadow_report(db_path: str | Path, symbol: str | None = None) -> dict:
    """Relatório somente leitura, sem ranking, Outcomes ou taxa de acerto."""
    with _connect_ro(db_path) as conn:
        if symbol is None:
            rows = conn.execute("SELECT * FROM shadow_runs ORDER BY cutoff_at_utc,id").fetchall()
        else:
            rows = conn.execute("SELECT * FROM shadow_runs WHERE symbol=? ORDER BY cutoff_at_utc,id", (symbol,)).fetchall()
    rows = [dict(row) for row in rows]
    total = len(rows)
    models = defaultdict(lambda: {"count": 0, "fallback_count": 0, "repair_count": 0})
    for row in rows:
        model = row.get("model_used") or row.get("model_configured") or "DESCONHECIDO"
        models[model]["count"] += 1
        models[model]["fallback_count"] += int(bool(row.get("fallback_used")))
        models[model]["repair_count"] += int(bool(row.get("repair_used")))
    for values in models.values():
        values["fallback_rate"] = values["fallback_count"] / values["count"] if values["count"] else None
        values["repair_rate"] = values["repair_count"] / values["count"] if values["count"] else None
        values["sample_band"] = sample_band(values["count"])
    return {"shadow_mode_version": SHADOW_MODE_VERSION, "symbol": symbol, "total_runs": total,
            "OK": sum(row.get("status") == "OK" for row in rows), "ERRO": sum(row.get("status") == "ERRO" for row in rows),
            "sample_band": sample_band(total), "models": dict(models),
            "gate_distribution": _counts(rows, "gate_status"), "consensus_distribution": _counts(rows, "consensus_status"),
            "first_cutoff": min((row["cutoff_at_utc"] for row in rows), default=None),
            "last_cutoff": max((row["cutoff_at_utc"] for row in rows), default=None)}


def _counts(rows: list[dict], field: str) -> dict[str, int]:
    counts = defaultdict(int)
    for row in rows:
        counts[str(row.get(field) or "OUTROS_DESCONHECIDOS")] += 1
    return dict(sorted(counts.items()))
