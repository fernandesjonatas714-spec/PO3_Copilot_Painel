"""Métricas simples de estabilidade, sem modificar produção."""
def summarize(values:list[str])->dict:
    if not values:return {"total":0,"mudancas":0,"estavel":True}
    changes=sum(a!=b for a,b in zip(values,values[1:]))
    return {"total":len(values),"mudancas":changes,"estavel":changes==0}
