# Decision Engine V1

## Objetivo

O Decision Engine organiza o contexto do mercado antes da narrativa. Ele não replica o JEV nem afirma usar sua arquitetura proprietária; é uma camada própria do PO3 Copilot, inspirada apenas no princípio de decisões pequenas, restritas e auditáveis.

Fluxo:

`MT5 + fontes autorizadas -> MarketState -> validação -> seis decisões -> Decision Gate -> segunda análise quando necessário -> consenso -> Narrative Engine -> Streamlit`

## Responsabilidades

- Python normaliza, calcula, valida e controla.
- A LLM interpreta contexto e classifica somente opções permitidas.
- O Decision Gate aceita, envia para revisão ou bloqueia.
- O usuário mantém a decisão operacional final.

## MarketState

`MarketState` é um adaptador não destrutivo de `MarketSnapshot` e do contexto externo. Reúne ativo, timestamp, preço, candles, níveis, zonas, macro MT5, calendário, notícias, cotações, fontes e qualidade dos dados. Ausências são preservadas como `None`, listas vazias ou status explícito.

## Validação

A validação classifica os dados como:

- Válidos
- Parciais
- Insuficientes
- Desatualizados

MT5 desconectado, preço ausente, ativo ausente, timestamp inválido ou dados desatualizados podem bloquear a análise estruturada. O calendário indisponível fica registrado como dado ausente.

## Seis decisões

1. Regime macro — CHOICE.
2. Contexto doméstico — CHOICE.
3. Contexto técnico — CHOICE.
4. Risco de evento — SCORE de 0 a 10.
5. Conflito de contexto — NOUL (SIM/NÃO).
6. Contexto operacional — CHOICE.

Contexto comprador/vendedor não é ordem de compra/venda. SCORE não é probabilidade de acerto.

## Saída estruturada

Cada decisão é validada antes de ser usada. São aceitos somente os tipos, opções, confiança e status de evidências definidos em `schemas.py`. Resposta JSON inválida não vira decisão.

## Decision Gate

- `VALIDO`: dados e decisões estruturadas adequados.
- `REVISAO`: confiança baixa, conflito ou dados parciais.
- `BLOQUEADO`: ausência de condições mínimas ou resposta inválida.

`SEM_SETUP` é uma classificação operacional possível e não deve ser confundida com `BLOQUEADO`.

## Segunda análise e consenso

Quando há revisão necessária ou confiança baixa, o mesmo `MarketState` é enviado a uma segunda chamada independente. Decisões iguais geram consenso; diferentes geram divergência e revisão recomendada.

## Narrative Engine

A narrativa recebe o estado, as decisões, o gate e o consenso. Continua produzindo exatamente os três blocos atuais:

- MACROECONOMIA E DIA A DIA
- IMPACTO NA BOLSA
- INSIGHT OPERACIONAL

A narrativa não pode alterar decisões estruturadas, inventar dados ou emitir ordens.

## OpenRouter

O serviço continua aceitando somente modelos `:free`. O modelo configurado e o modelo realmente utilizado são registrados no resultado seguro da chamada. Nenhuma chave ou token é gravado.

## Feature flag

`DECISION_ENGINE_ENABLED=true` ativa o fluxo novo. `false` retorna ao fluxo narrativo anterior. O fluxo antigo permanece como fallback se uma etapa estruturada falhar.

## Histórico e segurança

O objeto estruturado é incluído no contexto salvo pelo `learning_store`, mantendo compatibilidade com registros antigos. A chave `OPENROUTER_API_KEY` permanece somente no ambiente. O MT5 continua somente leitura; não existe envio automático de ordens.