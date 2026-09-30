# PO3 Copilot B3 — Painel local

Painel Streamlit somente leitura para acompanhar o PO3 no WIN pela sequência:

**M15 contexto → M5 estrutura → M1 entrada.**

## Segurança

- Não solicita login ou senha.
- Não possui comandos de negociação.
- Não transmite dados para serviços externos.
- A decisão e a execução permanecem manuais no MT5.

## Instalação

1. Execute `instalar_painel.cmd` uma vez.
2. Na Área de Trabalho, abra o atalho **PO3 Copilot B3** sempre que quiser operar. Ele abre o **Painel Macro WIN**.
3. Deixe o MT5 aberto no WIN; o painel inicia em **MT5 local — somente leitura**.
4. Se o terminal não estiver disponível, selecione **Demonstração** para conhecer a tela.

O endereço local padrão é `http://127.0.0.1:8501`.

## Rotina durante o pregão

- Abra primeiro o MT5 e deixe o WIN visível e conectado.
- Abra o atalho **PO3 Copilot B3**. O painel lê D1, M15, M5, M1 e a conta em modo somente leitura.
- A atualização automática fica ligada por padrão e o painel mostra o horário da última leitura.
- Para parar a coleta, feche a janela preta que foi aberta junto com o painel. Fechar somente a aba do navegador pode deixar o processo ativo.

O MT5 é a fonte principal. Uma fonte externa só deve ser usada quando o dado do MT5 estiver ausente ou atrasado, e sempre será exibida no painel com sua origem e horário. Não são usados valores inventados nem fontes não identificadas.

## Estrutura

- `app.py`: interface Streamlit.
- `macro_app.py`: interface principal do Painel Macro WIN.
- `iniciar_painel_macro.cmd`: inicializador usado pelo atalho da Área de Trabalho.
- `po3/mt5_reader.py`: leitura local do MT5.
- `po3/levels.py`: cálculo dos níveis anteriores.
- `po3/engine.py`: checklist e risco/retorno.
- `po3/book_rules.py`: sequência automática baseada na Regra Mestre.
- `po3/macro.py`: score macro do WIN, correlações e confiança usando os símbolos disponíveis no MT5.
- `po3/demo_data.py`: dados simulados para teste.
- `tests/`: testes funcionais e contrato de somente leitura.

Consulte `REGRA_MESTRE_PO3.md` para a separação entre regra do livro e parâmetros experimentais, e `PLANO.md` para escopo, critérios de aceitação e riscos.

O painel identifica automaticamente o **Single Candle Order Block** de alta ou baixa e o classifica como fraco, bom ou excelente. O Mitigation Block permanece manual e separado até sua própria validação.

## Painel macro

A aba **Macro e opções** calcula um score de -100 a +100 com B3, dólar, juros, exterior, volatilidade e commodities quando esses símbolos existem no MT5. Cada fator mostra símbolo, direção, correlação e contribuição. Símbolos ausentes ficam visíveis como indisponíveis e não são substituídos por estimativas.

O score é um filtro de contexto. Ele não envia ordens, não substitui o setup técnico e não deve ser interpretado como previsão garantida. A integração com fontes externas oficiais será adicionada apenas para dados com endpoint e horário identificados.
