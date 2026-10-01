"""Freshness gate factual para o feed M1."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo
BRT=ZoneInfo("America/Sao_Paulo")
@dataclass(frozen=True)
class FeedFreshness:
    status:str
    feed_lag_seconds:float|None
    last_closed_at_utc:datetime|None
    last_tick_at_utc:datetime|None
    market_active:bool
    detail:str
def is_market_active(now_utc:datetime)->bool:
    local=now_utc.astimezone(BRT)
    if local.weekday()>=5: return False
    return time(9,0)<=local.time()<=time(18,30)
def _utc(value):
    if value is None:return None
    if isinstance(value,datetime):return value.astimezone(timezone.utc)
    return datetime.fromtimestamp(float(value),timezone.utc)
def assess_freshness(*,last_closed_at_utc:datetime|None,now_utc:datetime|None=None,last_tick_at_utc:datetime|None=None,max_lag_seconds:int=120,market_active:bool|None=None)->FeedFreshness:
    now=(now_utc or datetime.now(timezone.utc)).astimezone(timezone.utc)
    closed=_utc(last_closed_at_utc); tick=_utc(last_tick_at_utc)
    active=is_market_active(now) if market_active is None else market_active
    lag=(now-closed).total_seconds() if closed else None
    if not active:
        return FeedFreshness("SEM_NOVO_CANDLE_MERCADO_FECHADO",lag,closed,tick,False,"Sem novo candle esperado fora da sessão.")
    if closed is None or lag is None or lag>max_lag_seconds:
        return FeedFreshness("MT5_DATA_STALE",lag,closed,tick,True,"Feed M1 atrasado durante sessão ativa.")
    return FeedFreshness("ATUAL",lag,closed,tick,True,"Último candle M1 fechado dentro do limite.")
