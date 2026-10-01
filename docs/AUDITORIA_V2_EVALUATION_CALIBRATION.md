# Auditoria V2 — Evaluation, Outcome, Calibration e Coleta Automática de Dados

**Projeto:** PO3 Copilot  
**Branch auditada:** `main`  
**Baseline:** PO3 Copilot V2 — Decision Engine V1 integrado no commit `827ccf4`  
**Escopo:** auditoria e planejamento técnico; nenhuma funcionalidade V2 foi implementada.

## 1. Resumo executivo

A V1 está operacional e preserva o princípio central: o painel é somente leitura, a decisão operacional é manual e não existe envio automático de ordens. O Decision Engine já normaliza o estado, valida dados, produz seis decisões estruturadas, aplica Decision Gate, pode executar uma segunda análise independente e registra metadados do modelo/fallback.

A coleta atual **já lê M1**, porém somente durante o ciclo de rerun do Streamlit. O `macro_app.py` usa `st.fragment(run_every=...)` com intervalo configurável de 5 a 60 segundos; o `app.py` legado também usa fragmento periódico. Isso não equivale a uma coleta por fechamento efetivo de candle. O MT5 é inicializado, consultado e desligado a cada leitura; nenhum candle ou MarketState é persistido automaticamente.

O banco SQLite atual registra apenas análises e eventos de erro. A tabela `outcomes` existe, mas não há registros e não há restrição de unicidade que impeça duplicação. Não existem tabelas para candles M1, MarketState congelado, itens de decisão, avaliações, calibração ou drift.

**Recomendação:** implementar a V2 em etapas, começando por schema/persistência e por um worker local controlado de coleta factual M1, separado do ciclo da UI, protegido por chave única e lease no SQLite. A coleta não deve chamar LLM. O Decision Engine deve continuar manual na primeira etapa.

## 2. Restrições e não objetivos

Durante esta auditoria não foram alterados:

- indicadores `.mq5`;
- prompts, schemas e regras operacionais da V1;
- integração do OpenRouter;
- `.env`;
- leitura de ordens ou execução de negociação;
- interface operacional;
- banco de produção.

A V2 inicial não deve incluir MCP, agentes autônomos, machine learning para trade, reinforcement learning, autoajuste de prompts/regras, troca automática de modelo, probabilidade de lucro ou recomendação automática de operação.

## 3. Arquitetura real encontrada

### Entradas e UI

- [`macro_app.py`](../macro_app.py) é o painel macro atual. Lê snapshot do MT5, renderiza contexto, calendário, chat e análise do dia.
- [`app.py`](../app.py) é o painel legado, também somente leitura, com leitura dos indicadores/regras PO3.
- [`po3/mt5_reader.py`](../po3/mt5_reader.py) é o adaptador de leitura do terminal.
- [`po3/models.py`](../po3/models.py) define `MarketSnapshot`, `PriceLevel`, `PriceZone` e eventos.
- [`po3/decision_engine/`](../po3/decision_engine/) contém `MarketState`, validator, schemas, engine, gate, consenso e narrativa.
- [`po3/external_data.py`](../po3/external_data.py), [`po3/investing_calendar.py`](../po3/investing_calendar.py) e [`po3/market_news.py`](../po3/market_news.py) coletam calendário, manchetes e cotações autorizadas.
- [`po3/learning_store.py`](../po3/learning_store.py) persiste análises e erros localmente.

### Fluxo atual do painel macro

1. O Streamlit cria um fragmento periódico conforme o intervalo escolhido.
2. `read_snapshot(terminal, symbol)` inicializa o MT5, confirma conexão, lê candles/fatores, obtém tick e encerra o MT5 em `finally`.
3. O painel mantém o snapshot atual em `st.session_state`.
4. Calendário e contexto externo usam `st.cache_data`: calendário por 1.800 s e contexto externo por 900 s.
5. A análise do dia e as perguntas do chat são manuais; somente essas ações chamam a IA e `save_analysis`.
6. O histórico da UI lê `recent_analyses`; não existe processamento periódico de outcomes.

## 4. Auditoria da coleta atual

1. **Lê M1?** Sim. `read_snapshot` lê `TIMEFRAME_M1` com até 300 registros.
2. **Frequência?** Indireta: depende do rerun do fragmento, configurável entre 5 e 60 segundos no `macro_app.py`; não é fixada em 60 segundos.
3. **Depende de rerun?** Sim.
4. **Timer?** O timer é o `run_every` do fragmento Streamlit; não há timer de domínio independente.
5. **Auto-refresh?** Sim, enquanto o toggle estiver ativo e a sessão Streamlit estiver viva.
6. **Cache?** Sim, somente para calendário/contexto externo; snapshot MT5 não é cacheado.
7. **Persistência de candles?** Não.
8. **Persistência de MarketState?** Somente dentro do JSON de uma análise manual salva; não há snapshot periódico.
9. **Duplicação?** Sim, análises repetidas e outcomes futuros podem duplicar; não há chave de negócio para candles/outcomes.
10. **Múltiplos processos/abas?** Não há coordenação. Cada sessão pode executar seu próprio fragmento e chamar MT5.
11. **Inicialização MT5?** `mt5.initialize(terminal, timeout=8000)`, com validação de `terminal_info().connected`.
12. **Encerramento?** `mt5.shutdown()` no bloco `finally`.
13. **Custo M1 a cada minuto?** A leitura atual é pequena (300 M1 + demais timeframes e macro), mas inclui vários símbolos/fatores e inicialização do terminal; um coletor dedicado deve reutilizar conexão ou limitar consultas.
14. **Histórico MT5?** Há suporte a `copy_rates_from_pos` e `copy_rates_range` no módulo de replay, mas o painel não grava esse histórico.
15. **Timestamps?** Epoch do MT5 é convertido de UTC para `America/Sao_Paulo`.
16. **Brasília?** Sim, via `ZoneInfo("America/Sao_Paulo")` em MT5, calendário e notícias.
17. **Fim de semana/fechado?** Não há uma camada explícita de sessão no coletor; ausência de barras precisa ser tratada na V2, sem inventar candle.
18. **Ativo atual?** O usuário informa o símbolo no sidebar; o default é `WINV26`. Não existe resolução automática de vencimento.
19. **Troca de contrato WIN?** Não há rollover automático. O símbolo informado é repassado ao MT5.
20. **Histórico após reinício?** Não para candles/MarketState; somente análises manuais já salvas. Outcomes pendentes não são processados.

## 5. Módulos históricos existentes

- [`po3/historical_training.py`](../po3/historical_training.py) faz replay isolado de M1, agrega timeframes e usa um corte fixo, mas não reconstrói o `MarketState` V1 completo, não possui fontes históricas de notícias/calendário e pode chamar a IA.
- [`po3/backtest.py`](../po3/backtest.py) simula sinais/confluência; não é Outcome Engine de contexto.
- [`statistical_audit.py`](../statistical_audit.py) faz auditoria causal de regras/execução simulada; não deve ser misturado com outcomes de análise.
- [`po3/demo_data.py`](../po3/demo_data.py) fornece dados de teste.

Esses módulos são reutilizáveis como referências/test fixtures, mas nenhum deve ser conectado diretamente ao coletor de produção sem contratos novos e testes de causalidade.

## 6. Estratégias de coleta M1 avaliadas

| Abordagem | Vantagens | Riscos/complexidade |
|---|---|---|
| A. Auto-refresh Streamlit | Simples, sem processo novo | Duplica em abas, bloqueia rerun, depende da UI e pode perder candles |
| B. Loop no processo Streamlit | Controle direto | Mantém UI ocupada, múltiplas sessões geram múltiplos loops |
| C. Thread controlada | Isola parcialmente a UI | Ciclo de vida difícil, duplicação entre processos e encerramento delicado no Windows |
| D. Worker local separado | Isola a UI, testa melhor, coleta mesmo sem rerun visual | Exige start/stop e lease; precisa tratar processo órfão |
| E. Scheduler local | Persistência independente | Mais dependência operacional e risco de continuar fora do painel |
| F. Detecção de fechamento M1 | Causal e sem drift de relógio | Precisa histórico MT5, deduplicação e tratamento de lacunas |

### Recomendação

Usar **D + F**: um worker local factual, iniciado pelo launcher do PO3 Copilot e encerrado no fechamento, que detecta novo candle M1 fechado. O worker deve ser protegido por lease/heartbeat no SQLite, de modo que duas abas não criem dois coletores. A UI apenas exibe status; não deve executar a coleta pesada nem chamar LLM.

A regra operacional deve consultar `copy_rates_from_pos(symbol, TIMEFRAME_M1, 1, ...)` ou equivalente para excluir o candle em formação. O último timestamp fechado salvo deve ser comparado ao retorno do MT5. Se houver mais de um timestamp novo, inserir a lacuna histórica em ordem; se não houver novo timestamp, não gravar nada.

## 7. Persistência M1 sugerida

Criar futuramente `market_bars_m1` com:

- `id INTEGER PRIMARY KEY`;
- `symbol TEXT NOT NULL`;
- `timestamp TEXT NOT NULL` em UTC canônico;
- `open`, `high`, `low`, `close REAL NOT NULL`;
- `tick_volume INTEGER`;
- `real_volume INTEGER` quando disponível;
- `spread INTEGER/REAL` quando disponível;
- `source TEXT NOT NULL`;
- `schema_version TEXT NOT NULL`;
- `created_at TEXT NOT NULL`.

Restrição principal: `UNIQUE(symbol, timestamp)`. Índice: `(symbol, timestamp)`. A gravação deve ocorrer em transação curta com `INSERT OR IGNORE`, `busy_timeout` e tratamento de `database is locked`. Não armazenar objetos Python gigantes nem repetir MarketState em cada candle.

## 8. MarketState histórico

O `MarketState` atual é serializável, mas contém candles recentes, macro, níveis, zonas, calendário, notícias e fontes. Para replay exato, a recomendação é um **modelo híbrido**:

- `market_states` guarda o estado factual congelado, horário de corte, ativo, versões e JSON canônico de contexto;
- candles M1 ficam normalizados em `market_bars_m1` e o snapshot guarda intervalo/hash/referência;
- calendário, manchetes e cotações disponíveis naquele corte são armazenados no JSON capturado, com fonte e timestamp de coleta;
- nenhuma consulta posterior deve preencher um estado antigo.

O registro deve conter `MARKET_STATE_VERSION`, `DECISION_ENGINE_VERSION`, `PROMPT_VERSION`, `SCHEMA_VERSION` e futuramente `OUTCOME_SCHEMA_VERSION`/`EVALUATION_VERSION`.

## 9. Proteção contra data leakage

Para cada estado histórico:

1. definir `cutoff_at` em UTC e exibir Brasília somente na UI;
2. aceitar somente barras com fechamento `<= cutoff_at`;
3. capturar calendário/notícias como eram conhecidos no corte, sem refetch atual;
4. manter outcomes em tabelas separadas, nunca dentro do prompt do replay;
5. impedir que o serializer inclua campos posteriores;
6. registrar `source_checked_at` e versão do schema;
7. testar que o replay não muda quando outcomes posteriores são adicionados ao banco.

O `MarketState` usado pela segunda análise deve continuar sendo exatamente o mesmo objeto; o Outcome Engine só pode ler dados após o corte.

## 10. Outcome Engine planejado

Outcomes não são trades, não são stop/alvo e não geram win rate. Para cada análise/state e horizonte `5m`, `15m`, `30m`, `60m` e fechamento de sessão, calcular deterministicamente:

- preço no horizonte, se existir;
- variação absoluta e percentual;
- máxima e mínima posteriores;
- `future_high_delta` e `future_low_delta`;
- amplitude e, se definido, volatilidade;
- status `PENDENTE`, `DISPONIVEL`, `SEM_DADO`, `MERCADO_FECHADO` ou `INVALIDO`.

MFE/MAE devem ser derivados depois a partir de deltas objetivos e do contexto classificado. Para comprador/altista, MFE favorece alta e MAE queda; para vendedor/baixista, o inverso. Armazenar primeiro fatos neutros reduz risco de contaminar a medição com uma interpretação.

Uma tabela `observed_outcomes` deve ter chave única `(state_id, horizon_minutes)` ou `(analysis_id, horizon_code)`. O processamento deve ser idempotente: reiniciar ou executar novamente apenas atualiza pendências vencidas.

## 11. Outcomes pendentes e sessões

Ao iniciar e periodicamente enquanto o painel estiver aberto:

- localizar análises/states sem outcome vencido;
- consultar somente MT5 histórico;
- respeitar calendário de sessão, fim de semana, feriado, leilão e lacunas;
- não inventar candle ausente;
- gravar resultado uma única vez.

Troca de contrato deve ser identificada pelo símbolo salvo no state; não misturar WINV26 com novo vencimento. O fechamento de sessão deve ser um horizonte explicitamente marcado, não um preço arbitrário.

## 12. SQLite atual e proposta

Banco atual: `data/po3_learning.sqlite`, aproximadamente 467 KB no momento da auditoria.

Tabelas e contagens observadas:

- `analysis_runs`: 20 registros; análise manual, símbolo, preço, viés, resposta, contexto e snapshot.
- `outcomes`: 0 registros; possui apenas `analysis_id`, timestamp, preço futuro, movimento, viés observado e notas.
- `ai_error_events`: 0 registros.
- Índices atuais: data de análise, vínculo de outcomes e data de erros.

Não há migrations, versão de schema, WAL/busy timeout configurado pelo projeto, lease, tabela de candles ou proteção contra duplicação de outcome. A V2 deve adicionar migrations idempotentes, backup antes da primeira alteração, transações curtas, `PRAGMA busy_timeout`, WAL quando validado no Windows e índices por símbolo/timestamp/status.

Tabelas realmente necessárias na primeira parte da V2:

1. `market_bars_m1`;
2. `market_states`;
3. `observed_outcomes`.

`decision_items`, `model_evaluations` e `calibration_snapshots` podem ser adicionadas depois, caso o JSON estruturado não seja suficiente para as consultas analíticas.

## 13. Evaluation Engine, Calibration e confiança

O Evaluation Engine deve ser determinístico e separado da narrativa. Métricas de sistema: JSON válido, reparo, fallback, bloqueio, segunda análise, consenso/divergência, latência e campos ausentes. Métricas de decisão: distribuição, follow-through, variação posterior, MFE, MAE, reversão e dispersão. Métricas de modelo: estabilidade, latência, JSON válido, reparo, fallback e divergência.

A confiança `ALTA`, `MÉDIA`, `BAIXA` não é probabilidade. A V2 pode medir retrospectivamente se a ordem esperada de consistência aparece, mas não deve alterar o Gate inicialmente. Amostras recomendadas e configuráveis:

- menos de 30: insuficiente;
- 30–99: indicativa;
- 100+: utilizável;
- 200+: maior robustez.

Calibration deve ser relatório, não ajuste automático. Não misturar métricas de versões incompatíveis de modelo, prompt ou schema.

## 14. Replay, benchmark, estabilidade e drift

**Replay Engine:** recebe `MarketState` congelado, chama o Decision Engine escolhido e compara a nova classificação com a original e com outcomes, sem dados futuros.

**Benchmark:** inicialmente offline/shadow mode, com modelos A/B/C explicitamente selecionados. Não trocar automaticamente o modelo operacional.

**Decision Stability:** executar o mesmo state N vezes em ambiente controlado e medir igualdade de decisões, confiança e Gate. Não fazer execução massiva no operacional.

**Drift:** cálculo determinístico de distribuição por janela (por exemplo, 30 dias contra 7 dias), segmentado por versão, modelo, prompt e regime. A LLM não deve detectar drift na primeira versão.

## 15. Coleta de notícias e calendário

O calendário atual é Investing.com com cache de 30 minutos no painel. Notícias e cotações são coletadas das fontes autorizadas por `fetch_daily_context`, com cache de 15 minutos no fluxo macro. O calendário histórico não está disponível: o replay existente marca calendário/notícias como indisponíveis e usa MT5 parcial.

Na V2, os resultados de coleta precisam ser congelados no `cutoff_at`, deduplicados por fonte/URL/título/data e armazenados junto do MarketState. Não fazer consultas atuais para preencher retrospectivamente um state antigo.

## 16. Concorrência, múltiplas abas e falhas

Duas abas podem hoje disparar leituras independentes. A proteção recomendada é:

- singleton lógico por `symbol + collector_name` em tabela de lease;
- `owner_id`, PID, heartbeat e expiração;
- UNIQUE em candle;
- transações curtas e retry limitado para lock;
- UI somente observa o status do worker.

Se MT5 cair, pausar a coleta, registrar diagnóstico e retomar quando `terminal_info().connected` voltar; não derrubar Streamlit. Se SQLite estiver bloqueado, retry com backoff curto e evento de erro; se houver corrupção/falta de espaço, interromper gravação, preservar o painel e sinalizar necessidade de backup/reparo. Nenhum erro de coleta deve emitir ordem.

## 17. Reinício e recuperação

No startup:

1. ler último M1 salvo por símbolo;
2. consultar MT5 a partir desse timestamp, com margem de segurança;
3. inserir somente candles fechados e novos;
4. verificar pendências de outcomes vencidos;
5. liberar leases expirados;
6. retomar heartbeat/worker.

A recuperação deve ser idempotente e não pode assumir que o contrato atual é o anterior. Se o símbolo mudou, iniciar uma série separada.

## 18. Performance estimada

Para aproximadamente 8 horas e 480 candles M1/dia:

- ~10.500 candles/mês;
- ~126.000 candles/ano.

SQLite deve suportar esse volume com índice composto, JSON fora da tabela de candles e retenção/backup definidos. PostgreSQL não é necessário na primeira V2. O risco maior é o tamanho dos MarketStates/notícias, não os candles; por isso, usar JSON comprimido/referências e política de retenção.

## 19. Testes atuais e testes futuros

A V1 passou nos testes existentes, incluindo Decision Engine, parser/reparo, Gate, fallback, histórico e contrato somente leitura. A V2 deve acrescentar testes para:

- novo M1 fechado, candle duplicado e candle em formação;
- gap, reinício, duas abas e lease expirado;
- MT5 desconectado, mercado fechado, timezone, contrato alterado;
- snapshot de 5 minutos, calendário de 5 minutos, notícias de 10 minutos;
- outcomes 5/15/30/60, fechamento, pendente e idempotência;
- MFE/MAE, ausência de dados e data leakage;
- replay, versões, benchmark, estabilidade, amostra insuficiente e drift;
- locking, corrupção/backup SQLite e compatibilidade de registros V1.

## 20. Arquivos futuros

Prováveis novos módulos, ainda não criados:

- `po3/collection/mt5_m1_collector.py`;
- `po3/collection/lease.py`;
- `po3/storage/migrations.py`;
- `po3/storage/market_repository.py`;
- `po3/outcome_engine.py`;
- `po3/evaluation_engine.py`;
- `po3/replay_engine.py`;
- `po3/calibration.py`;
- `po3/benchmark.py`;
- `po3/drift.py`;
- testes correspondentes em `tests/`;
- documentação operacional e de recuperação.

Arquivos existentes que provavelmente serão modificados somente com autorização futura:

- `po3/learning_store.py` para migrations/repositórios;
- `po3/mt5_reader.py` para adapter de barras fechadas, se necessário;
- `macro_app.py` para exibir status/controles do coletor;
- launcher `.cmd` para iniciar/parar o worker;
- documentação e testes.

Devem permanecer intocados na primeira implementação: indicadores `.mq5`, regras PO3, prompts V1, `po3/decision_engine/schemas.py`, `gate.py` e fluxo de ordens (inexistente).

## 21. Fases recomendadas

1. **Schema e persistência M1:** migrations, backup, tabelas e repositório idempotente.
2. **Coleta automática M1:** worker factual, candle fechado, lease e recuperação.
3. **MarketState periódico:** snapshot híbrido a cada 5 minutos.
4. **Outcome Engine:** deltas neutros, horizontes e status.
5. **Outcomes pendentes:** processamento no startup/periódico.
6. **Metrics Engine:** agregações determinísticas.
7. **Evaluation Engine:** qualidade de sistema/decisões/modelos.
8. **Dashboard histórico:** filtros e drill-down somente leitura.
9. **Replay Engine:** reprodução causal sem leakage.
10. **Model Benchmark:** shadow mode offline desligado por padrão.
11. **Decision Stability:** repetição controlada do mesmo state.
12. **Calibration Engine:** relatórios por amostra e versão, sem alterar Gate.
13. **Drift:** janelas e alertas determinísticos.
14. **Exportação/relatórios:** CSV, sem Excel nesta fase.
15. **Testes completos:** concorrência, recuperação e data leakage.
16. **Documentação:** operação, backup e rollback.
17. **Validação final:** V1 intacta, V2 desligável e sem ordens.

## 22. Critérios de aceitação da futura V2

- V1 continua passando sua suíte sem alteração de comportamento;
- coletor grava apenas candles M1 fechados;
- `UNIQUE(symbol, timestamp)` impede duplicação;
- duas abas não criam dois coletores ativos;
- reinício recupera lacunas sem duplicar;
- MarketState tem corte explícito e replay não recebe dados futuros;
- outcomes são determinísticos e idempotentes;
- outcomes não são chamados de trades e não geram win rate;
- calendário/notícias são congelados no corte;
- falha de MT5/SQLite não derruba o painel;
- LLM permanece manual e sem chamada periódica na primeira etapa;
- nenhum modelo pago, ordem automática ou alteração de indicador é introduzido;
- registros V1 continuam legíveis;
- backup, migration e rollback são testados.

## 23. Validação da V1 nesta auditoria

- Branch auditada: `main`.
- Testes: **35 aprovados, 0 falhas**.
- `macro_app.py` e `app.py`: health `ok` na validação anterior e após a integração.
- `py_compile`: aprovado.
- `git diff --check`: aprovado.
- OpenRouter: modelo `qwen/qwen3.8-27b:free`, fallback somente `:free`.
- `.env`: fora do Git.
- Indicadores `.mq5`: não alterados.
- Execução automática de ordens: não existe; o contrato somente leitura permanece aprovado.

## 24. Conclusão

A V1 está pronta como baseline para iniciar a V2, mas a implementação deve começar pela persistência e pelo controle de concorrência, não pelo dashboard ou pela calibração. O caminho crítico é: candles M1 fechados → MarketState congelado → outcomes idempotentes → métricas determinísticas → replay/evaluation. A coleta deve ser separada do Streamlit e do LLM para evitar duplicação, travamento de UI e data leakage.

**Status:** auditoria concluída; implementação V2 não iniciada. Nova autorização é necessária antes de criar módulos, migrations, workers, tabelas novas ou flags de coleta.
