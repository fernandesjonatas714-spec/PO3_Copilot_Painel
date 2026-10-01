# Auditoria da arquitetura atual — PO3 Copilot

Data da auditoria: 30/09/2026
Escopo: somente análise estrutural. Nenhuma funcionalidade operacional foi alterada nesta fase.

## 1. Resumo executivo

O projeto é uma aplicação local em Python/Streamlit para leitura do WIN da B3. Existem dois pontos de entrada Streamlit:

- `macro_app.py`: painel macro atualmente iniciado pelos atalhos `iniciar_painel_macro.cmd` e `instalar_painel.cmd`; concentra MT5, macro, calendário, notícias, chat, análise do dia, voz e histórico.
- `app.py`: painel PO3 mais antigo/alternativo, com gráficos Altair, checklist manual, regra do livro, opções e leitura do snapshot.

A arquitetura atual é predominantemente procedural: o snapshot do MT5 e os dados externos são serializados em prompts e enviados ao OpenRouter, que retorna texto narrativo. Ainda não existe `MarketState`, `Decision Engine`, `Decision Gate`, schema estruturado de decisões ou `Narrative Engine` separado.

A decisão e a execução permanecem manuais. A leitura do MT5 é somente leitura e não há chamada de envio de ordem identificada no código Python ou nos testes de contrato.

## 2. Árvore relevante

Arquivos de aplicação e operação:

- `macro_app.py` — painel macro principal.
- `app.py` — painel Streamlit alternativo/legado.
- `iniciar_painel_macro.cmd` — inicia `macro_app.py` na porta 8501.
- `iniciar_painel.cmd` — inicia `app.py`.
- `instalar_painel.cmd` — instalação/atalho local.
- `requirements.txt` — dependências Python.
- `.streamlit/config.toml` — configuração visual/servidor.
- `.env` — configuração local; não é versionado.
- `.env.example` — modelo sem segredo.
- `.gitignore` — protege `.env`, ambiente virtual, cache e banco de relatórios.

Pacote `po3/`:

- `models.py` — dataclasses `MarketSnapshot`, `PriceZone`, `PriceLevel` e `PO3Event`.
- `mt5_reader.py` — conexão, leitura de candles, tick, conta e macro a partir do MT5.
- `macro.py` — retornos, direção, correlação, score, fatores e confiança macro.
- `levels.py` — níveis de contexto e zonas diárias.
- `book_rules.py` — detecção da sequência operacional da regra do livro.
- `engine.py` — checklist manual, cálculo de risco/retorno e mensagens de contexto.
- `ai_service.py` — configuração e chamadas ao OpenRouter.
- `external_data.py` — consolidação de calendário, notícias e cotações autorizadas.
- `investing_calendar.py` — leitura/parsing do calendário do Investing.com.
- `market_news.py` — manchetes e cotações externas autorizadas.
- `learning_store.py` — persistência local SQLite de análises, resultados e erros.
- `historical_training.py` — replay/avaliação histórica separado; não é usado pelo fluxo diário atual.
- `backtest.py`, `statistical_audit.py` e scripts auxiliares — análises estatísticas independentes.
- `demo_data.py` — snapshot simulado.
- `options_data.py` — CSV/opções públicas da B3.

Indicadores MT5:

- `mt5/PO3_D1_Objetivos_M15.mq5`
- `mt5/PO3_FVG_OB_M5.mq5`
- `mt5/PO3_Confluencia_M15_M5_M1.mq5`
- `mt5/PO3_Confluencia_M5_M1.mq5`
- `mt5/PO3_FVG_OB_Entrada_M5_M1.mq5`
- `mt5/PO3_Vacuum_Block_M15.mq5`

Testes:

- `tests/test_core.py`
- `tests/test_read_only.py`
- `tests/test_setup_area_rule.py`
- `tests/test_statistical_audit.py`
- `test_openrouter_connection.py`
- `test_setup_area.py`

## 3. Fluxo atual do painel principal

1. `macro_app.py` configura o Streamlit, CSS e estado da sessão.
2. O fragmento `live()` lê o snapshot com `read_snapshot(terminal, symbol)` ou usa `build_demo_snapshot()`.
3. O snapshot é renderizado com sinais por tempo, resumo macro, correlações, líderes, perguntas fixas, calendário e panorama.
4. O painel atualiza automaticamente conforme o intervalo configurado, mas a análise externa/IA ocorre sob solicitação.
5. `render_local_chat()` é renderizado após o painel e usa o snapshot mais recente guardado em `st.session_state`.

`app.py` possui fluxo próprio e mais antigo: lê/gera `MarketSnapshot`, calcula detecção PO3, renderiza gráficos Altair, checklist manual, opções e planejador de risco/retorno. Os dois pontos de entrada compartilham módulos de `po3`, mas não há um orquestrador único entre eles.

## 4. Fluxo atual do botão “Análise do dia”

Em `macro_app.py`, o botão executa:

1. `fetch_daily_context()` em `po3.external_data`.
2. Consulta/consolidação do calendário Investing, manchetes e cotações autorizadas.
3. Montagem de `_daily_analysis_prompt(snapshot, context)`, contendo ativo, preço, macro MT5, calendário, fontes e regras dos indicadores.
4. Chamada `send_message()` para o OpenRouter com instruções de português, estrutura fixa de três blocos e regras anti-alucinação.
5. Salvamento em `learning_store.save_analysis()`.
6. Armazenamento da resposta, horário e fontes em `st.session_state`.
7. Exibição da resposta e botão de voz.
8. Em falha, `record_ai_error()` registra erro de forma protegida e a interface continua aberta.

Os três blocos narrativos atuais são `MACROECONOMIA E DIA A DIA`, `IMPACTO NA BOLSA` e `INSIGHT OPERACIONAL`. Não existe uma etapa determinística anterior que produza seis decisões estruturadas.

## 5. Fluxo atual do chat com IA

`render_local_chat()`:

- mostra o histórico recente em `st.session_state`;
- aceita `st.chat_input()` ou perguntas fixas do painel;
- obtém contexto externo cacheado por `_external_context()`;
- serializa snapshot, candles recentes, níveis, macro, zonas e regras em `_ai_market_context()`;
- envia pergunta + JSON + calendário/fontes ao mesmo `send_message()` do OpenRouter;
- aplica um `system_instruction` que exige português, fontes permitidas, uso do símbolo atual, distinção entre fato/cálculo/inferência e regras dos indicadores;
- salva a pergunta/resposta com `save_analysis()`;
- não encaminha toda pergunta ao fluxo da análise do dia e não usa ainda decisões estruturadas.

Há também `_local_chat_answer()`, com respostas locais simples baseadas no snapshot, mas o caminho atual do chat visual usa OpenRouter quando a pergunta é enviada.

## 6. Integração com MT5

`po3.mt5_reader.read_snapshot()`:

- importa `MetaTrader5` sob demanda;
- valida o caminho do terminal;
- chama `mt5.initialize()` e confirma `terminal_info().connected`;
- lê conta somente para exibição (`account_info()`);
- lê candles D1, M15, M5 e M1; também W1 e MN1 para níveis;
- lê tick/preço atual;
- chama `build_context_levels()` e `build_daily_zones()`;
- calcula macro por M15, M30, H1, H4, W1 e MN1 via `build_macro()`;
- encerra com `mt5.shutdown()` no bloco `finally`.

Os dados são convertidos para horário `America/Sao_Paulo`. O `MarketSnapshot` é a representação atual mais próxima de um estado centralizado, mas é uma dataclass ampla e não possui validação de qualidade ou schema de decisão.

Os arquivos `.mq5` são indicadores executados no MT5 e não são chamados diretamente pelo Python. O Python recebe candles, níveis e cálculos próprios; a leitura detalhada das zonas dos indicadores não é um contrato JSON compartilhado entre MT5 e o Decision Engine.

## 7. Indicadores e regras preservadas

As regras dos indicadores ficam nos fontes `.mq5` e também são descritas parcialmente nos prompts/contextos:

- FVG, mitigação por fechamento, linha de 50%, nesting M1 e níveis de entrada/stop/alvos permanecem responsabilidades determinísticas do indicador/código.
- A IA recebe uma descrição textual das regras para interpretar o contexto, mas não deve recalcular ou inventar níveis.
- A futura arquitetura deve manter esses cálculos fora da LLM.

## 8. OpenRouter, modelo e fallback

`po3.ai_service` usa a API Chat Completions do OpenRouter via `urllib`, sem cliente externo adicional.

- URL: `https://openrouter.ai/api/v1/chat/completions`.
- Chave: `OPENROUTER_API_KEY`, carregada do ambiente/.env sem ser exibida.
- Timeout: `OPENROUTER_TIMEOUT_SECONDS`.
- Modelo configurável: `OPENROUTER_MODEL`.
- Modelo padrão declarado no código: `qwen/qwen3.8-27b:free`.
- Fallback: tupla `FREE_MODEL_PRIORITY`, somente modelos terminados em `:free`.
- O código envia lotes sequenciais com um modelo primário e até três modelos no campo `models`, respeitando a limitação observada do OpenRouter.
- Respostas vazias, HTTP, timeout, conexão e JSON inválido geram `OpenRouterError` controlado.

Ponto de atenção: o modelo realmente utilizado não é retornado pela função `send_message()` nem registrado no histórico. O painel mostra atualmente o modelo configurado, não necessariamente o fallback que respondeu. Além disso, `.env.example` ainda contém um valor de exemplo anterior e `load_config()` usa a primeira entrada de `FREE_MODEL_PRIORITY` quando não encontra `OPENROUTER_MODEL`; isso deve ser harmonizado em fase futura, sem expor a chave.

## 9. Prompts atuais

Os prompts estão embutidos em `macro_app.py`:

- `_daily_analysis_prompt()` monta o JSON da análise do dia.
- `_run_daily_analysis()` define instruções de narrativa e sistema.
- `render_local_chat()` define instruções do chat.
- `_ai_market_context()` define o JSON factual enviado ao chat.

As instruções atuais exigem português do Brasil, estrutura fixa, prioridade ao MT5, uso de fontes autorizadas, diferenciação fato/inferência, não invenção e decisão manual. Elas ainda misturam coleta, interpretação e narrativa em uma única chamada; não há prompt específico para saída JSON validada de decisões pequenas.

## 10. Calendário, notícias e fontes

`external_data.py` consolida:

- calendário via `investing_calendar.fetch_investing_calendar()`;
- filtro de eventos relevantes por termos, impacto e relação com WIN/DOL/juros;
- notícias por `market_news.fetch_market_headlines()`;
- cotações externas por `market_news.fetch_authorized_quotes()`.

O calendário faz parsing HTML/embutido do Investing.com e converte horários. Fontes externas possuem tratamento de erro e status. O fluxo usa cache Streamlit para calendário e contexto externo. A disponibilidade pode ser parcial; hoje isso é comunicado ao modelo por JSON, mas não existe um objeto formal `status_evidencias`.

## 11. Voz

`_render_audio_button()` em `macro_app.py` usa `streamlit.components.v1.html` e `window.speechSynthesis` local do navegador. Remove ícones/markdown simples antes de falar, configura português brasileiro e escolhe vozes disponíveis. Não envia o texto a um serviço de voz externo.

Ponto de atenção futuro: `components.v1` é uma API legada segundo a referência Streamlit; qualquer migração deve ser isolada e testada, pois a voz atual funciona.

## 12. Logs e histórico

Não há camada geral de logging estruturado Python. O histórico principal usa SQLite em `data/po3_learning.sqlite` por `po3.learning_store`:

- `analysis_runs`: análise, símbolo, preço, viés, resposta, contexto e snapshot.
- `outcomes`: resultado observado posterior, mantido para avaliação futura.
- `ai_error_events`: erros controlados, com proteção contra credenciais.

A serialização `_json()` trata referências circulares e objetos não serializáveis para não derrubar a análise. O registro é local; não altera prompts, modelos ou regras automaticamente.

## 13. Configurações e dependências

`requirements.txt` contém:

- `streamlit==1.62.0`;
- `MetaTrader5==5.0.6147`;
- `pandas>=2.2,<3.1`;
- `altair==6.2.2`.

`python-dotenv` é opcional: `ai_service.py` tenta usá-lo e possui leitura mínima de `.env` como fallback. Não há dependência separada de cliente OpenRouter.

`.env` existe localmente, mas não foi lido nem exposto nesta auditoria. `.gitignore` protege `.env`, `.env.*` (exceto `.env.example`), `.venv`, caches, relatórios e banco SQLite.

## 14. Testes existentes

- `tests/test_core.py`: zonas, checklist, R:R e detecção PO3.
- `tests/test_read_only.py`: verifica ausência de tokens de envio de ordens no Python.
- `tests/test_setup_area_rule.py`: regras de área/setup.
- `tests/test_statistical_audit.py`: simulação/auditoria estatística.
- `test_openrouter_connection.py`: teste isolado da conexão OpenRouter.
- `test_setup_area.py`: utilitários de setup.

Não existem testes para schema de decisão, saída JSON da LLM, qualidade de evidências, Decision Gate, consenso, segunda opinião ou registro do modelo efetivamente usado.

## 15. Dependências e duplicações observadas

Dependências principais:

`macro_app.py` → `mt5_reader`, `external_data`, `ai_service`, `learning_store`.

`mt5_reader` → `models`, `levels`, `macro`.

`external_data` → `investing_calendar`, `market_news`.

`app.py` → `models`, `mt5_reader`, `book_rules`, `engine`, `options_data`, `demo_data`.

Duplicações/pontos de atenção:

- dois entrypoints Streamlit e duas composições de interface;
- prompts e serializações de contexto concentrados no arquivo principal;
- regras dos indicadores descritas em mais de um local e parcialmente divergentes de nomes antigos;
- coleta diária e chat fazem chamadas de contexto em caminhos diferentes;
- fallback de modelos está no serviço, mas o modelo usado não acompanha a resposta;
- `historical_training.py` e scripts estatísticos são paralelos ao fluxo de produção.

## 16. Tratamento de erros

Há tratamento local para:

- terminal/MT5 ausente ou desconectado;
- histórico insuficiente;
- falhas HTTP, timeout, URLError e resposta vazia do OpenRouter;
- falhas de calendário/notícias/cotações;
- falhas SQLite e serialização circular;
- exceções do botão de análise sem derrubar o Streamlit.

A camada ainda não diferencia formalmente dados incompletos, conflitantes, desatualizados e indisponíveis para tomada de decisão. Essa é uma responsabilidade adequada para o futuro `DataValidator`/`DecisionGate`.

## 17. Execução automática de ordens

A auditoria não encontrou integração de execução automática de ordens.

- `mt5_reader.py` usa inicialização, leitura de terminal, conta, tick, candles e desligamento.
- Não há `mt5.order_send`, `positions_get` para execução, comandos de compra/venda ou API de negociação no Python.
- `engine.py`, `backtest.py` e scripts usam termos de operação apenas para cálculo, checklist ou simulação.
- Os indicadores `.mq5` desenham objetos e níveis; não há rotina de envio de ordens identificada.
- `tests/test_read_only.py` existe justamente para impedir tokens de submissão de ordens.

Portanto, o projeto atual é somente leitura/apoio à decisão; a decisão e a execução continuam manuais no MT5.

## 18. Pontos recomendados para a evolução

### MarketState

Introduzir entre `read_snapshot()`/`fetch_daily_context()` e os prompts. Um adaptador deve combinar snapshot MT5, calendário, notícias, cotações, regras, timestamp, símbolo e qualidade dos dados sem substituir `MarketSnapshot` imediatamente.

### Data Validator

Validar completude, atualidade, tipos, timezone, ativo e presença dos campos críticos antes de chamar a LLM. O resultado deve ser explícito, sem inventar valores.

### Decision Engine

Criar pacote independente que receba `MarketState` validado e execute seis decisões pequenas: regime macro, contexto doméstico, contexto técnico, risco de evento, conflito de contexto e contexto operacional. Cálculos verificáveis devem permanecer em Python.

### Decision Gate

Colocar após a validação das decisões e antes da narrativa. Deve produzir `VALIDO`, `REVISAO` ou `BLOQUEADO`, com mensagens em português e sem enviar ordens.

### Segunda análise

Adicionar somente após schema, validação e gate estarem estáveis. Deve receber o mesmo estado, sem receber a resposta da primeira análise, e ser acionada apenas em baixa confiança, conflito ou revisão.

### Narrative Engine

Separar depois que as decisões estruturadas estiverem validadas. A narrativa deve receber estado, decisões, gate e fontes; o prompt atual de três blocos deve ser preservado como contrato de apresentação.

## 19. Impacto previsto no painel

A integração futura deve ser incremental:

- manter o botão `Análise do dia` e o chat;
- construir o estado estruturado em paralelo;
- adicionar uma área compacta `Decisão estruturada`;
- manter voz, histórico, calendário, indicadores e perguntas fixas;
- permitir feature flag para comparar fluxo antigo e novo;
- não alterar o layout principal até validar a saída.

## 20. Riscos de regressão

1. Mudança de prompt pode alterar a narrativa atual ou misturar português/inglês.
2. Duplicação entre `MarketSnapshot` e `MarketState` pode gerar campos divergentes.
3. Fallback do OpenRouter pode ser confundido com modelo principal sem metadados de uso.
4. Chamadas adicionais de LLM podem aumentar latência, custo ou atingir limites gratuitos.
5. Dados externos podem estar indisponíveis ou atrasados e bloquear decisões.
6. Parsing do Investing.com é sensível a mudanças de HTML.
7. Atualizações automáticas do fragmento podem competir com ações do usuário.
8. Alterações na voz/`components.v1` podem quebrar o navegador.
9. SQLite pode falhar por bloqueio de arquivo ou caminho não gravável.
10. O segundo `app.py` pode ficar inconsistente se a nova arquitetura for ligada a apenas um entrypoint.

## 21. Arquivos prováveis da Fase 2

Criar, preferencialmente:

- `po3/decision_engine/market_state.py` ou adaptador equivalente;
- `po3/decision_engine/schemas.py`;
- `po3/decision_engine/validator.py`;
- testes unitários dos schemas e validação;
- `docs/DECISION_ENGINE.md` apenas quando a arquitetura for aprovada.

Arquivos provavelmente modificados na Fase 2, de forma incremental:

- `macro_app.py`, para montar o estado sem alterar inicialmente a narrativa;
- `po3/models.py`, caso o adaptador precise de tipos compartilhados;
- `po3/learning_store.py`, somente para campos estruturados após aprovação;
- `po3/ai_service.py`, somente se for necessário registrar modelo configurado/usado;
- `tests/`, para contratos novos.

Não modificar inicialmente:

- fontes `.mq5` e regras dos indicadores;
- `po3/mt5_reader.py`, salvo adapter não invasivo aprovado;
- `.env` e credenciais;
- fluxo de fallback sem teste específico;
- voz e layout principal.

## 22. Estratégia de migração recomendada

1. Criar a documentação e contratos de dados sem alterar o fluxo atual.
2. Implementar um adaptador `MarketState` somente leitura a partir do snapshot/contexto existentes.
3. Adicionar validação unitária com dados simulados.
4. Implementar schemas das seis decisões e validar respostas sem exibi-las.
5. Implementar o Decision Engine em modo paralelo/feature flag.
6. Implementar Decision Gate e mensagens de status.
7. Registrar modelo configurado/usado e decisões no histórico, sem segredos.
8. Criar segunda opinião somente em revisão/conflito.
9. Separar Narrative Engine mantendo exatamente os três blocos atuais.
10. Integrar no botão `Análise do dia` atrás de feature flag.
11. Executar regressão completa: MT5, calendário, notícias, chat, voz, histórico, fallback e contrato somente leitura.
12. Somente após validação, considerar ativação padrão.

## 23. Conclusão da Fase 1

A base atual é adequada para uma evolução incremental, mas o ponto central deve ser a criação de contratos estruturados entre dados, decisões e narrativa. O projeto não deve transformar a LLM em calculadora de preços/FVG nem em executor de ordens.

A Fase 1 está concluída com este relatório. MarketState, Decision Engine, Decision Gate, segunda opinião e Narrative Engine ainda não foram implementados.