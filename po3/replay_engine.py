"""Replay causal, determinístico e offline do Decision Engine V2.

O módulo recebe exclusivamente MarketStates congelados. Não consulta Outcomes,
não chama OpenRouter e nunca grava resultados no SQLite.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from time import perf_counter
from typing import Any, Callable, Iterable

from po3.calibration import state_hash

REPLAY_VERSION = "1.0.0"
_FUTURE_KEYS = {
    "outcomes", "observed_outcomes", "future_bars", "future_price", "future_high",
    "future_low", "percentage_change", "absolute_change", "high_delta", "low_delta",
    "target_at_utc", "target_at", "observed_at_utc", "observed_at",
}


def _sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _sanitize(item) for key, item in value.items()
            if str(key).lower() not in _FUTURE_KEYS
        }
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_sanitize(item) for item in value)
    return deepcopy(value)


def sanitize_replay_state(state: dict) -> dict:
    """Remove recursivamente campos que só podem ser conhecidos no futuro."""
    return _sanitize(state)


def _utc(value: datetime | str | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    return str(value)


def _sort_key(state: dict) -> tuple[str, int]:
    return (str(state.get("cutoff_at_utc") or state.get("timestamp") or ""), int(state.get("id") or 0))


def replay_market_states(
    states: Iterable[dict],
    decision_runner: Callable[[dict], Any],
    *,
    run_at_utc: datetime | None = None,
    runner_version: str | None = None,
) -> list[dict]:
    """Reexecuta estados em ordem causal, isolando falhas por estado."""
    run_at = (run_at_utc or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()
    version = runner_version or "UNSPECIFIED"
    results = []
    for original in sorted((deepcopy(state) for state in states), key=_sort_key):
        payload = sanitize_replay_state(original)
        started = perf_counter()
        base = {
            "replay_version": REPLAY_VERSION,
            "market_state_id": original.get("id"),
            "symbol": original.get("symbol") or original.get("ativo"),
            "cutoff_at_utc": original.get("cutoff_at_utc") or original.get("timestamp"),
            "state_hash": state_hash(original),
            "run_at_utc": run_at,
            "runner_version": version,
        }
        try:
            result = decision_runner(payload)
            base.update({"status": "OK", "result": result,
                         "duration_seconds": perf_counter() - started})
        except Exception as exc:  # runner failure is factual replay output
            base.update({"status": "ERRO", "result": None,
                         "error_type": type(exc).__name__, "error_message": str(exc),
                         "duration_seconds": perf_counter() - started})
        results.append(base)
    return results


def _load_states(db_path: str | Path, symbol: str | None, start_cutoff: str | None,
                 end_cutoff: str | None, limit: int | None) -> list[dict]:
    path = Path(db_path)
    uri = f"file:{path.resolve().as_posix()}?mode=ro"
    where, params = [], []
    if symbol is not None:
        where.append("symbol=?"); params.append(symbol)
    if start_cutoff is not None:
        where.append("cutoff_at_utc>=?"); params.append(_utc(start_cutoff))
    if end_cutoff is not None:
        where.append("cutoff_at_utc<=?"); params.append(_utc(end_cutoff))
    query = "SELECT id,symbol,cutoff_at_utc,state_json FROM market_states"
    if where:
        query += " WHERE " + " AND ".join(where)
    query += " ORDER BY cutoff_at_utc ASC, id ASC"
    if limit is not None:
        query += " LIMIT ?"; params.append(int(limit))
    with sqlite3.connect(uri, uri=True) as conn:
        conn.row_factory = sqlite3.Row
        states = []
        for row in conn.execute(query, tuple(params)).fetchall():
            state = json.loads(row["state_json"])
            if not isinstance(state, dict):
                raise ValueError(f"MarketState {row['id']} não contém objeto JSON")
            state.setdefault("id", row["id"])
            state.setdefault("symbol", row["symbol"])
            state.setdefault("cutoff_at_utc", row["cutoff_at_utc"])
            states.append(state)
        return states


def replay_from_db(
    db_path: str | Path,
    decision_runner: Callable[[dict], Any],
    symbol: str | None = None,
    start_cutoff: str | None = None,
    end_cutoff: str | None = None,
    limit: int | None = None,
    *,
    run_at_utc: datetime | None = None,
    runner_version: str | None = None,
) -> list[dict]:
    """Lê somente MarketStates congelados do SQLite e retorna resultados em memória."""
    states = _load_states(db_path, symbol, start_cutoff, end_cutoff, limit)
    return replay_market_states(states, decision_runner, run_at_utc=run_at_utc, runner_version=runner_version)


def _result_decisions(result: Any) -> dict[str, Any]:
    value = result
    if isinstance(value, dict) and isinstance(value.get("result"), dict):
        value = value["result"]
    if isinstance(value, dict) and isinstance(value.get("decisoes"), list):
        return {item.get("id_decisao"): item.get("decisao") for item in value["decisoes"] if isinstance(item, dict)}
    return {}


def compare_replay_with_observation(db_path: str | Path, replay_results: Iterable[dict]) -> list[dict]:
    """Compara Replay somente com observação MATCHED do mesmo MarketState."""
    results = list(replay_results)
    ids = [row.get("market_state_id") for row in results if row.get("market_state_id") is not None]
    observations = {}
    if ids:
        uri = f"file:{Path(db_path).resolve().as_posix()}?mode=ro"
        with sqlite3.connect(uri, uri=True) as conn:
            conn.row_factory = sqlite3.Row
            placeholders = ",".join("?" for _ in ids)
            for row in conn.execute(
                f"SELECT market_state_id,decisions_json,gate_status,consensus_status,link_status FROM decision_observations WHERE market_state_id IN ({placeholders})",
                tuple(ids),
            ).fetchall():
                if row["link_status"] == "MATCHED":
                    observations[row["market_state_id"]] = dict(row)
    comparisons = []
    for replay in results:
        original = observations.get(replay.get("market_state_id"))
        if not original:
            comparisons.append({"market_state_id": replay.get("market_state_id"), "status": "INDISPONIVEL"})
            continue
        original_items = _json_list(original.get("decisions_json"))
        original_decisions = {item.get("id_decisao"): item.get("decisao") for item in original_items if isinstance(item, dict)}
        replay_decisions = _result_decisions(replay.get("result"))
        per_decision = {}
        for key in sorted(set(original_decisions) | set(replay_decisions)):
            if key not in original_decisions or key not in replay_decisions:
                per_decision[key] = "INDISPONIVEL"
            else:
                per_decision[key] = "IGUAL" if original_decisions[key] == replay_decisions[key] else "DIFERENTE"
        replay_value = replay.get("result") if isinstance(replay.get("result"), dict) else {}
        comparisons.append({"market_state_id": replay.get("market_state_id"), "status": "OK",
                            "decisions": per_decision,
                            "gate": _compare_value(original.get("gate_status"), replay_value.get("gate_status")),
                            "consenso": _compare_value(original.get("consensus_status"), replay_value.get("consensus_status"))})
    return comparisons


def _json_list(value: Any) -> list:
    parsed = json.loads(value or "[]") if isinstance(value, str) else value
    return parsed if isinstance(parsed, list) else []


def _compare_value(original: Any, replay: Any) -> str:
    if original in (None, "") or replay in (None, ""):
        return "INDISPONIVEL"
    return "IGUAL" if original == replay else "DIFERENTE"


def replay(states: list[dict], decision_runner: Callable[[dict], Any], *, run_at: datetime | None = None) -> list[dict]:
    """Compatibilidade da API V1, agora com sanitização recursiva e status."""
    return replay_market_states(states, decision_runner, run_at_utc=run_at)
