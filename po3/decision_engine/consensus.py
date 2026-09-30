from __future__ import annotations

def compare(first, second):
    if not second: return {"status":"NAO_EXECUTADA","divergencias":[]}
    a={x.id_decisao:x.decisao for x in first}; b={x.id_decisao:x.decisao for x in second}
    diffs=[key for key in a if a.get(key)!=b.get(key)]
    return {"status":"DIVERGENCIA" if diffs else "CONSENSO", "divergencias":diffs}