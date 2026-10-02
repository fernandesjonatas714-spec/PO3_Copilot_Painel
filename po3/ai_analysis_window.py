"""Janela única para chamadas automáticas de IA.

Esta regra não interfere na coleta factual, no MT5, em Outcomes ou no chat
manual. O watermark persistido evita que uma reinicialização reprocesse estados
antigos automaticamente.
"""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

DEFAULT_ENABLED = True
DEFAULT_START = "08:45"
DEFAULT_END = "18:00"
DEFAULT_TIMEZONE = "America/Sao_Paulo"
WATERMARK_SCOPE = "automatic_ai"


def _dotenv_values() -> dict[str, str]:
    values: dict[str, str] = {}
    path = Path(__file__).resolve().parent.parent / ".env"
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    except OSError:
        pass
    return values


def _value(name: str, default: str) -> str:
    return os.getenv(name, _dotenv_values().get(name, default)).strip()


def window_config() -> dict[str, object]:
    enabled = _value("AI_ANALYSIS_WINDOW_ENABLED", "true").lower() in {"1", "true", "sim", "yes"}
    start_text = _value("AI_ANALYSIS_START", DEFAULT_START)
    end_text = _value("AI_ANALYSIS_END", DEFAULT_END)
    timezone_name = _value("AI_ANALYSIS_TIMEZONE", DEFAULT_TIMEZONE) or DEFAULT_TIMEZONE
    try:
        start = time.fromisoformat(start_text)
    except ValueError:
        start_text, start = DEFAULT_START, time(8, 45)
    try:
        end = time.fromisoformat(end_text)
    except ValueError:
        end_text, end = DEFAULT_END, time(18, 0)
    try:
        zone = ZoneInfo(timezone_name)
    except Exception:
        timezone_name, zone = DEFAULT_TIMEZONE, ZoneInfo(DEFAULT_TIMEZONE)
    return {"enabled": enabled, "start": start, "end": end,
            "start_text": start_text, "end_text": end_text,
            "timezone": timezone_name, "zone": zone}


def _as_utc(value: datetime | None) -> datetime:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        return current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc)


def is_ai_analysis_window_open(now: datetime | None = None) -> bool:
    config = window_config()
    if not config["enabled"]:
        return True
    local = _as_utc(now).astimezone(config["zone"])
    return local.weekday() < 5 and config["start"] <= local.time() < config["end"]


def next_ai_analysis_window(now: datetime | None = None) -> datetime:
    config = window_config()
    local = _as_utc(now).astimezone(config["zone"])
    candidate = local.replace(hour=config["start"].hour, minute=config["start"].minute,
                              second=0, microsecond=0)
    if local.time() >= config["start"] or local.weekday() >= 5:
        candidate += timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate += timedelta(days=1)
    return candidate.astimezone(timezone.utc)


def current_ai_window_status(now: datetime | None = None) -> dict[str, object]:
    config = window_config()
    current = _as_utc(now)
    local = current.astimezone(config["zone"])
    opened = is_ai_analysis_window_open(current)
    return {"open": opened, "enabled": config["enabled"], "local_time": local.isoformat(),
            "start": config["start_text"], "end": config["end_text"],
            "timezone": config["timezone"],
            "next_open_utc": None if opened else next_ai_analysis_window(current).isoformat(),
            "reason": "ATIVA" if opened else "FORA_JANELA_IA"}


def ensure_ai_analysis_baseline(db_path: str | Path, symbol: str,
                                now: datetime | None = None) -> tuple[str, int, str | None] | None:
    """Cria uma vez por dia o marco a partir do qual a IA pode trabalhar."""
    current = _as_utc(now)
    if not is_ai_analysis_window_open(current):
        return None
    local_date = current.astimezone(window_config()["zone"]).date().isoformat()
    path = Path(db_path)
    with sqlite3.connect(path, timeout=5) as conn:
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("""CREATE TABLE IF NOT EXISTS ai_analysis_watermarks (
            scope TEXT NOT NULL, symbol TEXT NOT NULL, local_date TEXT NOT NULL,
            baseline_market_state_id INTEGER NOT NULL DEFAULT 0,
            baseline_cutoff_at_utc TEXT, created_at_utc TEXT NOT NULL,
            PRIMARY KEY(scope, symbol, local_date)
        )""")
        row = conn.execute("""SELECT scope,symbol,local_date,baseline_market_state_id,baseline_cutoff_at_utc
                             FROM ai_analysis_watermarks WHERE scope=? AND symbol=? AND local_date=?""",
                           (WATERMARK_SCOPE, symbol, local_date)).fetchone()
        if row:
            return str(row[2]), int(row[3]), row[4]
        latest = conn.execute("""SELECT id,cutoff_at_utc FROM market_states
                                WHERE symbol=? ORDER BY cutoff_at_utc DESC,id DESC LIMIT 1""", (symbol,)).fetchone()
        baseline_id = int(latest[0]) if latest else 0
        baseline_cutoff = latest[1] if latest else None
        conn.execute("""INSERT OR IGNORE INTO ai_analysis_watermarks
                       (scope,symbol,local_date,baseline_market_state_id,baseline_cutoff_at_utc,created_at_utc)
                       VALUES (?,?,?,?,?,?)""",
                     (WATERMARK_SCOPE, symbol, local_date, baseline_id, baseline_cutoff, current.isoformat()))
        return local_date, baseline_id, baseline_cutoff


def state_is_after_baseline(state_id: int, cutoff_at_utc: str | None,
                            baseline: tuple[str, int, str | None] | None) -> bool:
    if baseline is None:
        return False
    _, baseline_id, baseline_cutoff = baseline
    if baseline_cutoff is None:
        return int(state_id) > baseline_id
    return (str(cutoff_at_utc or "") > str(baseline_cutoff) or
            (str(cutoff_at_utc or "") == str(baseline_cutoff) and int(state_id) > baseline_id))
