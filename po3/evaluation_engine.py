"""Métricas descritivas e calibração; não altera decisões de produção."""
from __future__ import annotations
def direction_match(bias:str|None, change:float|None)->bool|None:
    if not bias or change is None or bias.lower() in {"neutro","neutral"}: return None
    b=bias.lower(); return (change>0)==("compr" in b or "alta" in b)
def summarize(records:list[dict])->dict:
    checked=[r for r in records if r.get("acerto") is not None]
    return {"total":len(records),"avaliados":len(checked),"acertos":sum(bool(r["acerto"]) for r in checked),"taxa_acerto":(sum(bool(r["acerto"]) for r in checked)/len(checked) if checked else None),"pendentes":sum(r.get("status")=="PENDENTE" for r in records)}
def calibration_buckets(records:list[dict])->dict:
    out={"Alta":[],"Média":[],"Baixa":[]}
    for r in records:
        c=r.get("confianca")
        if c in out: out[c].append(r)
    return {k:summarize(v) for k,v in out.items()}
