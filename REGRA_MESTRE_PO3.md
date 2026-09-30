# Regra Mestre PO3 — baseada nas páginas 276–281

## Regra do livro

1. **Acumulação:** preço lateral em faixa estreita, próximo da abertura, formando liquidez acima e abaixo.
2. **Manipulação:** falso rompimento de uma extremidade da faixa, também chamado de Judas Swing.
3. **Confirmação da reversão:** rejeição por candle e/ou Market Structure Shift (MSS) no sentido contrário ao falso rompimento.
4. **Distribuição:** expansão direcional com estrutura de máximas e mínimas coerente com a direção.
5. **Retorno:** preço volta a uma zona de interesse criada na movimentação, como FVG ou Order Block.
6. **Continuidade:** a entrada somente é considerada após confirmação da retomada da distribuição.
7. **Proteção e objetivo:** stop além da manipulação; alvo em liquidez anterior na direção do movimento.

## Aplicação no painel

- **D1:** mapa de objetivos da distribuição, com FVGs e Order Blocks ainda ativos.
- **M15:** faixa de acumulação, contexto semanal/mensal e projeção dos objetivos D1.
- **M5:** falso rompimento, MSS e deslocamento; níveis do pregão anterior.
- **M1:** FVG, reteste e confirmação de continuidade.
- **Order Block:** detecção automática inicial do Single Candle Order Block no D1 e no M1.
- **Mitigation Block:** permanece separado e manual nesta versão.
- **Execução:** sempre manual; o painel não contém comandos de negociação.

## Adaptações experimentais para a B3

O livro descreve alguns critérios de forma qualitativa. Para que o computador consiga medi-los, o painel expõe cinco parâmetros que precisam de backtest:

- quantidade de candles M15 que forma a janela inicial;
- amplitude máxima da faixa em relação ao ATR típico;
- quantidade de candles M5 usada para definir a estrutura rompida no MSS;
- tamanho mínimo do candle de deslocamento em relação ao corpo típico.
- agressão mínima do Order Block excelente em relação ao corpo típico.

Esses parâmetros não são apresentados como números definitivos do livro. O padrão inicial é conservador e deve ser validado em pelo menos 20 pregões de WIN antes de qualquer confiança operacional.

## Regra do Order Block — páginas 89–93

1. O Single Candle Order Block é o último candle contrário antes do movimento forte.
2. Para compra, procura-se o último candle de baixa antes da expansão compradora.
3. Para venda, procura-se o último candle de alta antes da expansão vendedora.
4. O bloco deve estar no ponto de interesse formado após a captura de liquidez e antes do deslocamento.
5. **Validação fraca:** houve apenas rompimento do candle.
6. **Validação boa:** a expansão alcançou pelo menos duas vezes a amplitude total do candle.
7. **Validação excelente:** além da projeção de duas vezes, houve agressão bem superior ao corpo típico recente.
8. O retorno à zona precisa apresentar candle de confirmação na direção da distribuição.

## Objetivos de distribuição no D1

1. São analisados somente candles diários fechados.
2. FVGs e Order Blocks não mitigados são projetados como zonas no M15.
3. O M15 usa essas zonas como destinos potenciais junto da liquidez, sem transformar qualquer zona em alvo automático.
4. Zonas tocadas por candles posteriores são consideradas mitigadas e deixam de ser exibidas.

A zona usada nesta primeira versão compreende toda a amplitude do candle, incluindo pavios. Essa escolha é conservadora e será comparada com corpo e 50% do candle no backtest.
