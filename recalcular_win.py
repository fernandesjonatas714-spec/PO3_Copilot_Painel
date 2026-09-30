"""Nova coleta somente leitura e replay da regra M5/M1 acordada."""
import csv
import json
import hashlib
from datetime import datetime, timezone, timedelta
from pathlib import Path
import MetaTrader5 as mt5
from statistical_audit import local, simulate, stats
from test_setup_area import generate

def main():
    now=datetime.now(timezone.utc)
    dest=Path(__file__).parent/'reports'/('novo_WIN_'+now.strftime('%Y%m%d_%H%M%S'))
    if not mt5.initialize(r'C:\Program Files\Clear Investimentos MT5 Terminal\terminal64.exe',timeout=8000):
        raise RuntimeError(str(mt5.last_error()))
    frames={}
    try:
        info=mt5.symbol_info('WINV26')
        if info is None: raise RuntimeError('WINV26 indisponível')
        tick,point=float(info.trade_tick_size),float(info.point)
        if tick<=0 or point<=0: raise RuntimeError('Passo de preço inválido')
        for name,tf in [('M1',mt5.TIMEFRAME_M1),('M5',mt5.TIMEFRAME_M5)]:
            raw=mt5.copy_rates_range('WINV26',tf,now-timedelta(days=90),now)
            if raw is None or not len(raw):
                raw=mt5.copy_rates_from_pos('WINV26',tf,1,50000 if name=='M1' else 10000)
            if raw is None or not len(raw): raise RuntimeError(name+': '+str(mt5.last_error()))
            seconds=60 if name=='M1' else 300
            frames[name]=[{k:int(r[k]) if k=='time' else float(r[k]) for k in ('time','open','high','low','close','spread')} for r in raw if (now-timedelta(days=90)).timestamp()<=int(r['time']) and int(r['time'])+seconds<=now.timestamp()]
    finally: mt5.shutdown()
    for rows in frames.values():
        assert rows and all(a['time']<b['time'] for a,b in zip(rows,rows[1:]))
        assert all(b['low']<=min(b['open'],b['close'])<=max(b['open'],b['close'])<=b['high'] for b in rows)
    dest.mkdir(parents=True)
    payload=json.dumps(frames,sort_keys=True).encode()
    (dest/'candles.json').write_bytes(payload)
    m1,m5=frames['M1'],frames['M5']
    print('Coleta:',len(m1),'M1;',len(m5),'M5',flush=True)
    signals,gaps=generate(m1,m5)
    trades,skipped=simulate(m1,signals,tick,point,2)
    results={'symbol':'WINV26','collected_utc':now.isoformat(),'start':local(m1[0]['time']).isoformat(),'end':local(m1[-1]['time']).isoformat(),'M1':len(m1),'M5':len(m5),'dates':len({local(b['time']).date() for b in m1}),'intraday_gaps':sum(b['time']-a['time']!=60 and local(b['time']).date()==local(a['time']).date() for a,b in zip(m1,m1[1:])),'sha256':hashlib.sha256(payload).hexdigest(),'signals':len(signals),'gross':stats(trades),'costs':[stats(trades,tick*n) for n in (1,2,4)],'gaps':gaps,'skipped':skipped,'tick':tick,'point':point}
    for side,d in [('compras',1),('vendas',-1)]: results[side]=stats([t for t in trades if t['direction']==d])
    with (dest/'operacoes.csv').open('w',newline='',encoding='utf-8-sig') as f:
        w=csv.DictWriter(f,fieldnames=list(trades[0]) if trades else ['signal']);w.writeheader();w.writerows(trades)
    (dest/'resultado.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
    g=results['gross']
    report=f'''# Novo levantamento WINV26 — confluência M5/M1, 2R

Coleta MT5 em {now.isoformat()}. Período: {results['start']} a {results['end']}.
{len(m1)} candles M1; {len(m5)} M5; {results['dates']} datas com dados; {results['intraday_gaps']} lacunas intradiárias M1.

## Regra
FVG/OB M5 confirmado, seguido de FVG/OB M1 inteiramente dentro da área, mesma direção. Todas as quatro combinações são aceitas. Entrada no próximo minuto consecutivo, stop 2 unidades de point além do M5 arredondado para fora ao tick, alvo 2R. Uma posição por vez e uma entrada por zona M5. Sem parcial ou breakeven. Toque não invalida M5: fechamento contrário ao limite invalida. Expiração em 399 barras M5; aquecimento de 399 M5 e 1199 M1. Em lacunas o contexto é descartado. Stop primeiro quando ambos os níveis são tocados no mesmo candle. Gaps adversos executam ao preço de abertura pior.

## Resultado
| Medida | Valor |
|---|---:|
| Sinais | {len(signals)} |
| Operações | {g['n']} |
| Positivas / negativas | {g['wins']} / {g['losses']} |
| Percentual positivo | {g['win_rate']:.2%} |
| Resultado bruto | {g['total_r']:+.2f}R |
| Média por operação | {g['mean_r']}R |
| Fator de lucro em R | {g['profit_factor']} |
| Drawdown máximo | {g['max_drawdown_r']:.2f}R |
| Maior sequência de perdas | {g['max_loss_streak']} |

Saídas: {g['exits']}.
'''
    for c in results['costs']: report+=f"\n- Custo/fricção hipotética total {c['drag_points_per_trade']} pontos por operação: {c['total_r']:+.2f}R."
    report+='''

## Limites de interpretação
Teste apenas da confluência técnica, sem filtro macro, MSS, manipulação, reteste discricionário ou reprodução exata do indicador instalado. Não representa o setup completo com decisões manuais. Mesmas premissas da revisão anterior; não houve otimização para melhorar o resultado. A amostra se sobrepõe à anterior, portanto não é validação independente.
Saídas por lacuna/fim são marcações no último fechamento, não execuções comprovadas; positivas incluem essas saídas e não equivalem à taxa de atingir 2R. Ausência de barras pode ser falta de negócios ou de histórico. Custos são cenários, não tarifas verificadas. R agrega risco normalizado e não equivale a lucro em reais com quantidade fixa de contratos. Dados incompletos não sustentam promessa de rentabilidade. Histórico e hashes preservados para reprodução.
Fonte da coleta: https://www.mql5.com/en/docs/python_metatrader5/mt5copyratesrange_py
'''
    (dest/'RELATORIO.md').write_text(report,encoding='utf-8')
    print(json.dumps(results,indent=2));print('PASTA',dest)

if __name__=='__main__': main()
