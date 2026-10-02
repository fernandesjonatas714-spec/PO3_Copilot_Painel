# O5A — Jev Shadow Decision Engine

O5A é uma integração experimental e somente observacional do modelo fixo
`typesafe/jev-1.13`. Ela lê MarketStates congelados do SQLite e nunca altera a
decisão oficial, a narrativa, Outcomes, MT5 ou ordens.

## Configuração

- `JEV_SHADOW_ENABLED=false` por padrão;
- `JEV_MODEL=typesafe/jev-1.13` (fixo nesta fase);
- `JEV_TIMEOUT_SECONDS=30`;
- chave exclusiva: `OPENROUTER_JEV_API_KEY`;
- endpoint: `https://openrouter.ai/api/alpha/decisions`.

A chave nunca é persistida ou escrita em logs. O serviço Jev é separado de
`ai_service.py`, que continua responsável pelos modelos generativos oficiais.

## Fluxo

`po3-m1` coleta e congela o MarketState; `po3-ai` mantém Auto Decision e
Shadow oficiais; `po3-jev` processa a fila Jev. O worker Jev usa lease próprio,
`po3-jev`, FIFO por `cutoff_at_utc` e `id`, recuperação de execução órfã e uma
única chamada por MarketState/configuração.

Antes da chamada externa, o mesmo validator do Decision Engine é aplicado.
Dados críticos, inclusive calendário ausente quando classificado como crítico,
resultam em `BLOQUEADO`, custo zero e `external_call_performed=false`. Risco de
evento, inclusive score 10, é informacional e não bloqueia.

## Perguntas e normalização

As seis perguntas versionadas (`JEV_QUESTION_VERSION=1.0.0`) são regime macro,
contexto doméstico, contexto técnico, risco de evento, conflito NOUL e contexto
operacional. Todas são enviadas em uma única requisição.

O score Jev bruto 0–9 é convertido deterministicamente para 0–10 por
`raw_score * 10 / 9`, limitado ao intervalo. NOUL usa `>= 0,50` como `SIM` e
`< 0,50` como `NAO` apenas na comparação experimental. Probabilidades e
confidence brutos são preservados.

## Persistência e comparação

`jev_shadow_runs` guarda respostas, uso, custo, latência, versões, status e
metadados de recuperação. A chave única é MarketState + modelo + versão das
perguntas. `jev_comparison.py` é somente leitura e compara campos compatíveis
com `official_decision_runs`; não calcula accuracy, win rate ou lucro.

Jev não gera narrativa. Os três blocos oficiais continuam sendo responsabilidade
da cadeia generativa atual.

## Segurança e limitações

Jev não acessa MT5 diretamente, não lê Outcomes como input, não executa ordens,
não substitui o Decision Engine e não altera indicadores `.mq5`. A flag deve
ser ativada explicitamente somente para uma observação controlada. O5A coleta
disponibilidade, tipagem, custo, latência e diferenças observacionais para uma
eventual avaliação O5B; não promove o Jev automaticamente.
