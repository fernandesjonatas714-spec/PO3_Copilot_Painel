"""Congelamento de MarketState com corte causal."""
from __future__ import annotations
from copy import deepcopy
from dataclasses import is_dataclass, asdict
from datetime import datetime, timezone
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
        filtered[timeframe]=[row for row in rows if row.get("time") is not None and _utc(row["time"])<=cutoff]
    frozen.bars=filtered
    return frozen

def freeze_market_state(snapshot,context:dict,*,cutoff_at_utc:datetime,db_path:str,symbol:str)->int:
    cutoff=_utc(cutoff_at_utc); frozen=_filter_snapshot(snapshot,cutoff); state=build_market_state(frozen,context)
    payload=_json_safe({"ativo":state.ativo,"timestamp":state.timestamp,"preco_atual":state.preco_atual,"tecnico":state.tecnico,"mercado_domestico":state.mercado_domestico,"mercado_externo":state.mercado_externo,"calendario":state.calendario,"noticias":state.noticias,"fontes":state.fontes,"qualidade_dados":state.qualidade_dados,"snapshot":state.snapshot,"cutoff_at_utc":cutoff.isoformat(),"captured_at_utc":datetime.now(timezone.utc).isoformat()})
    return insert_market_state(payload,db_path,cutoff_at_utc=cutoff,symbol=symbol,sources=_json_safe(context.get("fontes",{})) if isinstance(context,dict) else {})
