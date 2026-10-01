"""Detecção descritiva de mudança de distribuição."""
def compare(reference:list[float], current:list[float])->dict:
    avg=lambda xs:sum(xs)/len(xs) if xs else None
    a,b=avg(reference),avg(current)
    return {"media_referencia":a,"media_atual":b,"drift":(b-a if a is not None and b is not None else None)}
