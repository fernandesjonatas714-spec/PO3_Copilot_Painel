# Plano — PO3 Copilot B3

## Objetivo

Disponibilizar um painel Streamlit local que leia candles do MT5 e organize a análise PO3 em M15, M5 e M1, sem executar operações.

## Não objetivos da V1

- Não enviar, alterar ou cancelar ordens.
- Não armazenar login ou senha.
- Não chamar serviços de IA ou transmitir dados para a internet.
- Não transformar detecções experimentais em ordens ou recomendações automáticas.

## Entregáveis e estado

- **Concluído:** interface local escura e responsiva.
- **Concluído:** modo demonstração independente do MT5.
- **Concluído:** leitor MT5 somente para candles e cotação.
- **Concluído:** níveis semanais/mensais no M15 e diários no M5.
- **Concluído:** M1 reservado para entrada de alta precisão.
- **Concluído:** checklist manual e cálculo de risco/retorno.
- **Concluído:** dependências instaladas em ambiente virtual local e isolado.
- **Concluído:** conexão real validada com o WINV26 no MT5 aberto.
- **Concluído:** Regra Mestre documentada a partir das páginas 276–281 do livro.
- **Concluído:** motor experimental de acumulação, sweep, MSS, deslocamento, FVG e reteste.
- **Concluído:** Single Candle Order Block de alta e baixa com validação fraca, boa e excelente.
- **Pendente:** calibrar os quatro parâmetros experimentais em pelo menos 20 pregões.
- **Pendente:** comparar zona completa, corpo e 50% do candle no backtest.
- **Pendente:** automatizar Mitigation Block em módulo separado.

## Critérios de aceitação

1. Aplicativo inicia em modo MT5 somente leitura e oferece demonstração como alternativa.
2. M15 mostra seis níveis semanais/mensais.
3. M5 mostra cinco níveis do pregão anterior.
4. M1 não recebe níveis automáticos.
5. Não existe API de envio de ordens no código da aplicação.
6. Testes automatizados passam.
7. Conexão real funciona sem senha no código quando o MT5 está aberto.
8. Leitura automática usa apenas candles concluídos.
9. Tela distingue regra do livro de parâmetros experimentais da B3.
10. Order Block exige sweep, MSS e deslocamento antes de ser exibido.
11. Validação boa exige projeção mínima de duas vezes a amplitude do candle.

## Riscos e mitigação

- **Histórico insuficiente:** mostrar erro claro e manter modo demonstração.
- **Contrato vencido:** permitir alterar o símbolo pela barra lateral.
- **Falso sinal:** checklist permanece manual até o backtest validar parâmetros.
- **Dependências Python:** usar ambiente virtual isolado dentro do projeto.
