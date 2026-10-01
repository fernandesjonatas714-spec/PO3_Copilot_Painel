"""Repositório factual do coletor e dos resultados observados."""
from __future__ import annotations
import hashlib, json, os, sqlite3, uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Mapping
from .migrations import CURRENT_SCHEMA_VERSION, migrate

def utc_now() -> datetime: return datetime.now(timezone.utc)
def iso(value: datetime | str) -> str:
    if isinstance(value, str): return value
    return value.astimezone(timezone.utc).isoformat()
def connect(db_path: str | Path) -> sqlite3.Connection:
    migrate(db_path)
    c = sqlite3.connect(str(db_path), timeout=5)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA busy_timeout=5000")
    return c

def insert_m1_bars(bars: Iterable[Mapping], db_path: str | Path) -> int:
    now = iso(utc_now()); rows = []
    for b in bars:
        rows.append((str(b["symbol"]), iso(b["timestamp_utc"]), float(b["open"]), float(b["high"]),
                     float(b["low"]), float(b["close"]), b.get("tick_volume"), b.get("real_volume"),
                     b.get("spread"), b.get("source", "MT5"), CURRENT_SCHEMA_VERSION, now,
                     b.get("source_timestamp_raw"), b.get("time_offset_seconds")))
    with connect(db_path) as c:
        before = c.total_changes
        c.executemany("""INSERT OR IGNORE INTO market_bars_m1
          (symbol,timestamp_utc,open,high,low,close,tick_volume,real_volume,spread,source,schema_version,created_at,source_timestamp_raw,time_offset_seconds)
          VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", rows)
        return c.total_changes - before

def latest_m1_timestamp(symbol: str, db_path: str | Path) -> str | None:
    with connect(db_path) as c:
        row = c.execute("SELECT MAX(timestamp_utc) t FROM market_bars_m1 WHERE symbol=?", (symbol,)).fetchone()
        return row["t"] if row and row["t"] else None

def get_m1_range(symbol: str, start: datetime | str, end: datetime | str, db_path: str | Path) -> list[dict]:
    with connect(db_path) as c:
        rows = c.execute("SELECT * FROM market_bars_m1 WHERE symbol=? AND timestamp_utc>=? AND timestamp_utc<=? ORDER BY timestamp_utc", (symbol,iso(start),iso(end))).fetchall()
        return [dict(r) for r in rows]

def get_m1_bar(symbol: str, timestamp: datetime | str, db_path: str | Path) -> dict | None:
    """Exact M1 bar by open timestamp."""
    with connect(db_path) as c:
        row = c.execute(
            "SELECT * FROM market_bars_m1 WHERE symbol=? AND timestamp_utc=? LIMIT 1",
            (symbol, iso(timestamp)),
        ).fetchone()
        return dict(row) if row else None

def get_v2_m1_bar(symbol: str, timestamp: datetime | str, db_path: str | Path) -> dict | None:
    """Retorna somente a barra M1 canônica, no horário de abertura exato.

    Registros sem os metadados de origem/alinhamento são históricos legados e
    não podem satisfazer contratos causais da V2.
    """
    with connect(db_path) as c:
        row = c.execute(
            """SELECT * FROM market_bars_m1
               WHERE symbol=? AND timestamp_utc=?
                 AND source_timestamp_raw IS NOT NULL
                 AND time_offset_seconds IS NOT NULL
               LIMIT 1""",
            (symbol, iso(timestamp)),
        ).fetchone()
        return dict(row) if row else None

def get_v2_m1_range(symbol: str, start: datetime | str, end: datetime | str, db_path: str | Path) -> list[dict]:
    """Faixa [start, end] contendo apenas barras M1 canônicas da V2."""
    with connect(db_path) as c:
        rows = c.execute(
            """SELECT * FROM market_bars_m1
               WHERE symbol=? AND timestamp_utc>=? AND timestamp_utc<=?
                 AND source_timestamp_raw IS NOT NULL
                 AND time_offset_seconds IS NOT NULL
               ORDER BY timestamp_utc""",
            (symbol, iso(start), iso(end)),
        ).fetchall()
        return [dict(r) for r in rows]

def acquire_lease(name: str, symbol: str, db_path: str | Path, owner_id: str | None = None, ttl_seconds: int = 90) -> str | None:
    owner_id = owner_id or f"{os.getpid()}-{uuid.uuid4().hex}"
    now = utc_now(); exp = now + timedelta(seconds=ttl_seconds)
    with connect(db_path) as c:
        row = c.execute("SELECT owner_id,expires_at FROM collector_leases WHERE collector_name=? AND symbol=?",(name,symbol)).fetchone()
        if row and row["owner_id"] != owner_id and row["expires_at"] > iso(now): return None
        c.execute("""INSERT INTO collector_leases VALUES(?,?,?,?,?,?,?)
          ON CONFLICT(collector_name,symbol) DO UPDATE SET owner_id=excluded.owner_id,pid=excluded.pid,
          started_at=excluded.started_at,heartbeat_at=excluded.heartbeat_at,expires_at=excluded.expires_at""",
          (name,symbol,owner_id,os.getpid(),iso(now),iso(now),iso(exp)))
    return owner_id

def heartbeat(name: str, symbol: str, owner_id: str, db_path: str | Path, ttl_seconds: int = 90) -> bool:
    now=utc_now(); exp=now+timedelta(seconds=ttl_seconds)
    with connect(db_path) as c:
        cur=c.execute("UPDATE collector_leases SET heartbeat_at=?,expires_at=? WHERE collector_name=? AND symbol=? AND owner_id=?",(iso(now),iso(exp),name,symbol,owner_id))
        return cur.rowcount == 1
def release_lease(name: str, symbol: str, owner_id: str, db_path: str | Path) -> None:
    with connect(db_path) as c: c.execute("DELETE FROM collector_leases WHERE collector_name=? AND symbol=? AND owner_id=?",(name,symbol,owner_id))

def insert_market_state(state: Mapping, db_path: str | Path, *, cutoff_at_utc: datetime | str, symbol: str, sources: Mapping | None = None, versions: Mapping | None = None) -> int:
    payload=json.dumps(state,ensure_ascii=False,sort_keys=True,separators=(",",":"),default=str)
    digest=hashlib.sha256(payload.encode()).hexdigest(); versions=versions or {}
    with connect(db_path) as c:
        cur=c.execute("""INSERT OR IGNORE INTO market_states(symbol,cutoff_at_utc,created_at,market_state_version,decision_engine_version,prompt_version,schema_version,state_json,state_hash,sources_json,status)
          VALUES(?,?,?,?,?,?,?,?,?,?,?)""",(symbol,iso(cutoff_at_utc),iso(utc_now()),versions.get("market_state","2.0"),versions.get("decision_engine","v2"),versions.get("prompt","v2"),CURRENT_SCHEMA_VERSION,payload,digest,json.dumps(sources or {},ensure_ascii=False,default=str),"CAPTURADO"))
        if cur.rowcount == 1: return int(cur.lastrowid)
        return int(c.execute("SELECT id FROM market_states WHERE symbol=? AND cutoff_at_utc=?",(symbol,iso(cutoff_at_utc))).fetchone()["id"])

def list_states(db_path: str | Path, symbol: str | None = None) -> list[dict]:
    with connect(db_path) as c:
        q="SELECT * FROM market_states"; args=()
        if symbol: q += " WHERE symbol=?"; args=(symbol,)
        q += " ORDER BY cutoff_at_utc"
        return [dict(r) for r in c.execute(q,args).fetchall()]

def upsert_outcome(outcome: Mapping, db_path: str | Path) -> None:
    now=iso(utc_now()); vals={**outcome,"schema_version":CURRENT_SCHEMA_VERSION,"updated_at":now,"created_at":outcome.get("created_at",now)}
    cols=["market_state_id","symbol","horizon_code","target_at_utc","observed_at_utc","start_price","future_price","future_high","future_low","high_delta","low_delta","absolute_change","percentage_change","candles_observed","status","schema_version","created_at","updated_at"]
    with connect(db_path) as c:
        c.execute(f"INSERT INTO observed_outcomes ({','.join(cols)}) VALUES ({','.join('?' for _ in cols)}) ON CONFLICT(market_state_id,horizon_code) DO UPDATE SET "+','.join(f"{x}=excluded.{x}" for x in cols[4:]), tuple(vals.get(x) for x in cols))

def get_outcomes(db_path: str | Path, state_id: int | None = None) -> list[dict]:
    with connect(db_path) as c:
        q="SELECT * FROM observed_outcomes"; args=()
        if state_id is not None: q+=" WHERE market_state_id=?"; args=(state_id,)
        return [dict(r) for r in c.execute(q+" ORDER BY horizon_code",args).fetchall()]

def collection_status(symbol: str, db_path: str | Path) -> dict:
    """Retorna somente status persistido para a UI, sem coletar nem chamar IA."""
    try:
        with connect(db_path) as c:
            lease = c.execute("SELECT heartbeat_at,expires_at FROM collector_leases WHERE collector_name=? AND symbol=?", ("po3-m1", symbol)).fetchone()
            bar = c.execute("SELECT MAX(timestamp_utc) AS ts FROM market_bars_m1 WHERE symbol=?", (symbol,)).fetchone()
            state = c.execute("SELECT MAX(cutoff_at_utc) AS ts FROM market_states WHERE symbol=?", (symbol,)).fetchone()
            pending = c.execute("SELECT COUNT(*) AS n FROM observed_outcomes WHERE status IN ('PENDENTE','SEM_DADO') AND symbol=?", (symbol,)).fetchone()
            now = utc_now()
            active = bool(lease and lease["expires_at"] > iso(now))
            runtime = c.execute("SELECT * FROM collector_runtime_status WHERE symbol=?", (symbol,)).fetchone()
            return {"status": "ATIVA" if active else "PAUSADA", "ultimo_m1": bar["ts"] if bar else None,
                    "ultimo_market_state": state["ts"] if state else None, "outcomes_pendentes": int(pending["n"] if pending else 0),
                    "feed_status": runtime["status"] if runtime else "SEM_DADOS",
                    "feed_lag_seconds": runtime["feed_lag_seconds"] if runtime else None,
                    "last_closed_at_utc": runtime["last_closed_at_utc"] if runtime else None,
                    "last_tick_at_utc": runtime["last_tick_at_utc"] if runtime else None,
                    "feed_liveness_status": runtime["feed_liveness_status"] if runtime and "feed_liveness_status" in runtime.keys() else None,
                    "clock_alignment_status": runtime["clock_alignment_status"] if runtime and "clock_alignment_status" in runtime.keys() else None,
                    "detected_offset_seconds": runtime["detected_offset_seconds"] if runtime and "detected_offset_seconds" in runtime.keys() else None,
                    "normalized_tick_at_utc": runtime["normalized_tick_at_utc"] if runtime and "normalized_tick_at_utc" in runtime.keys() else None}
    except Exception as exc:
        return {"status": "ERRO", "erro": str(exc), "ultimo_m1": None, "ultimo_market_state": None, "outcomes_pendentes": 0}


def update_runtime_status(symbol: str, db_path: str | Path, *, status: str,
                         feed_lag_seconds: float | None,
                         last_closed_at_utc: str | None,
                         last_tick_at_utc: str | None,
                         detail: str = "",
                         feed_liveness_status: str | None = None,
                         clock_alignment_status: str | None = None,
                         detected_offset_seconds: float | None = None,
                         normalized_tick_at_utc: str | None = None) -> None:
    now = iso(utc_now())
    with connect(db_path) as c:
        c.execute("""CREATE TABLE IF NOT EXISTS collector_runtime_status (
            symbol TEXT PRIMARY KEY, status TEXT NOT NULL, feed_lag_seconds REAL,
            last_closed_at_utc TEXT, last_tick_at_utc TEXT, detail TEXT,
            updated_at TEXT NOT NULL, feed_liveness_status TEXT,
            clock_alignment_status TEXT, detected_offset_seconds REAL,
            normalized_tick_at_utc TEXT)""")
        c.execute("""INSERT INTO collector_runtime_status
            (symbol,status,feed_lag_seconds,last_closed_at_utc,last_tick_at_utc,detail,updated_at,
             feed_liveness_status,clock_alignment_status,detected_offset_seconds,normalized_tick_at_utc)
            VALUES(?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(symbol) DO UPDATE SET status=excluded.status,
            feed_lag_seconds=excluded.feed_lag_seconds,last_closed_at_utc=excluded.last_closed_at_utc,
            last_tick_at_utc=excluded.last_tick_at_utc,detail=excluded.detail,updated_at=excluded.updated_at,
            feed_liveness_status=excluded.feed_liveness_status,
            clock_alignment_status=excluded.clock_alignment_status,
            detected_offset_seconds=excluded.detected_offset_seconds,
            normalized_tick_at_utc=excluded.normalized_tick_at_utc""",
            (symbol,status,feed_lag_seconds,last_closed_at_utc,last_tick_at_utc,detail,now,
             feed_liveness_status,clock_alignment_status,detected_offset_seconds,normalized_tick_at_utc))

def runtime_status(symbol: str, db_path: str | Path) -> dict:
    with connect(db_path) as c:
        c.execute("""CREATE TABLE IF NOT EXISTS collector_runtime_status (
            symbol TEXT PRIMARY KEY, status TEXT NOT NULL, feed_lag_seconds REAL,
            last_closed_at_utc TEXT, last_tick_at_utc TEXT, detail TEXT,
            updated_at TEXT NOT NULL)""")
        row=c.execute("SELECT * FROM collector_runtime_status WHERE symbol=?",(symbol,)).fetchone()
        return dict(row) if row else {"symbol":symbol,"status":"SEM_DADOS","feed_lag_seconds":None,"last_closed_at_utc":None,"last_tick_at_utc":None,"detail":"Ainda sem coleta."}
