from __future__ import annotations
import argparse, os, time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from po3.storage.migrations import migrate
from po3.storage.market_repository import acquire_lease, heartbeat, release_lease, insert_m1_bars, latest_m1_timestamp

@dataclass(frozen=True)
class CollectorConfig:
    symbol: str
    db_path: str
    terminal_path: str | None = None
    source: str = "MT5"
    lease_name: str = "po3-m1"
    poll_seconds: int = 60

def _dt(ts: Any) -> datetime:
    if isinstance(ts, datetime): return ts.astimezone(timezone.utc)
    return datetime.fromtimestamp(float(ts), tz=timezone.utc)

def closed_m1_bars(mt5: Any, symbol: str, now_utc: datetime | None = None, count: int = 2000, source: str = "MT5") -> list[dict]:
    now_utc = (now_utc or datetime.now(timezone.utc)).astimezone(timezone.utc)
    rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M1, 1, count)
    if rates is None: return []
    out=[]
    for row in rates:
        t=_dt(row["time"] if isinstance(row, dict) else row["time"])
        if t + timedelta(minutes=1) <= now_utc:
            names = getattr(getattr(row, 'dtype', None), 'names', None)
            get=lambda k, default=None: row[k] if ((isinstance(row, dict) and k in row) or (names and k in names)) else default
            out.append({"symbol":symbol,"timestamp_utc":t,"open":float(row["open"]),"high":float(row["high"]),"low":float(row["low"]),"close":float(row["close"]),"tick_volume":get("tick_volume"),"real_volume":get("real_volume"),"spread":get("spread"),"source":source})
    return sorted(out,key=lambda x:x["timestamp_utc"])

def collect_once(config: CollectorConfig, mt5: Any, owner_id: str | None = None, now_utc: datetime | None = None) -> dict:
    migrate(config.db_path)
    owner=acquire_lease(config.lease_name,config.symbol,config.db_path,owner_id)
    if not owner: return {"status":"LEASE_OCUPADA","inserted":0}
    try:
        bars=closed_m1_bars(mt5,config.symbol,now_utc,source=config.source)
        inserted=insert_m1_bars(bars,config.db_path)
        heartbeat(config.lease_name,config.symbol,owner,config.db_path)
        return {"status":"OK","inserted":inserted,"latest":latest_m1_timestamp(config.symbol,config.db_path)}
    finally: release_lease(config.lease_name,config.symbol,owner,config.db_path)

def run_worker(config: CollectorConfig, mt5: Any, stop_event=None, max_cycles: int | None = None) -> None:
    migrate(config.db_path); owner=acquire_lease(config.lease_name,config.symbol,config.db_path)
    if not owner: raise RuntimeError("Outro coletor já possui o lease")
    cycles=0
    try:
        while max_cycles is None or cycles < max_cycles:
            bars=closed_m1_bars(mt5,config.symbol,source=config.source); insert_m1_bars(bars,config.db_path)
            heartbeat(config.lease_name,config.symbol,owner,config.db_path); cycles+=1
            if stop_event is not None and stop_event.is_set(): break
            if max_cycles is None: time.sleep(config.poll_seconds)
    finally: release_lease(config.lease_name,config.symbol,owner,config.db_path)

def main() -> int:
    p=argparse.ArgumentParser(description="Coletor M1 fechado do PO3 Copilot")
    p.add_argument("--symbol",default=os.getenv("MT5_SYMBOL","WINV26")); p.add_argument("--db",default="data/po3_learning.sqlite")
    args=p.parse_args(); raise SystemExit("A execução requer um terminal MT5 conectado; use o worker pelo ambiente do projeto.")

if __name__ == "__main__": main()
