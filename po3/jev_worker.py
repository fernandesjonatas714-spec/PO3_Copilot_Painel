"""Worker isolado do Jev Shadow O5A; somente SQLite, nunca MT5 ou Outcomes."""
from __future__ import annotations

import argparse
import json
import os
import signal
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Event, Thread
from time import monotonic, perf_counter
from pathlib import Path
from typing import Any, Callable

from po3.decision_engine.validator import validate_market_state
from po3.jev_questions import JEV_QUESTION_VERSION, build_jev_questions
from po3.jev_service import JEV_MODEL, JevError, send_jev_decisions
from po3.run_recovery import ORPHAN_RUN_STALE_SECONDS, run_is_recoverable
from po3.shadow_runner import _hydrate_market_state
from po3.storage.market_repository import acquire_lease, heartbeat, release_lease
from po3.storage.migrations import migrate
from po3.v2_config import JEV_SHADOW_ENABLED

JEV_ENGINE_VERSION = "0.1.0-shadow"
SCHEMA_VERSION = "2.0.0"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect(path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def _critical(validation) -> bool:
    return bool(validation.bloqueado or "CALENDARIO" in validation.dados_ausentes)


def _normalize_answers(answers: Any) -> list[dict]:
    """Valida as seis respostas Jev sem fingir campos generativos."""
    if not isinstance(answers, list) or len(answers) != 6:
        raise JevError("Jev deve retornar exatamente seis respostas.", error_type="INVALID_ANSWER_SHAPE")
    expected = {"regime_macro", "contexto_domestico", "contexto_tecnico", "risco_evento",
                "conflito_contexto", "contexto_operacional"}
    out = []
    for raw in answers:
        if not isinstance(raw, dict):
            raise JevError("Resposta Jev inválida.", error_type="INVALID_ANSWER_SHAPE")
        decision_id = raw.get("decision_id", raw.get("id_decisao"))
        if decision_id not in expected:
            raise JevError("Identificador de decisão Jev inválido.", error_type="INVALID_DECISION_ID")
        value = raw.get("answer", raw.get("value", raw.get("raw_answer")))
        item = {"decision_id": decision_id, "answer_type": raw.get("answer_type"),
                "raw_answer": value, "confidence": raw.get("confidence"),
                "probabilities": raw.get("probabilities")}
        if decision_id == "risco_evento":
            try:
                score = float(raw.get("raw_score", value))
            except (TypeError, ValueError) as exc:
                raise JevError("Score Jev inválido.", error_type="INVALID_SCORE") from exc
            item["raw_score"] = score
            item["normalized_answer"] = max(0.0, min(10.0, score * 10.0 / 9.0))
        elif decision_id == "conflito_contexto":
            try: probability = float(raw.get("noul_probability", raw.get("probability", value)))
            except (TypeError, ValueError) as exc:
                raise JevError("Probabilidade NOUL inválida.", error_type="INVALID_NOUL") from exc
            item["noul_probability"] = probability
            item["normalized_answer"] = "SIM" if probability >= 0.50 else "NAO"
        else:
            item["normalized_answer"] = value
        out.append(item)
    if {item["decision_id"] for item in out} != expected:
        raise JevError("Jev não retornou as seis decisões distintas.", error_type="INVALID_DECISION_ID")
    return out


def _persist_result(path: str | Path, run_id: int, result: dict[str, Any], *, status: str,
                    external_call: bool, started: float, error_type: str | None = None,
                    error_message: str | None = None) -> None:
    finished = _now()
    with _connect(path) as conn:
        conn.execute("""UPDATE jev_shadow_runs SET model_used=?,provider=?,status=?,
          external_call_performed=?,answers_json=?,raw_response_json=?,input_tokens=?,
          output_tokens=?,cost_usd=?,duration_seconds=?,error_type=?,error_message=?,finished_at_utc=?
          WHERE id=?""", (result.get("model_used"), result.get("provider"), status,
          int(external_call), json.dumps(result.get("answers", []), ensure_ascii=False, default=str),
          json.dumps(result.get("raw_response"), ensure_ascii=False, default=str) if result.get("raw_response") is not None else None,
          result.get("input_tokens"), result.get("output_tokens"), float(result.get("cost_usd") or 0),
          perf_counter() - started, error_type, error_message, finished, run_id))


def run_jev_for_market_state(db_path: str | Path, market_state_id: int,
                             runner: Callable[[dict, dict], dict] = send_jev_decisions, *,
                             model_configured: str = JEV_MODEL,
                             jev_engine_version: str = JEV_ENGINE_VERSION,
                             question_version: str = JEV_QUESTION_VERSION,
                             worker_owner_id: str | None = None,
                             stale_timeout_seconds: int = ORPHAN_RUN_STALE_SECONDS) -> dict[str, Any]:
    if not JEV_SHADOW_ENABLED:
        return {"status": "DESABILITADO", "created": False, "external_call_performed": False}
    with _connect(db_path) as conn:
        row = conn.execute("SELECT * FROM market_states WHERE id=?", (market_state_id,)).fetchone()
    if row is None:
        return {"status": "ERRO", "created": False, "error_type": "MARKETSTATE_NAO_ENCONTRADO"}
    with _connect(db_path) as conn:
        existing = conn.execute("""SELECT * FROM jev_shadow_runs WHERE market_state_id=?
          AND model_configured=? AND jev_question_version=?""",
          (market_state_id, model_configured, question_version)).fetchone()
        recovered = False
        if existing is not None:
            if not run_is_recoverable(db_path, existing, status="RUNNING", worker_owner_id=worker_owner_id,
                                      stale_timeout_seconds=stale_timeout_seconds):
                return {"status": existing["status"], "created": False, "id": existing["id"], "runner_called": False}
            conn.execute("""UPDATE jev_shadow_runs SET status='RUNNING', error_type=NULL,
              error_message=NULL, worker_owner_id=?, recovered_after_restart=1 WHERE id=?""",
              (worker_owner_id, existing["id"]))
            run_id = int(existing["id"]); recovered = True
        else:
            cur = conn.execute("""INSERT INTO jev_shadow_runs
              (market_state_id,symbol,cutoff_at_utc,state_hash,jev_engine_version,jev_question_version,
               model_configured,status,created_at_utc,worker_owner_id)
              VALUES (?,?,?,?,?,?,?,?,?,?)""", (row["id"], row["symbol"], row["cutoff_at_utc"], row["state_hash"],
              jev_engine_version, question_version, model_configured, "RUNNING", _now(), worker_owner_id))
            run_id = int(cur.lastrowid)
        conn.commit()
    started = perf_counter()
    try:
        state = json.loads(row["state_json"])
        hydrated = _hydrate_market_state(state)
        validation = validate_market_state(hydrated)
        if _critical(validation):
            result = {"model_configured": model_configured, "answers": [], "cost_usd": 0}
            _persist_result(db_path, run_id, result, status="BLOQUEADO", external_call=False, started=started,
                            error_type="DADOS_CRITICOS_AUSENTES", error_message="DADOS_CRITICOS_AUSENTES")
            return {"status": "BLOQUEADO", "created": True, "recovered": recovered, "runner_called": False, "id": run_id}
        result = dict(runner(state, build_jev_questions()) or {})
        result["answers"] = _normalize_answers(result.get("answers"))
        _persist_result(db_path, run_id, result, status="OK", external_call=True, started=started)
        return {"status": "OK", "created": True, "recovered": recovered, "runner_called": True, "id": run_id,
                "result": result}
    except JevError as exc:
        _persist_result(db_path, run_id, {}, status="ERRO", external_call=True, started=started,
                        error_type=exc.error_type, error_message=str(exc))
        return {"status": "ERRO", "created": True, "recovered": recovered, "runner_called": True, "id": run_id,
                "error_type": exc.error_type, "error_message": str(exc)}
    except Exception as exc:
        _persist_result(db_path, run_id, {}, status="ERRO", external_call=True, started=started,
                        error_type=type(exc).__name__, error_message=str(exc))
        return {"status": "ERRO", "created": True, "recovered": recovered, "runner_called": True, "id": run_id,
                "error_type": type(exc).__name__, "error_message": str(exc)}


def process_pending_jev_states(db_path: str | Path, runner: Callable[[dict, dict], dict] = send_jev_decisions, *,
                               symbol: str | None = None, limit: int = 1, model_configured: str = JEV_MODEL,
                               worker_owner_id: str | None = None,
                               stale_timeout_seconds: int = ORPHAN_RUN_STALE_SECONDS) -> dict[str, Any]:
    if not JEV_SHADOW_ENABLED:
        return {"found": 0, "created": 0, "OK": 0, "ERRO": 0, "BLOQUEADO": 0, "DESABILITADO": 0}
    clauses = ["NOT EXISTS (SELECT 1 FROM jev_shadow_runs r WHERE r.market_state_id=s.id AND r.model_configured=? AND r.jev_question_version=? AND r.status <> 'RUNNING')"]
    args: list[Any] = [model_configured, JEV_QUESTION_VERSION]
    if symbol:
        clauses.append("s.symbol=?"); args.append(symbol)
    with _connect(db_path) as conn:
        rows = conn.execute(f"SELECT s.id FROM market_states s WHERE {' AND '.join(clauses)} ORDER BY s.cutoff_at_utc ASC,s.id ASC LIMIT ?", tuple(args + [max(0, int(limit))])).fetchall()
    summary = {"found": len(rows), "created": 0, "OK": 0, "ERRO": 0, "BLOQUEADO": 0}
    for row in rows:
        result = run_jev_for_market_state(db_path, row["id"], runner, model_configured=model_configured,
                                          worker_owner_id=worker_owner_id, stale_timeout_seconds=stale_timeout_seconds)
        if result.get("created"):
            summary["created"] += 1
        if result.get("status") in summary:
            summary[result["status"]] += 1
    return summary


@dataclass(frozen=True)
class JevWorkerConfig:
    symbol: str
    db_path: str
    poll_seconds: int = 10
    lease_ttl_seconds: int = 90
    heartbeat_interval_seconds: float = 25.0
    lease_name: str = "po3-jev"


def _heartbeat(config: JevWorkerConfig, owner: str, stop: Event, hb_stop: Event, lost: Event) -> None:
    while not hb_stop.wait(min(config.heartbeat_interval_seconds, config.lease_ttl_seconds / 3)):
        if not heartbeat(config.lease_name, config.symbol, owner, config.db_path, config.lease_ttl_seconds):
            lost.set(); stop.set(); return


def run_jev_worker(config: JevWorkerConfig, stop_event: Event | None = None, max_cycles: int | None = None) -> None:
    migrate(config.db_path)
    owner = acquire_lease(config.lease_name, config.symbol, config.db_path, ttl_seconds=config.lease_ttl_seconds)
    if not owner:
        raise RuntimeError("Outro Jev worker possui o lease")
    stop_event = stop_event or Event(); hb_stop = Event(); lost = Event()
    thread = Thread(target=_heartbeat, args=(config, owner, stop_event, hb_stop, lost), daemon=True)
    thread.start(); stop_file = os.getenv("PO3_JEV_WORKER_STOP_FILE"); cycles = 0
    try:
        while not stop_event.is_set() and (max_cycles is None or cycles < max_cycles):
            if stop_file and os.path.exists(stop_file): stop_event.set(); break
            if lost.is_set(): raise RuntimeError("Lease Jev perdido")
            process_pending_jev_states(config.db_path, symbol=config.symbol, limit=1, worker_owner_id=owner)
            cycles += 1
            if max_cycles is None: stop_event.wait(max(1, config.poll_seconds))
    finally:
        hb_stop.set(); thread.join(timeout=max(1, int(config.heartbeat_interval_seconds) + 1))
        release_lease(config.lease_name, config.symbol, owner, config.db_path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Worker Jev Shadow O5A")
    parser.add_argument("--symbol", default=os.getenv("MT5_SYMBOL", "WINV26")); parser.add_argument("--db", default="data/po3_learning.sqlite")
    parser.add_argument("--poll-seconds", type=int, default=10); args = parser.parse_args()
    stop = Event()
    def request_stop(_signum, _frame): stop.set()
    signal.signal(signal.SIGINT, request_stop); signal.signal(signal.SIGTERM, request_stop)
    if hasattr(signal, "SIGBREAK"): signal.signal(signal.SIGBREAK, request_stop)
    run_jev_worker(JevWorkerConfig(args.symbol, args.db, args.poll_seconds), stop)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
