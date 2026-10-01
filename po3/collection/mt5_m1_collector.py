from __future__ import annotations
import argparse, os, signal
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from threading import Event
from typing import Any, Callable
from po3.storage.migrations import migrate
from po3.storage.market_repository import acquire_lease, heartbeat, release_lease, insert_m1_bars, latest_m1_timestamp, list_states, update_runtime_status, get_v2_m1_bar
from po3.outcome_engine import process_pending_outcomes
from po3.market_state_store import freeze_market_state
from po3.collection.freshness import assess_freshness
from po3.collection.time_alignment import Mt5TimeAlignmentDetector

@dataclass(frozen=True)
class CollectorConfig:
    symbol: str
    db_path: str
    terminal_path: str | None = None
    source: str = "MT5"
    lease_name: str = "po3-m1"
    poll_seconds: int = 15
    lease_ttl_seconds: int = 90
    state_interval_minutes: int = 5
    max_feed_lag_seconds: int = 120

def _dt(ts: Any) -> datetime:
    if isinstance(ts, datetime): return ts.astimezone(timezone.utc)
    return datetime.fromtimestamp(float(ts),tz=timezone.utc)
def _field(row: Any,name: str,default=None):
    if isinstance(row,dict): return row.get(name,default)
    names=getattr(getattr(row,"dtype",None),"names",None) or ()
    return row[name] if name in names else default
def closed_m1_bars(mt5: Any,symbol: str,now_utc: datetime|None=None,count: int=2000,source: str="MT5",
                    normalize_timestamp: Callable[[float], datetime] | None = None,
                    time_offset_seconds: float | None = None)->list[dict]:
    now_utc=(now_utc or datetime.now(timezone.utc)).astimezone(timezone.utc)
    rates=mt5.copy_rates_from_pos(symbol,mt5.TIMEFRAME_M1,1,count)
    if rates is None:return []
    out=[]
    for row in rates:
        raw_time=float(_field(row,"time"))
        t=normalize_timestamp(raw_time) if normalize_timestamp else _dt(raw_time)
        if t+timedelta(minutes=1)<=now_utc:
            out.append({"symbol":symbol,"timestamp_utc":t,"source_timestamp_raw":int(raw_time),
                        "time_offset_seconds":time_offset_seconds,"open":float(_field(row,"open")),
                        "high":float(_field(row,"high")),"low":float(_field(row,"low")),
                        "close":float(_field(row,"close")),"tick_volume":_field(row,"tick_volume"),
                        "real_volume":_field(row,"real_volume"),"spread":_field(row,"spread"),"source":source})
    return sorted(out,key=lambda x:x["timestamp_utc"])
def _slot(value:datetime,interval:int=5)->datetime:
    value=value.astimezone(timezone.utc).replace(second=0,microsecond=0)
    return value.replace(minute=(value.minute//interval)*interval)
def wait_for_stop(stop_event: Event, stop_file: str | None, poll_seconds: float) -> bool:
    """Aguarda o próximo ciclo sem deixar o stop file adormecer o worker."""
    deadline = datetime.now(timezone.utc).timestamp() + max(0.0, float(poll_seconds))
    while True:
        if stop_event.is_set():
            return True
        if stop_file and os.path.exists(stop_file):
            stop_event.set()
            return True
        remaining = deadline - datetime.now(timezone.utc).timestamp()
        if remaining <= 0:
            return stop_event.is_set()
        stop_event.wait(min(0.5, remaining))
def _tick_time(mt5:Any,symbol:str)->datetime|None:
    try:
        tick=mt5.symbol_info_tick(symbol)
        value=getattr(tick,"time",None) if tick is not None else None
        return _dt(value) if value else None
    except Exception:return None
def _record_freshness(config,bars,alignment,now):
    last=max((b["timestamp_utc"] for b in bars),default=None)
    aligned=alignment.last
    if not alignment.usable:
        if aligned.feed_liveness_status == "STALE":
            status, detail = "MT5_FEED_REALLY_STALE", aligned.detail
        elif aligned.clock_alignment_status == "UNSTABLE_OFFSET":
            status, detail = "MT5_CLOCK_UNSTABLE", aligned.detail
        else:
            status, detail = "MT5_ALIGNMENT_UNAVAILABLE", aligned.detail
        update_runtime_status(config.symbol,config.db_path,status=status,feed_lag_seconds=None,
            last_closed_at_utc=last.isoformat() if last else None,
            last_tick_at_utc=aligned.normalized_tick_at_utc.isoformat() if aligned.normalized_tick_at_utc else None,
            detail=detail,feed_liveness_status=aligned.feed_liveness_status,
            clock_alignment_status=aligned.clock_alignment_status,
            detected_offset_seconds=aligned.detected_offset_seconds,
            normalized_tick_at_utc=aligned.normalized_tick_at_utc.isoformat() if aligned.normalized_tick_at_utc else None)
        return None
    freshness=assess_freshness(last_closed_at_utc=last,now_utc=now,
        last_tick_at_utc=aligned.normalized_tick_at_utc,max_lag_seconds=config.max_feed_lag_seconds)
    update_runtime_status(config.symbol,config.db_path,status=freshness.status,
        feed_lag_seconds=freshness.feed_lag_seconds,last_closed_at_utc=last.isoformat() if last else None,
        last_tick_at_utc=aligned.normalized_tick_at_utc.isoformat() if aligned.normalized_tick_at_utc else None,
        detail=f"{freshness.detail} offset={aligned.detected_offset_seconds:.3f}s",
        feed_liveness_status=aligned.feed_liveness_status,
        clock_alignment_status=aligned.clock_alignment_status,
        detected_offset_seconds=aligned.detected_offset_seconds,
        normalized_tick_at_utc=aligned.normalized_tick_at_utc.isoformat() if aligned.normalized_tick_at_utc else None)
    return freshness

def collect_once(config:CollectorConfig,mt5:Any,owner_id:str|None=None,now_utc:datetime|None=None,
                alignment_detector: Mt5TimeAlignmentDetector | None = None)->dict:
    migrate(config.db_path); owner=acquire_lease(config.lease_name,config.symbol,config.db_path,owner_id,config.lease_ttl_seconds)
    if not owner:return {"status":"LEASE_OCUPADA","inserted":0}
    try:
        now=now_utc or datetime.now(timezone.utc)
        detector=alignment_detector or Mt5TimeAlignmentDetector()
        tick_fn=getattr(mt5,"symbol_info_tick",None)
        tick=tick_fn(config.symbol) if callable(tick_fn) else None
        alignment=detector.observe(raw_tick_time=getattr(tick,"time",None),
            raw_tick_time_msc=getattr(tick,"time_msc",None),observed_at_system_utc=now)
        bars=closed_m1_bars(mt5,config.symbol,now,source=config.source,
            normalize_timestamp=detector.normalize if detector.usable else None,
            time_offset_seconds=alignment.detected_offset_seconds) if detector.usable else []
        inserted=insert_m1_bars(bars,config.db_path)
        freshness=_record_freshness(config,bars,detector,now)
        heartbeat(config.lease_name,config.symbol,owner,config.db_path,config.lease_ttl_seconds)
        return {"status":"OK" if freshness else alignment.status,"inserted":inserted,
                "latest":latest_m1_timestamp(config.symbol,config.db_path),
                "freshness":freshness.status if freshness else None,
                "feed_lag_seconds":freshness.feed_lag_seconds if freshness else None}
    finally:release_lease(config.lease_name,config.symbol,owner,config.db_path)
def _default_snapshot_provider(config,cutoff,alignment_detector,mt5_session=None):
    from po3.mt5_reader import read_snapshot_at_cutoff
    if not alignment_detector.usable:
        raise RuntimeError("MT5_ALIGNMENT_UNAVAILABLE: snapshot causal sem alinhamento validado")
    return read_snapshot_at_cutoff(config.terminal_path or "",config.symbol,cutoff,
                                   normalize_timestamp=alignment_detector.normalize,
                                   mt5_session=mt5_session,manage_connection=mt5_session is None),{}
def run_worker(config:CollectorConfig,mt5:Any,stop_event:Event|None=None,max_cycles:int|None=None,snapshot_provider:Callable|None=None)->None:
    migrate(config.db_path); owner=acquire_lease(config.lease_name,config.symbol,config.db_path,ttl_seconds=config.lease_ttl_seconds)
    if not owner:raise RuntimeError("Outro coletor possui o lease")
    stop_event=stop_event or Event(); cycles=0
    alignment_detector=Mt5TimeAlignmentDetector()
    provider=snapshot_provider or (lambda cutoff:_default_snapshot_provider(config,cutoff,alignment_detector,mt5))
    existing=list_states(config.db_path,config.symbol)
    last_slot=_slot(datetime.fromisoformat(existing[-1]["cutoff_at_utc"]) if existing else datetime(1970,1,1,tzinfo=timezone.utc),config.state_interval_minutes) if existing else None
    try:
        while not stop_event.is_set() and (max_cycles is None or cycles<max_cycles):
            stop_file = os.getenv("PO3_WORKER_STOP_FILE")
            if stop_file and os.path.exists(stop_file):
                stop_event.set()
                break
            now=datetime.now(timezone.utc)
            try:
                tick_fn=getattr(mt5,"symbol_info_tick",None)
                tick=tick_fn(config.symbol) if callable(tick_fn) else None
                alignment=alignment_detector.observe(raw_tick_time=getattr(tick,"time",None),
                    raw_tick_time_msc=getattr(tick,"time_msc",None),observed_at_system_utc=now)
                bars=closed_m1_bars(mt5,config.symbol,now,source=config.source,
                    normalize_timestamp=alignment_detector.normalize if alignment_detector.usable else None,
                    time_offset_seconds=alignment.detected_offset_seconds) if alignment_detector.usable else []
                insert_m1_bars(bars,config.db_path)
                freshness=_record_freshness(config,bars,alignment_detector,now)
                process_pending_outcomes(config.db_path,symbol=config.symbol,now_utc=now)
                slot=_slot(now,config.state_interval_minutes)
                if freshness is not None and freshness.status=="ATUAL" and (last_slot is None or slot>last_slot):
                    snapshot,context=provider(slot)
                    expected_start=slot-timedelta(minutes=1)
                    # O contrato V2 exige a barra canônica exatamente em cutoff-1m.
                    # Registros legados sem metadata nunca podem ser usados aqui.
                    start_bar=get_v2_m1_bar(config.symbol,expected_start,config.db_path)
                    start_price=float(start_bar["close"]) if start_bar is not None else None
                    freeze_market_state(snapshot,context or {},cutoff_at_utc=slot,db_path=config.db_path,symbol=config.symbol,
                                        start_price=start_price,start_bar_open_time=expected_start,
                                        start_price_status="DISPONIVEL" if start_bar is not None else "INDISPONIVEL")
                    last_slot=slot; process_pending_outcomes(config.db_path,symbol=config.symbol,now_utc=now)
            except Exception as exc:
                print(f"Worker factual: {type(exc).__name__}",flush=True)
            if not heartbeat(config.lease_name,config.symbol,owner,config.db_path,config.lease_ttl_seconds):raise RuntimeError("Lease perdido durante a coleta")
            cycles+=1
            if max_cycles is None:
                wait_for_stop(stop_event, os.getenv("PO3_WORKER_STOP_FILE"), max(1, config.poll_seconds))
    finally:release_lease(config.lease_name,config.symbol,owner,config.db_path)
def main()->int:
    parser=argparse.ArgumentParser(description="Worker M1, MarketState e outcomes do PO3 Copilot")
    parser.add_argument("--symbol",default=os.getenv("MT5_SYMBOL","WINV26"));parser.add_argument("--db",default="data/po3_learning.sqlite");parser.add_argument("--terminal",default=os.getenv("MT5_TERMINAL_PATH"));parser.add_argument("--poll-seconds",type=int,default=15);parser.add_argument("--max-feed-lag-seconds",type=int,default=int(os.getenv("MT5_MAX_FEED_LAG_SECONDS","120")))
    args=parser.parse_args()
    try:import MetaTrader5 as mt5
    except ImportError:print("MetaTrader5 nao esta disponivel neste ambiente.",flush=True);return 2
    ok=mt5.initialize(path=args.terminal) if args.terminal else mt5.initialize()
    if not ok:print("Nao foi possivel conectar ao terminal MT5.",flush=True);return 3
    stop=Event()
    def request_stop(_signum,_frame):stop.set()
    signal.signal(signal.SIGINT,request_stop);signal.signal(signal.SIGTERM,request_stop)
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, request_stop)
    try:run_worker(CollectorConfig(symbol=args.symbol,db_path=args.db,terminal_path=args.terminal,poll_seconds=args.poll_seconds,max_feed_lag_seconds=args.max_feed_lag_seconds),mt5,stop)
    finally:mt5.shutdown()
    return 0
if __name__=="__main__":raise SystemExit(main())
