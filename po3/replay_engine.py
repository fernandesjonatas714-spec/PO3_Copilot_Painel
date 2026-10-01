"""Replay offline com corte causal e sem contaminação por resultados futuros."""
from __future__ import annotations
from datetime import datetime, timezone
def replay(states:list[dict], decision_runner, *, run_at:datetime|None=None)->list[dict]:
    run_at=(run_at or datetime.now(timezone.utc)).astimezone(timezone.utc); rows=[]
    for state in states:
        payload=dict(state); payload.pop("outcomes",None); payload.pop("future_bars",None)
        result=decision_runner(payload)
        rows.append({"market_state_id":state.get("id"),"cutoff_at_utc":state.get("cutoff_at_utc"),"run_at_utc":run_at.isoformat(),"result":result})
    return rows
