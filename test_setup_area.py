"""Teste da regra esclarecida: confirmação M1 integralmente dentro da área M5."""
import csv
import json
import hashlib
from collections import Counter
from pathlib import Path
from statistical_audit import OUT, local, simulate, stats

def newborn(bars, seconds):
    if len(bars)<3 or any(b['time']-a['time']!=seconds for a,b in zip(bars[-3:],bars[-2:])):
        return []
    a,base,c=bars[-3:]; born=[]
    if c['low']>a['high']:
        born.append(('FVG',1,a['high'],c['low'],a['time'],c['time']+seconds))
    elif c['high']<a['low']:
        born.append(('FVG',-1,c['high'],a['low'],a['time'],c['time']+seconds))
    typical=max(sum(abs(b['close']-b['open']) for b in bars)/len(bars),1)
    d=1 if c['close']>c['open'] else -1
    if (base['close']-base['open'])*d<0 and abs(c['close']-c['open'])>=1.5*max(abs(base['close']-base['open']),typical):
        born.append(('OB',d,base['low'],base['high'],base['time'],c['time']+seconds))
    return born

def invalid(z,close):
    return close<z[2] if z[1]==1 else close>z[3]

def matches(h,l):
    return l[1]==h[1] and l[4]>=h[5] and l[5]>h[5] and h[2]<=l[2]<l[3]<=h[3]

def generate(m1,m5):
    k=0;active=[];out=[];counts=Counter()
    for i,b in enumerate(m1):
        now=b['time']+60
        while k<len(m5) and m5[k]['time']+300<=now:
            x=m5[k]
            if k and x['time']-m5[k-1]['time']!=300:
                counts['zonas_descartadas_por_lacuna_M5']+=len(active);active=[]
            active=[(z,idx) for z,idx in active if not invalid(z,x['close']) and k-idx<399]
            if k>=398:
                active.extend((z,k) for z in newborn(m5[max(0,k-398):k+1],300))
            k+=1
        if i<1198 or k<399:continue
        # Informação de um M5 parcial após lacuna não é reconstruível.
        if i and b['time']-m1[i-1]['time']!=60:
            counts['zonas_descartadas_por_lacuna_M1']+=len(active);active=[]
            continue
        lower=newborn(m1[max(0,i-1198):i+1],60)
        hits=[(h,l) for h,_ in active for l in lower if matches(h,l)]
        if hits:
            h,l=max(hits,key=lambda pair:(pair[0][5],pair[1][5],pair[0][0],pair[1][0]))
            out.append((i,h,l,h[0]+'+'+l[0]))
    return out,dict(counts)

def main():
    source=OUT/'candles.json'
    payload=source.read_bytes();data=json.loads(payload)
    q=json.loads((OUT/'resultado.json').read_text())['quality']
    assert hashlib.sha256(payload).hexdigest()==q['data_sha256']
    signals,quality=generate(data['M1'],data['M5'])
    trades,skipped=simulate(data['M1'],signals,q['tick'],q['point'],2)
    result=dict(rule='M1 inteiro dentro M5; formação M1 inicia após confirmação M5; invalidação por fechamento M5 contrário',quality=q,signals=len(signals),gap_policy=quality,skipped=skipped,gross=stats(trades),cost_scenarios=[stats(trades,q['tick']*n) for n in (1,2,4)])
    dest=OUT/'regra_area_M5_2R'
    dest.mkdir(exist_ok=True)
    with (dest/'operacoes.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(trades[0]) if trades else ['signal']);w.writeheader();w.writerows(trades)
    (dest/'resultado.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    g=result['gross'];exits=g['exits'];censored=exits.get('fim_sessao_ou_lacuna',0)+exits.get('fim_amostra',0)
    text=f'''# Novo teste — confirmação M1 na área M5, alvo 2R

Dados congelados da coleta anterior: {q['M1']} candles M1 e {q['M5']} M5, {q['days']} datas, {q['intraday_gaps']} lacunas intradiárias. Período: {q['start']} a {q['end']}.

## Regra testada

Primeiro forma FVG ou OB no M5. Depois começa e termina a formação de OB/FVG no M1, na mesma direção, com **toda a zona M1 dentro da zona M5**. Todas as quatro combinações são aceitas. Não exige um toque separado além dessa formação dentro da área.

O toque não elimina o M5. Premissa de invalidação: fechamento M5 abaixo do limite inferior comprador ou acima do superior vendedor. Validade máxima: 399 candles M5. As zonas são fixadas no momento da formação, com média de corpos somente do passado disponível. Formação de OB exige impulso de pelo menos 1,5 vez o corpo-base e o corpo médio; FVG usa três candles.

Formações não atravessam lacunas. Ao encontrar lacuna M1/M5, o contexto anterior é descartado por não ser possível verificar sua validade. Aquecimento de 399 candles M5 e 1.199 M1. Em empate, usa a zona M5 mais recentemente confirmada. Uma posição por vez e uma operação por identidade de zona M5; novas regiões não são proibidas para sempre por sobreposição antiga.

Entrada na abertura do próximo minuto consecutivo à confirmação; stop dois pontos mínimos além do M5, arredondado para fora ao tick; alvo **duas vezes o risco**. Stop primeiro se alvo/stop tocarem no mesmo candle. Gaps adversos usam a abertura pior. São premissas de simulação, não garantia de execução no fechamento do sinal.

## Resultado

| Medida | Valor |
|---|---:|
| Sinais | {len(signals)} |
| Operações | {g['n']} |
| Positivas / negativas / zero | {g['wins']} / {g['losses']} / {g['n']-g['wins']-g['losses']} |
| Alvos 2R / stops | {exits.get('alvo',0)} / {exits.get('stop',0)} |
| Saídas truncadas | {censored} |
| Resultado bruto incluindo marcações truncadas | {g['total_r']:+.2f}R |
| Média bruta | {g['mean_r'] if g['mean_r'] is not None else 'indisponível'}R |
| Maior drawdown em R | {g['max_drawdown_r']:.2f}R |
| Maior sequência de perdas | {g['max_loss_streak']} |

'''
    for s in result['cost_scenarios']:
        text+=f"- Fricção hipotética total de {s['drag_points_per_trade']:.0f} pontos/operação: {s['total_r']:+.2f}R.\n"
    text+='''
## Limitação e conclusão

Saídas truncadas são marcadas no último fechamento disponível antes de lacuna/fim de sessão/amostra. Não são execuções comprovadas. A taxa de operações positivas inclui essas marcações e não equivale à taxa de atingir 2R. Custos são cenários hipotéticos, não tarifas comprovadas da Clear. Resultados permanecem exploratórios: dados incompletos e premissas ainda exigem validação fora da amostra. Não há fundamento para declarar vantagem estatística comprovada.

O indicador instalado não foi alterado. Este teste implementa a regra esclarecida, portanto não é reprodução da lógica antiga. Entrada no próximo open, contenção integral, invalidação por fechamento, expiração e tratamento de lacunas estão explicitados para permitir revisão.

Arquivos: `operacoes.csv`, `resultado.json`. Código: `test_setup_area.py`. Base e hash preservados no diretório superior. Documentação da coleta: https://www.mql5.com/en/docs/python_metatrader5/mt5copyratesfrompos_py . Não há consulta de conta ou envio de ordens.
'''
    (dest/'RELATORIO.md').write_text(text,encoding='utf-8')
    print(json.dumps(result,indent=2))

if __name__=='__main__':main()
