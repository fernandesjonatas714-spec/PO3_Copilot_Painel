"""Congelamento de MarketState com corte causal."""
from __future__ import annotations
from datetime import datetime, timezone
from po3.decision_engine.market_state import build_market_state
from po3.storage.market_repository import insert_market_state
def freeze_market_state(snapshot, context:dict, *, cutoff_at_utc:datetime, db_path:str, symbol:str)->int:
    cutoff=cutoff_at_utc.astimezone(timezone.utc)
    state=build_market_state(snapshot,context)
    payload={"ativo":state.ativo,"timestamp":state.timestamp,"preco_atual":state.preco_atual,"tecnico":state.tecnico,"mercado_domestico":state.mercado_domestico,"mercado_externo":state.mercado_externo,"calendario":state.calendario,"noticias":state.noticias,"fontes":state.fontes,"qualidade_dados":state.qualidade_dados,"snapshot":state.snapshot,"cutoff_at_utc":cutoff.isoformat()}
    return insert_market_state(payload,db_path,cutoff_at_utc=cutoff,symbol=symbol,sources=context.get("fontes") if isinstance(context,dict) else {})
