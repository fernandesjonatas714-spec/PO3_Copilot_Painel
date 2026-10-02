"""Supervisor operacional determinístico e somente leitura do PO3 Copilot."""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from po3.collection.freshness import is_market_active
from po3.v2_config import flags

UTC = timezone.utc
BRT = ZoneInfo("America/Sao_Paulo")
SAFE_CLOCK_STATUSES = {"ALIGNED", "OFFSET_DETECTED"}
EXPECTED_HORIZONS = ("5m", "15m", "30m", "60m")


def _utc(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip()
        if not text:
            return None
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


def _iso(value: Any) -> str | None:
    dt = _utc(value)
    return dt.isoformat() if dt else None


def _read_only(db_path: str) -> sqlite3.Connection:
    absolute = os.path.abspath(db_path).replace("\\", "/")
    return sqlite3.connect(f"file:{absolute}?mode=ro", uri=True)


def _state_payload(row: sqlite3.Row) -> dict:
    try:
        payload = json.loads(row["state_json"] or "{}")
        return payload if isinstance(payload, dict) else {}
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}


def _latest_m1_close(conn: sqlite3.Connection, symbol: str, timestamp: datetime) -> float | None:
    row = conn.execute(
        "SELECT close FROM market_bars_m1 WHERE symbol=? AND timestamp_utc=? LIMIT 1",
        (symbol, timestamp.isoformat()),
    ).fetchone()
    if row is None:
        return None
    try:
        return float(row[0])
    except (TypeError, ValueError):
        return None


def _validate_o1(conn: sqlite3.Connection, symbol: str, now: datetime) -> dict:
    since = now - timedelta(minutes=30)
    rows = conn.execute(
        "SELECT * FROM market_states WHERE symbol=? ORDER BY cutoff_at_utc ASC, id ASC",
        (symbol,),
    ).fetchall()
    recent = []
    for row in rows:
        cutoff = _utc(row["cutoff_at_utc"])
        if cutoff and since <= cutoff <= now:
            recent.append(row)
    reasons: list[str] = []
    valid_rows = []
    validity: list[bool] = []
    for row in recent:
        cutoff = _utc(row["cutoff_at_utc"])
        payload = _state_payload(row)
        start_bar = _utc(payload.get("start_bar_open_time"))
        expected = cutoff - timedelta(minutes=1) if cutoff else None
        status = payload.get("start_price_status")
        state_valid = True
        if not row["state_hash"]:
            reasons.append(f"state {row['id']}: hash ausente")
            state_valid = False
        if cutoff is None:
            reasons.append(f"state {row['id']}: cutoff inválido")
            state_valid = False
        if expected and start_bar != expected:
            reasons.append(f"state {row['id']}: start_bar incompatível")
            state_valid = False
        if status != "DISPONIVEL":
            reasons.append(f"state {row['id']}: start_price indisponível para validação causal")
            state_valid = False
        if status == "DISPONIVEL" and cutoff and start_bar:
            expected_close = _latest_m1_close(conn, symbol, start_bar)
            try:
                actual_price = float(payload.get("start_price"))
            except (TypeError, ValueError):
                actual_price = None
            if expected_close is None or actual_price is None or actual_price != expected_close:
                reasons.append(f"state {row['id']}: start_price não coincide com M1 exato")
                state_valid = False
        validity.append(state_valid)
        if state_valid:
            valid_rows.append(row)
    max_progress = 0
    current_progress = 0
    previous_cutoff: datetime | None = None
    previous_valid = False
    for row, state_valid in zip(recent, validity):
        cutoff = _utc(row["cutoff_at_utc"])
        if state_valid and previous_valid and cutoff and previous_cutoff and cutoff - previous_cutoff == timedelta(minutes=5):
            current_progress = min(3, current_progress + 1)
        elif state_valid:
            current_progress = 1
        else:
            current_progress = 0
        max_progress = max(max_progress, current_progress)
        previous_cutoff = cutoff
        previous_valid = state_valid
    chain = []
    for index in range(max(0, len(recent) - 2)):
        window = recent[index:index + 3]
        if not all(validity[index:index + 3]):
            continue
        cutoffs = [_utc(row["cutoff_at_utc"]) for row in window]
        if any(cutoff is None for cutoff in cutoffs) or any(
            cutoffs[n + 1] - cutoffs[n] != timedelta(minutes=5) for n in range(2)
        ):
            reasons.append(f"cadeia iniciada no state {window[0]['id']}: espaçamento inválido")
            continue
        chain = window
        break
    approved = len(chain) == 3
    details = (
        f"Cadeia causal aprovada: {[int(row['id']) for row in chain]}."
        if approved else (reasons or ("Aguardando três MarketStates causais válidos." if recent else "Aguardando dados."))
    )
    return {
        "status": "APROVADO" if approved else ("VALIDANDO_CAUSALIDADE" if recent else "AGUARDANDO_DADOS"),
        "valid_states": min(3, max_progress),
        "required_states": 3,
        "details": details,
        "state_ids": [int(row["id"]) for row in chain],
    }


def build_supervisor_snapshot(db_path: str, symbol: str, now_utc: datetime | None = None) -> dict:
    """Lê o estado factual sem gravar, migrar ou chamar qualquer IA."""
    now = (now_utc or datetime.now(UTC)).astimezone(UTC)
    active = is_market_active(now)
    conn = _read_only(db_path)
    try:
        conn.row_factory = sqlite3.Row
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        counts = {}
        for table in ("market_bars_m1", "market_states", "observed_outcomes", "decision_observations", "shadow_runs"):
            counts[table] = int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
        runtime = conn.execute("SELECT * FROM collector_runtime_status WHERE symbol=?", (symbol,)).fetchone()
        lease = conn.execute("SELECT * FROM collector_leases WHERE collector_name='po3-m1' AND symbol=?", (symbol,)).fetchone()
        latest_m1 = conn.execute("SELECT MAX(timestamp_utc) FROM market_bars_m1 WHERE symbol=?", (symbol,)).fetchone()[0]
        latest_state = conn.execute("SELECT * FROM market_states WHERE symbol=? ORDER BY cutoff_at_utc DESC,id DESC LIMIT 1", (symbol,)).fetchone()
        latest_shadow = conn.execute("SELECT id,market_state_id,cutoff_at_utc,status,model_configured,model_used,error_type,error_message,created_at_utc FROM shadow_runs WHERE symbol=? ORDER BY cutoff_at_utc DESC,id DESC LIMIT 1", (symbol,)).fetchone()
        outcome_rows = conn.execute("SELECT horizon_code,status,COUNT(*) n FROM observed_outcomes WHERE symbol=? GROUP BY horizon_code,status", (symbol,)).fetchall()
        outcomes = {"total": sum(int(row["n"]) for row in outcome_rows), "por_horizon": {}, "por_status": {}}
        for row in outcome_rows:
            horizon, status, count = row["horizon_code"], row["status"], int(row["n"])
            outcomes["por_horizon"].setdefault(horizon, 0)
            outcomes["por_horizon"][horizon] += count
            outcomes["por_status"][status] = outcomes["por_status"].get(status, 0) + count
        latest = None
        if latest_state:
            payload = _state_payload(latest_state)
            latest = {
                "id": int(latest_state["id"]), "symbol": latest_state["symbol"],
                "cutoff_at_utc": latest_state["cutoff_at_utc"], "state_hash": latest_state["state_hash"],
                "start_bar_open_time": payload.get("start_bar_open_time"),
                "start_price": payload.get("start_price"),
                "start_price_status": payload.get("start_price_status"),
            }
        runtime_data = dict(runtime) if runtime else {}
        lease_data = dict(lease) if lease else {}
        lease_active = bool(lease and _utc(lease["expires_at"]) and _utc(lease["expires_at"]) > now)
        security = {key: flags().get(key, False) for key in ("AUTO_DECISION_ENGINE", "SHADOW_MODE_ENABLED", "REPLAY_ENABLED", "CALIBRATION_ENABLED", "MODEL_BENCHMARK_ENABLED")}
        o1 = _validate_o1(conn, symbol, now)
    finally:
        conn.close()
    shadow_data = dict(latest_shadow) if latest_shadow else None
    dangerous = security["AUTO_DECISION_ENGINE"]
    if dangerous:
        overall = "ATENCAO_SEGURANCA"
    elif integrity != "ok":
        overall = "ATENCAO_BANCO"
    elif not active:
        overall = "AGUARDANDO_SESSAO"
    elif runtime_data.get("clock_alignment_status") not in SAFE_CLOCK_STATUSES:
        overall = "ATENCAO_CLOCK"
    elif runtime_data.get("feed_liveness_status") not in {"LIVE", "ATUAL"}:
        overall = "ATENCAO_FEED"
    elif not lease_active:
        overall = "ATENCAO_LEASE"
    elif o1["status"] == "APROVADO":
        overall = "OPERACAO_NORMAL"
    else:
        overall = "VALIDANDO_CAUSALIDADE"
    local = now.astimezone(BRT).isoformat()
    snapshot = {
        "timestamp_utc": now.isoformat(), "symbol": symbol,
        "session": {"market_active": active, "local_time": local, "session_status": "ABERTA" if active else "FECHADA"},
        "collector": {key: runtime_data.get(key) for key in ("status", "feed_liveness_status", "clock_alignment_status", "detected_offset_seconds", "normalized_tick_at_utc", "last_closed_at_utc", "feed_lag_seconds")},
        "lease": {"active": lease_active, "owner_id": lease_data.get("owner_id"), "expires_at": lease_data.get("expires_at")},
        "database": {"integrity_status": integrity, **counts},
        "latest_m1": {"timestamp_utc": latest_m1}, "latest_market_state": latest,
        "outcomes": outcomes, "shadow": {"enabled": security["SHADOW_MODE_ENABLED"], "latest": shadow_data},
        "security": security, "o1_validation": o1, "overall_status": overall,
    }
    return snapshot


def operational_state_hash(snapshot: dict) -> str:
    collector = snapshot.get("collector", {})
    relevant = {
        "symbol": snapshot.get("symbol"),
        "session": {"market_active": snapshot.get("session", {}).get("market_active"), "session_status": snapshot.get("session", {}).get("session_status")},
        "collector": {key: collector.get(key) for key in ("status", "feed_liveness_status", "clock_alignment_status")},
        "lease_active": snapshot.get("lease", {}).get("active"),
        "latest_market_state": snapshot.get("latest_market_state"),
        "outcomes": snapshot.get("outcomes", {}),
        "security": snapshot.get("security", {}),
        "o1_validation": snapshot.get("o1_validation", {}),
        "overall_status": snapshot.get("overall_status"),
    }
    return hashlib.sha256(json.dumps(relevant, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def supervisor_ai_gate(snapshot: dict, state: dict, now: datetime | None = None) -> dict:
    """Decide se uma narrativa pode ser solicitada, sem chamar a IA."""
    now = now or datetime.now(UTC)
    current_hash = operational_state_hash(snapshot)
    current_status = snapshot.get("overall_status")
    previous_hash = state.get("last_supervisor_hash")
    previous_status = state.get("last_supervisor_status")
    previous_at = state.get("last_supervisor_ai_at")
    critical = {"ATENCAO_SEGURANCA", "ATENCAO_BANCO", "ATENCAO_CLOCK", "ATENCAO_FEED"}
    critical_transition = current_status in critical and previous_status is not None and current_status != previous_status
    if current_hash == previous_hash:
        return {"should_call": False, "critical_transition": False, "hash": current_hash, "status": current_status}
    if previous_at:
        when = _utc(previous_at)
        if when and (now.astimezone(UTC) - when).total_seconds() < 300 and not critical_transition:
            return {"should_call": False, "critical_transition": False, "hash": current_hash, "status": current_status}
    return {"should_call": True, "critical_transition": critical_transition, "hash": current_hash, "status": current_status}


def supervisor_ai_context(snapshot: dict) -> str:
    return json.dumps(snapshot, ensure_ascii=False, sort_keys=True, default=str)
