"""Auditoria reproduzível de candles, consultas diárias e resultados censurados."""
import json, csv, hashlib
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
import MetaTrader5 as mt5
from statistical_audit import local, simulate, stats
from test_setup_area import generate

ROOT=Path(__file__).parent
SOURCE=ROOT/'reports/novo_WIN_20260908_212652'

def main():
    old=json.loads((SOURCE/'candles.json').read_text())
    meta=json.loads((SOURCE/'resultado.json').read_text())
    out=ROOT/'reports'/('auditoria_WIN_'+datetime.now().strftime('%Y%m%d_%H%M%S'))
    out.mkdir(parents=True)
    start,end=old['M1'][0]['time'],old['M1'][-1]['time']
    frames={k:{b['time']:b for b in v} for k,v in old.items()}
    logs=[]; changed=defaultdict(int); added=defaultdict(int)
    if not mt5.initialize(r'C:\Program Files\Clear Investimentos MT5 Terminal\terminal64.exe',timeout=8000): raise RuntimeError(mt5.last_error())
    try:
        for k,tf in [('M1',mt5.TIMEFRAME_M1),('M5',mt5.TIMEFRAME_M5)]:
            for day in range(start//86400*86400,end+1,86400):
                raw=mt5.copy_rates_range('WINV26',tf,day,min(day+86399,end))
                logs.append(dict(frame=k,start=day,count=None if raw is None else len(raw),error=str(mt5.last_error()) if raw is None else ''))
                if raw is None: continue
                for r in raw:
                    t=int(r['time'])
                    if not start<=t<=end:continue
                    b={key:int(r[key]) if key=='time' else float(r[key]) for key in ('time','open','high','low','close','spread')}
                    if t not in frames[k]: added[k]+=1
                    elif any(b[x]!=frames[k][t][x] for x in ('open','high','low','close')): changed[k]+=1
                    frames[k][t]=b
            print(k,'consultado',len(frames[k]),'recuperados',added[k],flush=True)
        # Sondagem de ticks de negócios em até três lacunas antigas, sem inferir cobertura de retorno vazio.
        samples=[]
        gaps=[(a,b) for a,b in zip(old['M1'],old['M1'][1:]) if b['time']-a['time']>60 and local(a['time']).date()==local(b['time']).date()]
        for a,b in (gaps[0:1]+gaps[len(gaps)//2:len(gaps)//2+1]+gaps[-1:]):
            ticks=mt5.copy_ticks_range('WINV26',a['time']+60,min(b['time']-1,a['time']+3600),mt5.COPY_TICKS_TRADE)
            samples.append(dict(start=a['time']+60,end=min(b['time']-1,a['time']+3600),ticks=None if ticks is None else len(ticks),error=str(mt5.last_error()) if ticks is None else '',note='Sondagem apenas; não usado para sintetizar candles.'))
    finally:mt5.shutdown()
    frames={k:sorted(v.values(),key=lambda x:x['time']) for k,v in frames.items()}
    payload=json.dumps(frames,sort_keys=True).encode();(out/'candles.json').write_bytes(payload)
    minutes={b['time']:b for b in frames['M1']}; checks=[]
    for b in frames['M5']:
        rows=[minutes.get(b['time']+60*i) for i in range(5)]
        if all(rows):
            values=dict(open=rows[0]['open'],high=max(x['high'] for x in rows),low=min(x['low'] for x in rows),close=rows[-1]['close'])
            status='coerente' if all(abs(values[k]-b[k])<0.001 for k in values) else 'divergente'
        else:status='M1_incompleto'
        checks.append(dict(time=b['time'],status=status))
    daily=defaultdict(lambda:dict(candles=0,gaps=0,missing_minutes=0))
    for b in frames['M1']:daily[str(local(b['time']).date())]['candles']+=1
    for a,b in zip(frames['M1'],frames['M1'][1:]):
        d=str(local(a['time']).date())
        if d==str(local(b['time']).date()) and b['time']-a['time']>60:
            daily[d]['gaps']+=1;daily[d]['missing_minutes']+=(b['time']-a['time'])//60-1
    sigs,_=generate(frames['M1'],frames['M5'])
    trades,skipped=simulate(frames['M1'],sigs,meta['tick'],meta['point'],2)
    complete=[t for t in trades if t['reason'] in ('stop','alvo')]
    censored=[t for t in trades if t['reason'] not in ('stop','alvo')]
    result=dict(added=dict(added),revised=dict(changed),queries=len(logs),failed_queries=sum(x['count'] is None for x in logs),M5_checks={s:sum(x['status']==s for x in checks) for s in ('coerente','divergente','M1_incompleto')},intraday_gaps=sum(x['gaps'] for x in daily.values()),missing_minutes_between_bars=sum(x['missing_minutes'] for x in daily.values()),tick_probes=samples,signals=len(sigs),total_candidates=len(trades),inconclusive=len(censored),observed_only=stats(complete),observed_costs=[stats(complete,n) for n in (5,10,20)],sha256=hashlib.sha256(payload).hexdigest(),skipped=skipped)
    for name,rows in [('operacoes_com_desfecho',complete),('operacoes_inconclusivas',censored),('dias',[dict(date=d,**v) for d,v in sorted(daily.items())]),('consultas',logs),('comparacao_M5',checks)]:
        with (out/(name+'.csv')).open('w',newline='',encoding='utf-8-sig') as f:
            w=csv.DictWriter(f,fieldnames=list(rows[0]) if rows else ['vazio']);w.writeheader();w.writerows(rows)
    (out/'resultado.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    g=result['observed_only']
    text=f'''# Auditoria do histórico WINV26

Mesmo intervalo da coleta anterior: {local(start)} a {local(end)}. Consultas diárias ao MT5: {len(logs)}; falhas: {result['failed_queries']}. Candles novos: {dict(added)}; OHLC revisados: {dict(changed)}.

Comparação M5 com cinco candles M1: {result['M5_checks']}.
Persistem {result['intraday_gaps']} intervalos intradiários descontínuos, somando {result['missing_minutes_between_bars']} minutos entre candles. Não são necessariamente falhas: sem registro de sessão e cobertura certificada de ticks, ausência de negócio e ausência de histórico não são distinguíveis. Horários convertidos de UTC conforme API; não houve correção arbitrária do relógio da corretora. Não certificamos sessões B3 completas.

## Replay sem saídas fictícias no resultado
Mesma regra automática M5/M1 e alvo 2R; stop além do M5, uma posição por vez, sem macro ou confirmação manual. {len(trades)} candidatos executáveis na simulação, dos quais {len(censored)} ficam inconclusivos por interrupção/fim. Seu resultado estimado anterior não entra no saldo abaixo. As exclusões são informadas, não presumidas como operações zeradas. O subconjunto com desfecho observado pode ter viés de seleção e não é resultado da estratégia inteira.

- Operações com alvo/stop observado nos candles: {g['n']}.
- Saídas: {g['exits']}.
- Resultado bruto desse subconjunto: {g['total_r']:+.2f}R.
- Percentual positivo: {g['win_rate']:.2%}.
'''
    for s in result['observed_costs']:text+=f"- Fricção hipotética {s['drag_points_per_trade']} pontos: {s['total_r']:+.2f}R.\n"
    text+='''
## Conclusão e pendências
Este é um diagnóstico e replay condicionado à cobertura, não uma estatística validada ou execução real. Não preenchemos candles sintéticos, não ajustamos parâmetros para melhorar desempenho e não trocamos contratos silenciosamente. Sondagens de ticks estão no JSON; retorno vazio não comprova ausência de negócios. Para validar todo o período é necessária fonte com cobertura confirmada, calendário/horários da sessão e custos reais. Contratos mais líquidos por época devem ser analisados individualmente, com aquecimento separado, se forem usados futuramente.
Documentação oficial: https://www.mql5.com/en/docs/python_metatrader5/mt5copyratesrange_py e https://www.mql5.com/en/docs/python_metatrader5/mt5copyticksrange_py
'''
    (out/'RELATORIO.md').write_text(text,encoding='utf-8')
    print(json.dumps(result,indent=2));print('PASTA',out)

if __name__=='__main__':main()
