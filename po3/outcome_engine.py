"""Cálculo causal de resultados futuros, sem ordens ou P/L."""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
HORIZONS={"5m":5,"15m":15,"30m":30,"60m":60}
def _iso(v): return v if isinstance(v,str) else v.astimezone(timezone.utc).isoformat()
def calculate_outcomes(*, state_id:int, symbol:str, cutoff_at_utc:datetime, start_price:float, bars:list[dict], session_close:datetime|None=None)->list[dict]:
    cutoff=cutoff_at_utc.astimezone(timezone.utc); result=[]
    targets={k:cutoff+timedelta(minutes=m) for k,m in HORIZONS.items()}
    if session_close: targets["SESSION_CLOSE"]=session_close.astimezone(timezone.utc)
    for code,target in targets.items():
        eligible=[b for b in bars if cutoff < (b["timestamp_utc"] if isinstance(b["timestamp_utc"],datetime) else datetime.fromisoformat(b["timestamp_utc"]).astimezone(timezone.utc)) <= target]
        exact=[b for b in bars if (b["timestamp_utc"] if isinstance(b["timestamp_utc"],datetime) else datetime.fromisoformat(b["timestamp_utc"]).astimezone(timezone.utc)) >= target]
        status="DISPONIVEL" if exact else ("MERCADO_FECHADO" if not eligible else "PENDENTE")
        last=exact[0] if exact else None
        high=max((float(b["high"]) for b in eligible),default=None); low=min((float(b["low"]) for b in eligible),default=None)
        future=float(last["close"]) if last else None
        result.append({"market_state_id":state_id,"symbol":symbol,"horizon_code":code,"target_at_utc":_iso(target),"observed_at_utc":_iso(datetime.now(timezone.utc)) if last else None,"start_price":float(start_price),"future_price":future,"future_high":high,"future_low":low,"high_delta":high-float(start_price) if high is not None else None,"low_delta":low-float(start_price) if low is not None else None,"absolute_change":future-float(start_price) if future is not None else None,"percentage_change":(future-float(start_price))/float(start_price)*100 if future is not None and start_price else None,"candles_observed":len(eligible),"status":status})
    return result
