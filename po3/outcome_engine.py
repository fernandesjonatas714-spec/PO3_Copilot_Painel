"""Outcomes causais: uma barra M1 é identificada pelo horário de abertura."""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from po3.storage.market_repository import list_states,get_m1_range,upsert_outcome
HORIZONS={"5m":5,"15m":15,"30m":30,"60m":60}
def _time(value):
    if isinstance(value,datetime): return value.astimezone(timezone.utc)
    return datetime.fromisoformat(str(value).replace("Z","+00:00")).astimezone(timezone.utc)
def _iso(value): return _time(value).isoformat()
def calculate_outcomes(*,state_id:int,symbol:str,cutoff_at_utc:datetime,start_price:float,bars:list[dict],session_close:datetime|None=None,now_utc:datetime|None=None)->list[dict]:
    cutoff=_time(cutoff_at_utc); now=_time(now_utc or datetime.now(timezone.utc)); result=[]
    targets={k:cutoff+timedelta(minutes=m) for k,m in HORIZONS.items()}
    if session_close: targets["SESSION_CLOSE"]=_time(session_close)
    for code,target in targets.items():
        # A barra com open_time T fecha em T+1m. Para target 10:05,
        # entram 10:00..10:04; a barra 10:05 pertence ao horizonte seguinte.
        eligible=[b for b in bars if cutoff<=_time(b["timestamp_utc"])<target and _time(b["timestamp_utc"])+timedelta(minutes=1)<=now]
        terminal_bar=[b for b in eligible if _time(b["timestamp_utc"])+timedelta(minutes=1)==target]
        if target>now: status="PENDENTE"
        elif terminal_bar: status="DISPONIVEL"
        elif eligible: status="PENDENTE_DADOS"
        else: status="MERCADO_FECHADO"
        last=terminal_bar[-1] if terminal_bar else None
        high=max((float(b["high"]) for b in eligible),default=None); low=min((float(b["low"]) for b in eligible),default=None); future=float(last["close"]) if last else None
        result.append({"market_state_id":state_id,"symbol":symbol,"horizon_code":code,"target_at_utc":_iso(target),"observed_at_utc":_iso(now) if last else None,"start_price":float(start_price),"future_price":future,"future_high":high,"future_low":low,"high_delta":high-float(start_price) if high is not None else None,"low_delta":low-float(start_price) if low is not None else None,"absolute_change":future-float(start_price) if future is not None else None,"percentage_change":(future-float(start_price))/float(start_price)*100 if future is not None and start_price else None,"candles_observed":len(eligible),"status":status})
    return result
def process_pending_outcomes(db_path:str,*,symbol:str|None=None,now_utc:datetime|None=None)->int:
    now=_time(now_utc or datetime.now(timezone.utc)); processed=0
    import json
    for row in list_states(db_path,symbol):
        state=json.loads(row["state_json"]); start=state.get("preco_atual")
        if start is None: continue
        bars=get_m1_range(row["symbol"],_time(row["cutoff_at_utc"]),now,db_path)
        for outcome in calculate_outcomes(state_id=int(row["id"]),symbol=row["symbol"],cutoff_at_utc=_time(row["cutoff_at_utc"]),start_price=float(start),bars=bars,now_utc=now):
            upsert_outcome(outcome,db_path); processed+=1
    return processed
