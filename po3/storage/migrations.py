"""Migrações idempotentes para o pipeline histórico da V2."""
from __future__ import annotations
import shutil, sqlite3
from datetime import datetime, timezone
from pathlib import Path

CURRENT_SCHEMA_VERSION = "2.0.0"

def _connect(path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=5000")
    return conn

def backup_database(db_path: str | Path) -> Path | None:
    src = Path(db_path)
    if not src.exists():
        return None
    with _connect(src) as conn:
        check = conn.execute("PRAGMA integrity_check").fetchone()[0]
        if check != "ok":
            raise RuntimeError(f"Banco SQLite inválido: {check}")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dst = src.with_name(f"{src.stem}.backup-{stamp}{src.suffix}")
    shutil.copy2(src, dst)
    return dst

def migrate(db_path: str | Path) -> str:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    from po3.learning_store import initialize
    initialize(path)
    with _connect(path) as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
          version TEXT PRIMARY KEY, applied_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS market_bars_m1 (
          id INTEGER PRIMARY KEY, symbol TEXT NOT NULL, timestamp_utc TEXT NOT NULL,
          open REAL NOT NULL, high REAL NOT NULL, low REAL NOT NULL, close REAL NOT NULL,
          tick_volume REAL, real_volume REAL, spread REAL, source TEXT NOT NULL,
          schema_version TEXT NOT NULL, created_at TEXT NOT NULL,
          UNIQUE(symbol, timestamp_utc)
        );
        CREATE INDEX IF NOT EXISTS idx_bars_symbol_time ON market_bars_m1(symbol,timestamp_utc);
        CREATE TABLE IF NOT EXISTS collector_leases (
          collector_name TEXT NOT NULL, symbol TEXT NOT NULL, owner_id TEXT NOT NULL,
          pid INTEGER, started_at TEXT NOT NULL, heartbeat_at TEXT NOT NULL,
          expires_at TEXT NOT NULL, PRIMARY KEY(collector_name,symbol)
        );
        CREATE TABLE IF NOT EXISTS market_states (
          id INTEGER PRIMARY KEY, symbol TEXT NOT NULL, cutoff_at_utc TEXT NOT NULL,
          created_at TEXT NOT NULL, market_state_version TEXT NOT NULL,
          decision_engine_version TEXT NOT NULL, prompt_version TEXT NOT NULL,
          schema_version TEXT NOT NULL, state_json TEXT NOT NULL, state_hash TEXT NOT NULL,
          sources_json TEXT NOT NULL, status TEXT NOT NULL,
          UNIQUE(symbol,cutoff_at_utc)
        );
        CREATE INDEX IF NOT EXISTS idx_states_symbol_cutoff ON market_states(symbol,cutoff_at_utc);
        CREATE TABLE IF NOT EXISTS observed_outcomes (
          id INTEGER PRIMARY KEY, market_state_id INTEGER NOT NULL, symbol TEXT NOT NULL,
          horizon_code TEXT NOT NULL, target_at_utc TEXT NOT NULL, observed_at_utc TEXT,
          start_price REAL NOT NULL, future_price REAL, future_high REAL, future_low REAL,
          high_delta REAL, low_delta REAL, absolute_change REAL, percentage_change REAL,
          candles_observed INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL,
          schema_version TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
          UNIQUE(market_state_id,horizon_code)
        );
        CREATE INDEX IF NOT EXISTS idx_outcomes_state ON observed_outcomes(market_state_id);
        CREATE TABLE IF NOT EXISTS decision_observations (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          analysis_run_id INTEGER NOT NULL UNIQUE,
          market_state_id INTEGER,
          symbol TEXT NOT NULL,
          decision_state_hash TEXT NOT NULL,
          link_status TEXT NOT NULL,
          decisions_json TEXT NOT NULL,
          gate_status TEXT,
          consensus_status TEXT,
          model_configured TEXT,
          model_used TEXT,
          fallback_used INTEGER NOT NULL DEFAULT 0,
          repair_used INTEGER NOT NULL DEFAULT 0,
          decision_engine_version TEXT,
          prompt_version TEXT,
          schema_version TEXT NOT NULL,
          created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_decision_observations_market_state ON decision_observations(market_state_id);
        CREATE TABLE IF NOT EXISTS shadow_runs (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          market_state_id INTEGER NOT NULL,
          symbol TEXT NOT NULL,
          cutoff_at_utc TEXT NOT NULL,
          state_hash TEXT NOT NULL,
          shadow_mode_version TEXT NOT NULL,
          decision_engine_version TEXT NOT NULL,
          prompt_version TEXT NOT NULL,
          schema_version TEXT NOT NULL,
          model_configured TEXT NOT NULL,
          model_used TEXT,
          fallback_used INTEGER NOT NULL DEFAULT 0,
          repair_used INTEGER NOT NULL DEFAULT 0,
          gate_status TEXT,
          consensus_status TEXT,
          decisions_json TEXT NOT NULL,
          status TEXT NOT NULL,
          error_type TEXT,
          error_message TEXT,
          duration_seconds REAL,
          created_at_utc TEXT NOT NULL,
          UNIQUE(market_state_id, shadow_mode_version, decision_engine_version, prompt_version, model_configured)
        );
        CREATE INDEX IF NOT EXISTS idx_shadow_runs_market_state ON shadow_runs(market_state_id);
        CREATE TABLE IF NOT EXISTS official_decision_runs (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          market_state_id INTEGER NOT NULL,
          symbol TEXT NOT NULL,
          cutoff_at_utc TEXT NOT NULL,
          state_hash TEXT NOT NULL,
          decision_engine_version TEXT NOT NULL,
          prompt_version TEXT NOT NULL,
          schema_version TEXT NOT NULL,
          model_configured TEXT NOT NULL,
          model_used TEXT,
          fallback_used INTEGER NOT NULL DEFAULT 0,
          repair_used INTEGER NOT NULL DEFAULT 0,
          gate_status TEXT,
          consensus_status TEXT,
          confidence TEXT,
          context_operational TEXT,
          model_attempts_json TEXT NOT NULL DEFAULT '[]',
          decision_status TEXT,
          narrative_status TEXT,
          decisions_json TEXT NOT NULL,
          narrative TEXT,
          status TEXT NOT NULL,
          error_type TEXT,
          error_message TEXT,
          duration_seconds REAL,
          created_at_utc TEXT NOT NULL,
          UNIQUE(market_state_id, decision_engine_version, prompt_version, model_configured)
        );
        CREATE INDEX IF NOT EXISTS idx_official_decision_latest
          ON official_decision_runs(symbol, cutoff_at_utc, id);
        CREATE TABLE IF NOT EXISTS collector_runtime_status (
          symbol TEXT PRIMARY KEY, status TEXT NOT NULL, feed_lag_seconds REAL,
          last_closed_at_utc TEXT, last_tick_at_utc TEXT, detail TEXT, updated_at TEXT NOT NULL
        );
        """)
        bar_columns = {row[1] for row in conn.execute("PRAGMA table_info(market_bars_m1)")}
        if "source_timestamp_raw" not in bar_columns:
            conn.execute("ALTER TABLE market_bars_m1 ADD COLUMN source_timestamp_raw INTEGER")
        if "time_offset_seconds" not in bar_columns:
            conn.execute("ALTER TABLE market_bars_m1 ADD COLUMN time_offset_seconds REAL")
        runtime_columns = {row[1] for row in conn.execute("PRAGMA table_info(collector_runtime_status)")}
        if "feed_liveness_status" not in runtime_columns:
            conn.execute("ALTER TABLE collector_runtime_status ADD COLUMN feed_liveness_status TEXT")
        if "clock_alignment_status" not in runtime_columns:
            conn.execute("ALTER TABLE collector_runtime_status ADD COLUMN clock_alignment_status TEXT")
        if "detected_offset_seconds" not in runtime_columns:
            conn.execute("ALTER TABLE collector_runtime_status ADD COLUMN detected_offset_seconds REAL")
        if "normalized_tick_at_utc" not in runtime_columns:
            conn.execute("ALTER TABLE collector_runtime_status ADD COLUMN normalized_tick_at_utc TEXT")
        official_columns = {row[1] for row in conn.execute("PRAGMA table_info(official_decision_runs)")}
        for column, definition in (("model_attempts_json", "TEXT NOT NULL DEFAULT '[]'"), ("decision_status", "TEXT"), ("narrative_status", "TEXT")):
            if column not in official_columns:
                conn.execute(f"ALTER TABLE official_decision_runs ADD COLUMN {column} {definition}")
        conn.execute("INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES(?,?)",
                     (CURRENT_SCHEMA_VERSION, datetime.now(timezone.utc).isoformat()))
    return CURRENT_SCHEMA_VERSION
