"""Relatórios de calibração para revisão humana."""
def report(records:list[dict])->dict:
    by={}
    for row in records:
        key=row.get("confianca","Não informada"); by.setdefault(key,[]).append(row)
    return {k:{"total":len(v),"acertos":sum(bool(x.get("acerto")) for x in v)} for k,v in by.items()}
