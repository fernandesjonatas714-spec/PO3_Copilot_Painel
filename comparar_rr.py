import json,csv,hashlib
from pathlib import Path
from statistics import mean,median
from test_setup_area import generate
from statistical_audit import simulate,stats

root=Path(__file__).parent/'reports/auditoria_WIN_20260908_183835'
payload=(root/'candles.json').read_bytes()
data=json.loads(payload)
assert hashlib.sha256(payload).hexdigest()==json.loads((root/'resultado.json').read_text())['sha256']
signals,_=generate(data['M1'],data['M5'])
result={}
for rr in (2,1):
    trades,skipped=simulate(data['M1'],signals,5,1,rr)
    observed=[t for t in trades if t['reason'] in ('alvo','stop')]
    risks=[t['risk_points'] for t in trades]
    result[str(rr)]=dict(total=len(trades),inconclusive=len(trades)-len(observed),stop_mean=mean(risks),stop_median=median(risks),stop_min=min(risks),stop_max=max(risks),observed_stop_mean=mean(t['risk_points'] for t in observed),observed=stats(observed),costs=[stats(observed,n) for n in (5,10,20)])
    with (root/f'comparacao_{rr}R_operacoes.csv').open('w',newline='',encoding='utf-8-sig') as f:
        w=csv.DictWriter(f,fieldnames=list(trades[0]));w.writeheader();w.writerows(trades)
(root/'comparacao_rr.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
text='# Comparação alvo 2R e 1R\n\nMesmos dados auditados, confluência automática M5/M1, sem macro/confirmação manual. Stop 2 points além da zona M5, arredondado ao tick. Uma posição por vez; simulação refeita para cada alvo. Stops medidos da entrada até o nível planejado, em pontos.\n\n| Medida | 2R | 1R |\n|---|---:|---:|\n'
for label,key in [('Total simulado','total'),('Inconclusivas','inconclusive'),('Stop médio (pontos)','stop_mean'),('Mediana stop (pontos)','stop_median')]:text+=f"| {label} | {result['2'][key]:.2f} | {result['1'][key]:.2f} |\n"
for label,key in [('Com desfecho','n'),('Alvos','wins'),('Stops','losses'),('Resultado bruto R','total_r'),('Taxa positiva','win_rate'),('Drawdown R','max_drawdown_r')]:text+=f"| {label} | {result['2']['observed'][key]:.4f} | {result['1']['observed'][key]:.4f} |\n"
text+='\nResultados de operações com desfecho nos candles, não execuções comprovadas. As inconclusivas são separadas e podem causar viés de seleção. CSV mantém marcações das inconclusivas para rastreabilidade, mas elas não entram no resultado comparativo. Custos no JSON são fricção hipotética total por operação. Horários originais preservados; sem filtro horário. Não ajusta indicador ou ordens.\n'
(root/'COMPARACAO_RR.md').write_text(text,encoding='utf-8')
print(json.dumps(result,indent=2))
