"""Execução automática oficial sobre MarketStates congelados.

Este módulo é deliberadamente separado do Shadow Mode: o Shadow continua
observacional e esta execução é o resultado oficial exibido pelo painel. Ambos
recebem exatamente o mesmo estado causal persistido e nenhum deles conhece
Outcomes ou abre uma nova sessão MT5.
"""
from __future__ import annotations

import json
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from po3.ai_service import configured_model_name, send_message_detailed
from po3.decision_engine.engine import DecisionEngine
from po3.decision_engine.narrative import generate_narrative
from po3.decision_engine.schemas import DECISION_ENGINE_VERSION, PROMPT_VERSION, SCHEMA_VERSION
from po3.shadow_runner import _hydrate_market_state
from po3.storage.migrations import migrate


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _confidence(result: dict[str, Any]) -> str | None:
    order = {"BAIXA": 0, "MEDIA": 1, "ALTA": 2}
    values = [str(item.get("confianca", "")).upper() for item in result.get("decisoes", [])]
    values = [value for value in values if value in order]
    return min(values, key=lambda value: order[value]) if values else None


def _operational_context(result: dict[str, Any]) -> str | None:
    for item in result.get("decisoes", []):
        if item.get("id_decisao") == "contexto_operacional":
            return item.get("decisao")
    return None


def _narrative_call(message: str, **kwargs) -> dict[str, Any]:
    return send_message_detailed(
        message,
        system_instruction=(
            "Responda somente com os três blocos narrativos solicitados, sempre em "
            "português do Brasil. Não invente dados, não transforme contexto em ordem."
        ),
    )


def _runner(state: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
    model = configured_model_name()

    def decision_call(message: str, **kwargs) -> dict[str, Any]:
        return send_message_detailed(
            message,
            **kwargs,
            system_instruction=(
                "Responda exclusivamente em JSON válido, em português do Brasil, "
                "conforme o schema solicitado. Não invente dados."
            ),
        )

    hydrated = _hydrate_market_state(state)
    structured = DecisionEngine(decision_call, model).run_market_state(hydrated)
    result = structured.to_dict()
    # Dados críticos ausentes são um bloqueio factual, não uma análise oficial
    # válida. Portanto não há narrativa nem chamada adicional de IA.
    if structured.error:
        return result, None
    try:
        narrative_model_used = None
        narrative_fallback_used = False
        narrative = generate_narrative(
            _narrative_call,
            structured.state,
            structured.decisions,
            structured.gate,
            structured.consensus,
            structured.model_used,
        )
        structured.narrative = narrative.get("content")
        narrative_model_used = narrative.get("model_used")
        narrative_fallback_used = bool(narrative.get("fallback_used"))
        structured.narrative_model_used = narrative_model_used
        structured.narrative_fallback_used = narrative_fallback_used
    except Exception as exc:
        structured.narrative = None
        structured.narrative_model_used = None
        structured.narrative_fallback_used = False
        result = structured.to_dict()
        result["_narrative_error"] = type(exc).__name__
        return result, None
    return structured.to_dict(), structured.narrative


def run_auto_decision_for_market_state(
    db_path: str | Path,
    market_state_id: int,
    *,
    model_configured: str | None = None,
    decision_engine_version: str = DECISION_ENGINE_VERSION,
    prompt_version: str = PROMPT_VERSION,
) -> dict[str, Any]:
    """Executa no máximo uma análise oficial por estado/configuração."""
    path = Path(db_path)
    migrate(path)
    model = model_configured or configured_model_name()
    started = time.perf_counter()
    conn = sqlite3.connect(path)
    try:
      with conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM market_states WHERE id=?", (market_state_id,)).fetchone()
        if row is None:
            return {"status": "ERRO", "error_type": "MARKETSTATE_NAO_ENCONTRADO", "created": False}
        claim = conn.execute(
            """INSERT OR IGNORE INTO official_decision_runs
               (market_state_id,symbol,cutoff_at_utc,state_hash,decision_engine_version,
                prompt_version,schema_version,model_configured,decisions_json,status,created_at_utc)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (row["id"], row["symbol"], row["cutoff_at_utc"], row["state_hash"],
             decision_engine_version, prompt_version, SCHEMA_VERSION, model, "{}", "PROCESSANDO", _utc_now()),
        )
        if claim.rowcount == 0:
            existing = conn.execute(
                """SELECT * FROM official_decision_runs WHERE market_state_id=?
                   AND decision_engine_version=? AND prompt_version=? AND model_configured=?""",
                (market_state_id, decision_engine_version, prompt_version, model),
            ).fetchone()
            return {"status": existing["status"] if existing else "PROCESSANDO", "created": False,
                    "id": int(existing["id"]) if existing else None}
        run_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
    finally:
        conn.close()

    try:
        state = json.loads(row["state_json"])
        result, narrative = _runner(state)
        error = result.get("erro")
        narrative_error = result.pop("_narrative_error", None)
        decision_status = "BLOQUEADO" if error == "DADOS_CRITICOS_AUSENTES" else ("OK" if len(result.get("decisoes", [])) == 6 and not error else "ERRO")
        narrative_status = "ERRO" if narrative_error else ("OK" if narrative else "NAO_EXECUTADA")
        status = decision_status
        gate = result.get("gate") or {}
        consensus = result.get("consenso") or {}
        decisions_json = json.dumps(result, ensure_ascii=False, sort_keys=True, default=str)
        conn = sqlite3.connect(path)
        try:
            conn.execute(
                """UPDATE official_decision_runs SET model_used=?,fallback_used=?,repair_used=?,
                   decision_model_used=?,decision_model_attempts_json=?,decision_fallback_used=?,decision_repair_used=?,
                   narrative_model_used=?,narrative_fallback_used=?,
                   gate_status=?,consensus_status=?,confidence=?,context_operational=?,
                   model_attempts_json=?,decision_status=?,narrative_status=?,
                   decisions_json=?,narrative=?,status=?,error_type=?,error_message=?,duration_seconds=?
                   WHERE id=?""",
                (result.get("modelo_utilizado"), int(bool(result.get("fallback_utilizado"))),
                 int(bool(result.get("reparo_json_utilizado"))), result.get("decision_model_used") or result.get("modelo_utilizado"),
                 json.dumps(result.get("decision_model_attempts", result.get("model_attempts", []))),
                 int(bool(result.get("decision_fallback_used", result.get("fallback_utilizado")))),
                 int(bool(result.get("decision_repair_used", result.get("reparo_json_utilizado")))),
                 result.get("narrative_model_used"), int(bool(result.get("narrative_fallback_used"))), gate.get("status"),
                 consensus.get("status"), _confidence(result), _operational_context(result),
                 json.dumps(result.get("model_attempts", [])), decision_status, narrative_status,
                 decisions_json, narrative, status, "DecisionEngineError" if error else narrative_error,
                 str(error) if error else narrative_error, time.perf_counter() - started, run_id),
            )
            conn.commit()
        finally:
            conn.close()
        return {"status": status, "created": True, "id": run_id, "result": result, "narrative": narrative}
    except Exception as exc:
        conn = sqlite3.connect(path)
        try:
            conn.execute(
                """UPDATE official_decision_runs SET status='ERRO',error_type=?,error_message=?,
                   duration_seconds=? WHERE id=?""",
                (type(exc).__name__, str(exc), time.perf_counter() - started, run_id),
            )
            conn.commit()
        finally:
            conn.close()
        return {"status": "ERRO", "created": True, "id": run_id,
                "error_type": type(exc).__name__, "error_message": str(exc)}


def process_pending_auto_decisions(
    db_path: str | Path,
    *,
    model_configured: str | None = None,
    symbol: str | None = None,
    limit: int = 1,
) -> dict[str, Any]:
    """Processa somente estados ainda não analisados pela configuração atual."""
    path = Path(db_path)
    migrate(path)
    model = model_configured or configured_model_name()
    conn = sqlite3.connect(path)
    try:
        conn.row_factory = sqlite3.Row
        where = ["o.id IS NULL"]
        args: list[Any] = [DECISION_ENGINE_VERSION, PROMPT_VERSION, model]
        if symbol:
            where.append("s.symbol=?")
            args.append(symbol)
        args.append(max(1, int(limit)))
        rows = conn.execute(
            f"""SELECT s.id FROM market_states s
                LEFT JOIN official_decision_runs o ON o.market_state_id=s.id
                  AND o.decision_engine_version=? AND o.prompt_version=? AND o.model_configured=?
                WHERE {' AND '.join(where)}
                ORDER BY s.cutoff_at_utc DESC, s.id DESC LIMIT ?""",
            tuple(args),
        ).fetchall()
    finally:
        conn.close()
    results = [run_auto_decision_for_market_state(path, int(row["id"]), model_configured=model) for row in rows]
    return {"selected": len(rows), "created": sum(1 for item in results if item.get("created")), "results": results}


def latest_official_analysis(db_path: str | Path, symbol: str) -> dict[str, Any] | None:
    path = Path(db_path)
    if not path.exists():
        return None
    conn = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)
    try:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM official_decision_runs WHERE symbol=? ORDER BY cutoff_at_utc DESC,id DESC LIMIT 1", (symbol,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()
