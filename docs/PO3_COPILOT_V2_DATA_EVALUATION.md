# PO3 Copilot V2 — dados, avaliação e calibração

## Escopo

Esta versão acrescenta uma camada separada para coletar M1 fechado, congelar
`MarketState`, observar horizontes futuros e calcular métricas descritivas. Ela
não substitui o fluxo V1, não altera prompts, indicadores MT5, OpenRouter ou a
interface principal e não envia ordens.

## Princípios de segurança

- somente candles cujo fechamento já ocorreu entram no banco;
- cada estado tem `cutoff_at_utc` e versão de schema/engine/prompt;
- resultados futuros ficam em `observed_outcomes` e nunca entram no estado usado
  para uma decisão histórica;
- o lease impede dois coletores concorrentes para o mesmo símbolo;
- respostas da IA e métricas são avaliação, não execução automática;
- o fallback do OpenRouter continua limitado a modelos `:free`.

## Banco e migração

`po3.storage.migrations.migrate()` é idempotente e cria as tabelas `market_bars_m1`,
`collector_leases`, `market_states`, `observed_outcomes` e `schema_migrations`.
Antes de uma migração material, `backup_database()` valida a integridade SQLite
e cria uma cópia datada. O banco local continua ignorado pelo Git.

## Coleta

`po3.collection.mt5_m1_collector` é um worker independente. Usa
`copy_rates_from_pos(..., 1, ...)`, portanto exclui o candle em formação, grava
UTC, aplica `UNIQUE(symbol,timestamp_utc)` e usa lease/heartbeat. A integração
com o Streamlit permanece desligada por padrão para preservar a V1; o worker
pode ser iniciado separadamente quando o terminal MT5 estiver conectado.

## Estados, resultados e replay

O coletor deve congelar um estado a cada fechamento alinhado de cinco minutos,
com as barras e fontes disponíveis naquele corte. `po3.outcome_engine` calcula
5, 15, 30 e 60 minutos e fechamento de sessão, com preço futuro, máxima/mínima,
variação absoluta/percentual, MFE/MAE implícitos e status `DISPONIVEL`,
`PENDENTE` ou `MERCADO_FECHADO`. `po3.replay_engine` remove explicitamente
resultados/barras futuras antes de chamar a análise.

## Avaliação e calibração

`po3.evaluation_engine` produz taxa direcional descritiva e buckets de confiança.
Não ajusta automaticamente prompts, pesos, modelos ou regras. Benchmark, drift,
estabilidade e calibração devem ser executados offline e revisados antes de
qualquer alteração de produção.

## Operação recomendada

1. Fazer backup do SQLite.
2. Rodar a migração e validar `PRAGMA integrity_check`.
3. Iniciar um único worker M1 por símbolo.
4. Conferir quantidade de barras fechadas e leases.
5. Rodar replay/avaliação em relatório separado.
6. Revisar resultados; só então propor mudanças em uma nova branch.

## Limitações atuais

Dados históricos de notícias/calendário podem não existir para todos os cortes;
nesse caso o estado deve marcar contexto parcial. A fonte factual primária dos
preços continua sendo o MT5. Não há nesta camada qualquer chamada de ordem.


## Gate de frescor e semântica dos outcomes

Durante uma sessão ativa, um MarketState somente é criado quando o último
candle M1 totalmente fechado está dentro de MT5_MAX_FEED_LAG_SECONDS
(padrão: 120 segundos). O status MT5_DATA_STALE impede a criação silenciosa.
Fora da sessão, a ausência de candle é registrada como
SEM_NOVO_CANDLE_MERCADO_FECHADO, não como erro de feed.

Como o MT5 identifica uma barra pelo horário de abertura, o cutoff é inclusivo
para a barra aberta no cutoff e exclusivo para a barra aberta no target. Assim,
para cutoff 10:00 e target 10:05, entram somente as barras 10:00, 10:01,
10:02, 10:03 e 10:04. O preço futuro é o fechamento da barra aberta às
10:04, que termina exatamente às 10:05; máximas e mínimas usam o mesmo
intervalo. A barra 10:05 não entra no Outcome 5m.

Antes de target_at, o status é PENDENTE. Depois do target, se ainda faltam
barras factuais por atraso temporário, o status é PENDENTE_DADOS. SEM_DADO
ou MERCADO_FECHADO somente indicam ausência factual confirmada, nunca um
substituto inventado. O processor pode ser executado repetidamente: quando o
feed se recupera, o mesmo registro passa a DISPONIVEL sem duplicação.
