"""Congelamento de MarketState com corte causal."""
from __future__ import annotations
from copy import deepcopy
from dataclasses import is_dataclass, asdict
from datetime import datetime, timedelta, timezone
from collections.abc import Mapping
from po3.decision_engine.market_state import build_market_state
from po3.storage.market_repository import insert_market_state

def _utc(value):
    if isinstance(value,datetime): return value.astimezone(timezone.utc)
    return datetime.fromisoformat(str(value).replace("Z","+00:00")).astimezone(timezone.utc)

def _json_safe(value, seen=None):
    seen=set() if seen is None else seen
    if value is None or isinstance(value,(str,int,float,bool)): return value
    if isinstance(value,datetime): return value.isoformat()
    marker=id(value)
    if marker in seen: return None
    seen.add(marker)
    if is_dataclass(value): return _json_safe(asdict(value),seen)
    if isinstance(value,Mapping): return {str(k):_json_safe(v,seen) for k,v in value.items()}
    if isinstance(value,(list,tuple,set)): return [_json_safe(v,seen) for v in value]
    if hasattr(value,"__dict__"): return _json_safe(vars(value),seen)
    return str(value)

def _filter_snapshot(snapshot, cutoff):
    frozen=deepcopy(snapshot); frozen.as_of=cutoff; filtered={}
    for timeframe,rows in (getattr(snapshot,"bars",{}) or {}).items():
        filtered[timeframe]=[row for row in rows if row.get("time") is not None and _utc(row["time"])<cutoff]
    frozen.bars=filtered
    return frozen

def freeze_market_state(snapshot,context:dict,*,cutoff_at_utc:datetime,db_path:str,symbol:str,
                        start_price:float|None=None,start_bar_open_time:datetime|None=None,
                        start_price_status:str|None=None)->int:
    cutoff=_utc(cutoff_at_utc); expected_start=cutoff-timedelta(minutes=1)
    frozen=_filter_snapshot(snapshot,cutoff); state=build_market_state(frozen,context)
    # V2 contract: start price is only CLOSE of the exact previous M1 bar.
    supplied_start_time = _utc(start_bar_open_time) if start_bar_open_time is not None else expected_start
    if supplied_start_time != expected_start:
        raise ValueError("INCONSISTENCIA_START_BAR: start_bar_open_time deve ser cutoff_at_utc - 1 minuto")
    status=start_price_status or ("DISPONIVEL" if start_price is not None else "INDISPONIVEL")
    if status == "DISPONIVEL" and start_price is None:
        raise ValueError("INCONSISTENCIA_START_PRICE: DISPONIVEL exige start_price")
    if status == "INDISPONIVEL":
        start_price = None
    start_time=expected_start
    payload=_json_safe({"ativo":state.ativo,"timestamp":state.timestamp,"preco_atual":start_price,
        "start_price":start_price,"start_bar_open_time":start_time.isoformat(),"start_price_status":status,
        "tecnico":state.tecnico,"mercado_domestico":state.mercado_domestico,"mercado_externo":state.mercado_externo,
        "calendario":state.calendario,"noticias":state.noticias,"fontes":state.fontes,
        "qualidade_dados":state.qualidade_dados,"snapshot":state.snapshot,"cutoff_at_utc":cutoff.isoformat(),
        "captured_at_utc":datetime.now(timezone.utc).isoformat()})
    return insert_market_state(payload,db_path,cutoff_at_utc=cutoff,symbol=symbol,sources=_json_safe(context.get("fontes",{})) if isinstance(context,dict) else {})
