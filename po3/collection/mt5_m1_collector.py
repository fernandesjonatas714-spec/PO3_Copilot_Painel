from __future__ import annotations
import argparse
import os
import signal
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from threading import Event
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
    lease_ttl_seconds: int = 90
def _dt(ts: Any) -> datetime:
    if isinstance(ts, datetime): return ts.astimezone(timezone.utc)
    return datetime.fromtimestamp(float(ts), tz=timezone.utc)
def _field(row: Any, name: str, default=None):
    if isinstance(row, dict): return row.get(name, default)
    names = getattr(getattr(row, "dtype", None), "names", None) or ()
    return row[name] if name in names else default
def closed_m1_bars(mt5: Any, symbol: str, now_utc: datetime | None = None, count: int = 2000, source: str = "MT5") -> list[dict]:
    now_utc = (now_utc or datetime.now(timezone.utc)).astimezone(timezone.utc)
    rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M1, 1, count)
    if rates is None: return []
    out=[]
    for row in rates:
        t=_dt(_field(row,"time"))
        if t + timedelta(minutes=1) <= now_utc:
            out.append({"symbol":symbol,"timestamp_utc":t,"open":float(_field(row,"open")),"high":float(_field(row,"high")),"low":float(_field(row,"low")),"close":float(_field(row,"close")),"tick_volume":_field(row,"tick_volume"),"real_volume":_field(row,"real_volume"),"spread":_field(row,"spread"),"source":source})
    return sorted(out,key=lambda x:x["timestamp_utc"])
def collect_once(config: CollectorConfig, mt5: Any, owner_id: str | None = None, now_utc: datetime | None = None) -> dict:
    migrate(config.db_path)
    owner=acquire_lease(config.lease_name,config.symbol,config.db_path,owner_id,config.lease_ttl_seconds)
    if not owner: return {"status":"LEASE_OCUPADA","inserted":0}
    try:
        bars=closed_m1_bars(mt5,config.symbol,now_utc,source=config.source)
        inserted=insert_m1_bars(bars,config.db_path)
        heartbeat(config.lease_name,config.symbol,owner,config.db_path,config.lease_ttl_seconds)
        return {"status":"OK","inserted":inserted,"latest":latest_m1_timestamp(config.symbol,config.db_path)}
    finally: release_lease(config.lease_name,config.symbol,owner,config.db_path)
def run_worker(config: CollectorConfig, mt5: Any, stop_event: Event | None = None, max_cycles: int | None = None) -> None:
    migrate(config.db_path)
    owner=acquire_lease(config.lease_name,config.symbol,config.db_path,ttl_seconds=config.lease_ttl_seconds)
    if not owner: raise RuntimeError("Outro coletor já possui o lease")
    stop_event=stop_event or Event(); cycles=0
    try:
        while not stop_event.is_set() and (max_cycles is None or cycles < max_cycles):
            bars=closed_m1_bars(mt5,config.symbol,datetime.now(timezone.utc),source=config.source)
            insert_m1_bars(bars,config.db_path)
            if not heartbeat(config.lease_name,config.symbol,owner,config.db_path,config.lease_ttl_seconds): raise RuntimeError("Lease perdido durante a coleta")
            cycles += 1
            if max_cycles is None: stop_event.wait(max(1,config.poll_seconds))
    finally: release_lease(config.lease_name,config.symbol,owner,config.db_path)
def main() -> int:
    parser=argparse.ArgumentParser(description="Coletor M1 fechado do PO3 Copilot")
    parser.add_argument("--symbol",default=os.getenv("MT5_SYMBOL","WINV26")); parser.add_argument("--db",default="data/po3_learning.sqlite"); parser.add_argument("--terminal",default=os.getenv("MT5_TERMINAL_PATH")); parser.add_argument("--poll-seconds",type=int,default=60)
    args=parser.parse_args()
    try: import MetaTrader5 as mt5
    except ImportError:
        print("MetaTrader5 não está disponível neste ambiente.",flush=True); return 2
    ok=mt5.initialize(path=args.terminal) if args.terminal else mt5.initialize()
    if not ok:
        print("Não foi possível conectar ao terminal MT5.",flush=True); return 3
    stop=Event()
    def request_stop(_signum,_frame): stop.set()
    signal.signal(signal.SIGINT,request_stop); signal.signal(signal.SIGTERM,request_stop)
    try: run_worker(CollectorConfig(symbol=args.symbol,db_path=args.db,terminal_path=args.terminal,poll_seconds=args.poll_seconds),mt5,stop)
    finally: mt5.shutdown()
    return 0
if __name__=="__main__": raise SystemExit(main())
