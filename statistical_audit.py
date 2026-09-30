"""Replay causal das regras do indicador; somente leitura do MT5."""
import csv
import json
import math
import hashlib
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo('America/Sao_Paulo')
OUT = Path(__file__).parent / 'reports' / 'estatistica_2026_09_07'

def local(t):
    return datetime.fromtimestamp(t, timezone.utc).astimezone(TZ)

def build(bars, seconds):
    """Mesma detecção e Fresh do MQL, somente candles conhecidos no instante."""
    if len(bars) < 4:
        return []
    typical = max(sum(abs(b['close']-b['open']) for b in bars)/len(bars), 1)
    out = []
    def fresh(start, lo, hi):
        for j in range(start,len(bars)):
            if bars[j]['low']<=hi and bars[j]['high']>=lo:
                return False
        return True
    for i in range(2, len(bars)):
        a, c = bars[i-2], bars[i]
        if c['low'] > a['high'] and fresh(i+1,a['high'],c['low']):
            out.append(('FVG',1,a['high'],c['low'],c['time'],c['time']+seconds))
        elif c['high'] < a['low'] and fresh(i+1,c['high'],a['low']):
            out.append(('FVG',-1,c['high'],a['low'],c['time'],c['time']+seconds))
    for i in range(len(bars)-1):
        a,b=bars[i:i+2]
        if abs(b['close']-b['open']) < max(1.5*abs(a['close']-a['open']),1.5*typical):
            continue
        direction=1 if b['close']>b['open'] else -1
        if (a['close']-a['open'])*direction < 0 and fresh(i+2,a['low'],a['high']):
            out.append(('OB',direction,a['low'],a['high'],a['time'],b['time']+seconds))
    return out

def signals(m1,m5):
    result=[]; baseline=[]; seen=set(); seen5=set(); k=0; zones5=[]
    for i,b in enumerate(m1):
        if i % 5000 == 0:
            print('Replay:',i,'/',len(m1),flush=True)
        now=b['time']+60
        old=k
        while k<len(m5) and m5[k]['time']+300<=now:
            k+=1
        if i<1198 or k<399:
            continue
        if old!=k or not zones5:
            zones5=build(m5[max(0,k-399):k],300)
            if zones5:
                z=max(zones5,key=lambda z:z[5])
                ident=z[:5]
                if ident not in seen5:
                    seen5.add(ident)
                    baseline.append((i,z,z,'M5'))
        zones1=build(m1[max(0,i-1198):i+1],60)
        hits=[]
        for h in zones5:
            for l in zones1:
                if l[4]>h[4] and l[1]==h[1] and l[2]<=h[3] and l[3]>=h[2]:
                    hits.append((h,l))
                    break
        if hits:
            h,l=hits[-1]  # Reprodução da seleção atual do indicador, não ordenar artificialmente.
            ident=(h[:5],l[:5])
            if ident not in seen:
                seen.add(ident)
                result.append((i,h,l,h[0]+'+'+l[0]))
    return result,baseline

def simulate(bars, sigs, tick, point, rr):
    trades=[]; blocked=-1; used=set(); skipped=Counter()
    for i,h,l,kind in sigs:
        if i<=blocked:
            skipped['operacao_aberta']+=1;continue
        region=h[:5]
        if region in used:
            skipped['zona_M5_ja_operada']+=1;continue
        if i+1>=len(bars) or bars[i+1]['time']-bars[i]['time']!=60:
            skipped['sem_proximo_minuto']+=1;continue
        # Referência no fechamento observável; execução no próximo open evita preço retroativo.
        entry=bars[i+1]['open']; direction=h[1]
        stop=math.floor((h[2]-2*point)/tick)*tick if direction==1 else math.ceil((h[3]+2*point)/tick)*tick
        risk=(entry-stop)*direction
        if risk<=0:
            skipped['stop_lado_invalido']+=1;continue
        target=entry+direction*rr*risk
        used.add(region)
        reason='fim_amostra'; exit_i=len(bars)-1; price=bars[-1]['close']; ambiguous=False
        for j in range(i+1,len(bars)):
            b=bars[j]
            if j>i+1 and (b['time']-bars[j-1]['time']!=60 or local(b['time']).date()!=local(bars[j-1]['time']).date()):
                exit_i=j-1;price=bars[j-1]['close'];reason='fim_sessao_ou_lacuna';break
            hit_stop=b['low']<=stop if direction==1 else b['high']>=stop
            hit_target=b['high']>=target if direction==1 else b['low']<=target
            if hit_stop:
                exit_i=j;price=min(stop,b['open']) if direction==1 else max(stop,b['open']);reason='stop';ambiguous=hit_target;break
            if hit_target:
                exit_i=j;price=target;reason='alvo';break
        blocked=exit_i
        pnl=direction*(price-entry)
        trades.append(dict(signal=local(bars[i]['time']+60).isoformat(),entry_time=local(bars[i+1]['time']).isoformat(),exit_time=local(bars[exit_i]['time']+60).isoformat(),direction=direction,kind=kind,entry=entry,stop=stop,target=target,risk_points=risk,pnl_points=pnl,r=pnl/risk,reason=reason,ambiguous=ambiguous))
    return trades,dict(skipped)

def stats(trades,drag=0):
    rs=[(t['pnl_points']-drag)/t['risk_points'] for t in trades]
    n=len(rs);w=sum(r>0 for r in rs);gain=sum(r for r in rs if r>0);loss=-sum(r for r in rs if r<0)
    equity=peak=dd=0;streak=worst=0
    for r in rs:
        equity+=r;peak=max(peak,equity);dd=max(dd,peak-equity)
        streak=streak+1 if r<0 else 0;worst=max(worst,streak)
    p=w/n if n else 0;z=1.96;den=1+z*z/n if n else 1
    center=(p+z*z/(2*n))/den if n else 0
    half=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/den if n else 0
    return dict(n=n,wins=w,losses=sum(r<0 for r in rs),win_rate=p,win_rate_wilson_95=[center-half,center+half],total_r=sum(rs),mean_r=sum(rs)/n if n else None,profit_factor=gain/loss if loss else None,max_drawdown_r=dd,max_loss_streak=worst,drag_points_per_trade=drag,exits=dict(Counter(t['reason'] for t in trades)),ambiguous=sum(t['ambiguous'] for t in trades))

def main():
    import MetaTrader5 as mt5
    if not mt5.initialize(r'C:\Program Files\Clear Investimentos MT5 Terminal\terminal64.exe',timeout=8000):
        raise RuntimeError(mt5.last_error())
    try:
        info=mt5.symbol_info('WINV26')
        if info is None: raise RuntimeError('WINV26 indisponível')
        frames={}
        for name,tf,count in [('M1',mt5.TIMEFRAME_M1,50000),('M5',mt5.TIMEFRAME_M5,10000)]:
            raw=mt5.copy_rates_from_pos('WINV26',tf,0,count)
            if raw is None: raise RuntimeError(str(mt5.last_error()))
            frames[name]=[{key:(int(row[key]) if key=='time' else float(row[key])) for key in ('time','open','high','low','close','spread')} for row in raw]
        tick,point=float(info.trade_tick_size),float(info.point)
    finally:
        mt5.shutdown()
    if tick<=0: raise ValueError('Tick inválido')
    cutoff=int((datetime.now(timezone.utc)-timedelta(days=90)).timestamp())
    now=int(datetime.now(timezone.utc).timestamp())
    m1=[b for b in frames['M1'] if cutoff<=b['time'] and b['time']+60<=now]
    m5=[b for b in frames['M5'] if cutoff<=b['time'] and b['time']+300<=now]
    for rows in (m1,m5):
        assert rows and all(a['time']<b['time'] for a,b in zip(rows,rows[1:]))
        assert all(b['low']<=min(b['open'],b['close'])<=max(b['open'],b['close'])<=b['high'] for b in rows)
    sigs,base=signals(m1,m5)
    OUT.mkdir(parents=True,exist_ok=True)
    results={}
    for label,ss,rr in [('confluencia_2R',sigs,2),('M5_sem_M1_2R',base,2)]+[(f'confluencia_{r}R',sigs,r) for r in (1,3,4,5)]:
        trades,skipped=simulate(m1,ss,tick,point,rr)
        results[label]=dict(gross=stats(trades),sensitivity=[stats(trades,tick*v) for v in (1,2,4)],skipped=skipped)
        with (OUT/(label+'.csv')).open('w',newline='',encoding='utf-8-sig') as f:
            writer=csv.DictWriter(f,fieldnames=list(trades[0]) if trades else ['signal']);writer.writeheader();writer.writerows(trades)
    payload=json.dumps(dict(M1=m1,M5=m5),sort_keys=True)
    (OUT/'candles.json').write_text(payload,encoding='utf-8')
    quality=dict(start=local(m1[0]['time']).isoformat(),end=local(m1[-1]['time']).isoformat(),M1=len(m1),M5=len(m5),days=len(set(local(b['time']).date() for b in m1)),intraday_gaps=sum(b['time']-a['time']!=60 and local(a['time']).date()==local(b['time']).date() for a,b in zip(m1,m1[1:])),tick=tick,point=point,signals=len(sigs),data_sha256=hashlib.sha256(payload.encode()).hexdigest())
    report=dict(quality=quality,results=results)
    (OUT/'resultado.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2),flush=True)

if __name__=='__main__':main()
