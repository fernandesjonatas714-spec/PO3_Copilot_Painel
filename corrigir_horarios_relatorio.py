"""Tabela operacional com correção explícita de três horas; preserva original."""
import csv
from datetime import datetime,timedelta
from pathlib import Path
from collections import defaultdict

root=Path(__file__).parent/'reports/auditoria_WIN_20260908_183835'
groups=defaultdict(lambda:dict(alvos=0,stops=0,inconclusivas=0))
rows=[]
for filename in ('operacoes_com_desfecho.csv','operacoes_inconclusivas.csv'):
    with (root/filename).open(encoding='utf-8-sig') as f:
        for original in csv.DictReader(f):
            row=dict(original)
            for field in ('signal','entry_time','exit_time'):
                row[field+'_original']=row[field]
                row[field]=(datetime.fromisoformat(row[field])+timedelta(hours=3)).isoformat()
            row['correcao_horaria']='+03:00 sobre relatório anterior; convenção operacional do servidor, pendente validação independente'
            hour=datetime.fromisoformat(row['entry_time']).hour
            kind='alvos' if row['reason']=='alvo' else 'stops' if row['reason']=='stop' else 'inconclusivas'
            groups[hour][kind]+=1;rows.append(row)
rows.sort(key=lambda r:r['entry_time'])
with (root/'operacoes_horario_brasilia.csv').open('w',newline='',encoding='utf-8-sig') as f:
    writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
text='# Distribuição por horário de entrada — Brasília\n\nCorreção operacional explícita: +3 horas nos horários do relatório anterior, preservados em colunas próprias. A convenção do servidor ainda requer comparação independente com negócio/candle de horário conhecido; não é uma mudança universal da API MT5. Não altera preços, entradas, saídas ou resultados.\n\n| Faixa | Alvos | Stops | Inconclusivas |\n|---|---:|---:|---:|\n'
for hour,g in sorted(groups.items()):
    text+=f"| {hour:02d}h–{hour+1:02d}h | {g['alvos']} | {g['stops']} | {g['inconclusivas']} |\n"
(root/'HORARIOS_BRASILIA.md').write_text(text,encoding='utf-8')
print(text)
