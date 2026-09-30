from __future__ import annotations
from datetime import datetime, timedelta
import json, math, statistics
from pathlib import Path
import MetaTrader5 as mt5

SYMBOL='WINV26'
TF={'M15':mt5.TIMEFRAME_M15,'M5':mt5.TIMEFRAME_M5,'M1':mt5.TIMEFRAME_M1}
N={'M15':7000,'M5':21000,'M1':40000}

def atr(vals, i, period=14):
    if i < period: return None
    tr=[]
    for j in range(i-period+1,i+1):
        prev=vals[j-1]['close']
        tr.append(max(vals[j]['high']-vals[j]['low'],abs(vals[j]['high']-prev),abs(vals[j]['low']-prev)))
    return sum(tr)/len(tr)

def main():
    if not mt5.initialize(r'C:\Program Files\Clear Investimentos MT5 Terminal\terminal64.exe', timeout=8000):
        raise RuntimeError(mt5.last_error())
    result={}
    try:
        for name,tf in TF.items():
            raw=mt5.copy_rates_from_pos(SYMBOL,tf,1,N[name])
            if raw is None or len(raw)<30: raise RuntimeError(f'{name}: {mt5.last_error()}')
            bars=[dict(time=int(x['time']),open=float(x['open']),high=float(x['high']),low=float(x['low']),close=float(x['close'])) for x in raw]
            rows=[]
            for i in range(2,len(bars)-1):
                lo=hi=None; direction=None
                if bars[i]['low']>bars[i-2]['high']:
                    lo,hi,direction=bars[i-2]['high'],bars[i]['low'],'COMPRA'
                elif bars[i]['high']<bars[i-2]['low']:
                    lo,hi,direction=bars[i]['high'],bars[i-2]['low'],'VENDA'
                if lo is None: continue
                size=hi-lo; a=atr(bars,i)
                if not a or a<=0: continue
                future=bars[i+1:i+1+min(24,len(bars)-i-1)]
                filled=any(x['low']<=hi and x['high']>=lo for x in future)
                reaction=0.0
                if future:
                    reaction=max((max(x['high'] for x in future)-hi) if direction=='COMPRA' else (lo-min(x['low'] for x in future)),0.0)
                rows.append({'size_points':size,'size_ticks':size/5.0,'atr_points':a,'atr_ratio':size/a,'filled_24':filled,'reaction_points':reaction})
            ratios=sorted(x['atr_ratio'] for x in rows); sizes=sorted(x['size_points'] for x in rows)
            def pct(v,p): return v[min(len(v)-1,max(0,math.ceil(len(v)*p)-1))] if v else None
            bands=[]
            for threshold in (0.10,0.15,0.20,0.25,0.30):
                keep=[x for x in rows if x['atr_ratio']>=threshold]
                bands.append({'min_atr':threshold,'count':len(keep),'share':len(keep)/len(rows) if rows else 0,'fill24':sum(x['filled_24'] for x in keep)/len(keep) if keep else None,'avg_reaction':statistics.mean(x['reaction_points'] for x in keep) if keep else None})
            result[name]={'bars':len(bars),'fvgs':len(rows),'size_points_p50':pct(sizes,.50),'size_points_p75':pct(sizes,.75),'size_points_p90':pct(sizes,.90),'atr_ratio_p50':pct(ratios,.50),'atr_ratio_p75':pct(ratios,.75),'atr_ratio_p90':pct(ratios,.90),'bands':bands}
    finally: mt5.shutdown()
    out=Path(__file__).with_name('relatorio_fvg_tamanhos.json'); out.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8'); print(json.dumps(result,ensure_ascii=False,indent=2))
if __name__=='__main__': main()
