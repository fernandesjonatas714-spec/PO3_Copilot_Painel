from pathlib import Path
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, Image, KeepTogether
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase import pdfmetrics

ROOT = Path(__file__).resolve().parent
OUT = ROOT.parent / "Guia_Indicadores_PO3_MT5"
OUT.mkdir(parents=True, exist_ok=True)
PDF = OUT / "Guia_Indicadores_PO3_MT5.pdf"
IMG_CONFL = Path(r"C:\Users\JONATAS\AppData\Local\Temp\codex-clipboard-8d9e7951-675a-4c85-b5dd-f44b17a47feb.png")
IMG_LEVELS = Path(r"C:\Users\JONATAS\AppData\Local\Temp\codex-clipboard-b94e3e68-b326-4d87-a62e-498b1de89c8c.png")

NAVY = colors.HexColor("#111827")
INK = colors.HexColor("#202938")
MUTED = colors.HexColor("#5B6678")
LIGHT = colors.HexColor("#F3F5F8")
BULL_CONFL = colors.HexColor("#5ABE96")
BEAR_CONFL = colors.HexColor("#DC8791")
BULL_ZONE = colors.HexColor("#69AFE6")
BEAR_ZONE = colors.HexColor("#EB7D87")
MID_CONFL = colors.HexColor("#DCDCDC")
MID_ZONE = colors.HexColor("#CDCDCD")

styles = getSampleStyleSheet()
styles.add(ParagraphStyle(name="CoverTitle", parent=styles["Title"], fontName="Helvetica-Bold", fontSize=25, leading=30, textColor=colors.white, alignment=TA_CENTER, spaceAfter=12))
styles.add(ParagraphStyle(name="CoverSub", parent=styles["Normal"], fontSize=12, leading=17, textColor=colors.HexColor("#D9E2F0"), alignment=TA_CENTER))
styles.add(ParagraphStyle(name="H1x", parent=styles["Heading1"], fontName="Helvetica-Bold", fontSize=18, leading=23, textColor=NAVY, spaceBefore=8, spaceAfter=10))
styles.add(ParagraphStyle(name="H2x", parent=styles["Heading2"], fontName="Helvetica-Bold", fontSize=13, leading=17, textColor=INK, spaceBefore=8, spaceAfter=6))
styles.add(ParagraphStyle(name="Bodyx", parent=styles["BodyText"], fontSize=9.5, leading=14, textColor=INK, spaceAfter=6))
styles.add(ParagraphStyle(name="Smallx", parent=styles["BodyText"], fontSize=8, leading=11, textColor=MUTED, spaceAfter=4))
styles.add(ParagraphStyle(name="Callout", parent=styles["BodyText"], fontSize=10, leading=14, textColor=INK, backColor=LIGHT, borderColor=colors.HexColor("#D9DEE8"), borderWidth=.5, borderPadding=8, spaceBefore=6, spaceAfter=8))

def P(text, style="Bodyx"):
    return Paragraph(text, styles[style])

def bullets(items):
    return KeepTogether([P("- " + x) for x in items])

def color_table(rows, widths=None):
    t = Table(rows, colWidths=widths, hAlign="LEFT")
    t.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), NAVY), ("TEXTCOLOR", (0,0), (-1,0), colors.white),
        ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"), ("FONTSIZE", (0,0), (-1,-1), 8.5),
        ("LEADING", (0,0), (-1,-1), 11), ("GRID", (0,0), (-1,-1), .35, colors.HexColor("#D9DEE8")),
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"), ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, LIGHT]),
        ("TOPPADDING", (0,0), (-1,-1), 6), ("BOTTOMPADDING", (0,0), (-1,-1), 6),
    ]))
    return t

def swatch(hexcolor, label):
    t = Table([["", label]], colWidths=[.65*cm, 5.2*cm], rowHeights=[.5*cm])
    t.setStyle(TableStyle([("BACKGROUND", (0,0), (0,0), colors.HexColor(hexcolor)), ("BOX", (0,0), (0,0), .3, colors.HexColor("#9099A8")), ("TEXTCOLOR", (1,0), (1,0), INK), ("FONTSIZE", (1,0), (1,0), 8.5), ("VALIGN", (0,0), (-1,-1), "MIDDLE")]))
    return t

def footer(canvas, doc):
    canvas.saveState()
    canvas.setStrokeColor(colors.HexColor("#D9DEE8")); canvas.line(1.6*cm, 1.25*cm, 19.4*cm, 1.25*cm)
    canvas.setFont("Helvetica", 7.5); canvas.setFillColor(MUTED)
    canvas.drawString(1.6*cm, .85*cm, "PO3 Copilot B3 - Guia de uso dos indicadores MT5")
    canvas.drawRightString(19.4*cm, .85*cm, f"Página {doc.page}")
    canvas.restoreState()

story = []
story += [Spacer(1, 3.0*cm), P("PO3 Copilot B3", "CoverTitle"), P("Guia prático dos indicadores gráficos para MetaTrader 5", "CoverSub"), Spacer(1, .7*cm), P("WIN - leitura de contexto, confluência e entrada", "CoverSub"), Spacer(1, 8.0*cm), P("Versão baseada nos arquivos MQ5 reais do projeto e nos exemplos visuais do gráfico do MT5.", "CoverSub"), PageBreak()]

story += [P("Como ler esta apostila", "H1x"), P("Os três indicadores são ferramentas de leitura visual. Eles desenham zonas e níveis no gráfico, mas não enviam ordens, não executam robôs e não substituem a decisão do operador.")]
story += [P("Fluxo recomendado", "H2x"), color_table([["Tempo", "Indicador", "Função principal"], ["D1", "PO3 D1 Objetivos M15", "Mapear FVGs e Order Blocks diários ainda ativos."], ["M15", "PO3 D1 Objetivos M15", "Projetar no M15 as zonas de objetivo do diário."], ["M5", "PO3 Confluência M5 M1", "Encontrar a zona M5 que recebe confirmação do M1."], ["M1", "PO3 Confluência M5 M1", "Confirmar a confluência e visualizar entrada, stop e alvos."], ["M5/M1", "PO3 FVG OB Entrada M5 M1", "Mostrar FVGs e OBs ativos do próprio tempo gráfico, sem exigir confluência."]], [2*cm, 5.5*cm, 10.3*cm]), Spacer(1, .2*cm)]
story += [P("Regra de segurança", "H2x"), P("Uma marcação no gráfico é uma hipótese de contexto. Antes de operar, confirme direção, liquidez, horário, risco financeiro e o comportamento do preço dentro da zona. O indicador não conhece regras específicas da sua mesa proprietária.", "Callout"), P("Cores usadas no código", "H2x")]
story += [Table([[swatch("#5ABE96", "Confluência de compra"), swatch("#DC8791", "Confluência de venda")], [swatch("#69AFE6", "Zona de compra D1/entrada"), swatch("#EB7D87", "Zona de venda D1/entrada")], [swatch("#DCDCDC", "Linha de 50% da confluência"), swatch("#CDCDCD", "Linha de 50% D1/entrada")]], colWidths=[8.8*cm, 8.8*cm], style=TableStyle([("VALIGN", (0,0), (-1,-1), "MIDDLE"), ("BOTTOMPADDING", (0,0), (-1,-1), 5)])), PageBreak()]

story += [P("1. PO3 D1 Objetivos M15", "H1x"), P("Este indicador trabalha nos gráficos D1 e M15. Ele lê candles diários já fechados e procura duas estruturas: Fair Value Gap e Order Block. As zonas são projetadas para a direita, para mostrar onde a distribuição pode buscar liquidez ou desequilíbrio.")]
story += [P("O que ele desenha", "H2x"), bullets(["Retângulo azul claro: FVG ou OB de compra.", "Retângulo vermelho claro: FVG ou OB de venda.", "Linha pontilhada cinza: 50% da zona.", "Texto da zona: tipo, D1, direção e 50%.", "Somente as zonas ainda não tocadas pelo histórico posterior são mantidas."])]
story += [P("Como interpretar", "H2x"), bullets(["No D1, use as zonas para enxergar o mapa maior e os possíveis objetivos.", "No M15, a zona não é um ponto de entrada. Ela é uma área de interesse projetada do diário.", "Se o preço atravessar ou mitigar a zona, ela pode desaparecer na próxima reconstrução.", "A linha de 50% é referência de equilíbrio da área; não é uma ordem automática."])]
story += [P("Parâmetros reais do arquivo", "H2x"), color_table([["Parâmetro", "Valor padrão", "Efeito visual"], ["Lookback D1", "120 dias", "Quantidade de candles diários analisados."], ["Máximo de zonas", "6", "Limita a poluição do gráfico."], ["Projeção", "20 dias", "Extensão do retângulo para a direita."], ["Rótulos", "Ligados", "Exibe tipo, direção e 50%."], ["Atualização", "A cada 10 s", "Reconstrói as zonas enquanto o indicador está anexado."]], [4.5*cm, 3*cm, 10.3*cm]), PageBreak()]

story += [P("Exemplo real do gráfico", "H2x")]
if IMG_LEVELS.exists():
    story += [Image(str(IMG_LEVELS), width=16.7*cm, height=10.9*cm), P("Exemplo enviado do MT5: níveis visualizados no gráfico de 5 minutos. A imagem é usada como referência visual de leitura, não como prova de resultado financeiro.", "Smallx")]
story += [P("2. PO3 Confluência M5 M1", "H1x"), P("Este é o indicador de confirmação entre tempos. Ele cria zonas no M5 e no M1 e só marca uma confluência quando a zona do M1 surge depois, na mesma direção e dentro da faixa de preço da zona M5.")]
story += [P("As quatro combinações aceitas", "H2x"), color_table([["Zona M5", "Zona M1", "Leitura"], ["OB compra", "OB compra", "Confluência compradora"], ["OB compra", "FVG compra", "Confluência compradora"], ["FVG venda", "OB venda", "Confluência vendedora"], ["FVG venda", "FVG venda", "Confluência vendedora"]], [4*cm, 4*cm, 9.8*cm]), P("O código exige direção igual e sobreposição de preço. Uma zona M1 fora da área M5 não é desenhada como confluência.", "Callout")]
story += [P("Como usar", "H2x"), bullets(["No M5, observe a faixa colorida como área principal de contexto.", "No M1, espere a formação da segunda zona dentro da área do M5.", "Compra aparece em verde; venda aparece em rosa.", "A linha pontilhada indica 50% da faixa M5 desenhada.", "A configuração padrão limita a uma confluência visível, reduzindo sobreposição de zonas."])]
story += [P("Níveis de operação no M1", "H2x"), bullets(["Entrada: calculada a partir do fechamento encontrado no M1 no momento da confluência.", "Stop: além do limite da zona M5, com buffer configurável em pontos.", "Alvos: cinco níveis, de 1R a 5R.", "Valor em reais: depende do tick e do valor do tick informados pelo símbolo no MT5 e do volume configurado.", "Esses níveis são referências gráficas. O código não envia ordens nem garante execução no preço mostrado."]), PageBreak()]

story += [P("Exemplo real do gráfico", "H2x")]
if IMG_CONFL.exists():
    story += [Image(str(IMG_CONFL), width=11.5*cm, height=14.9*cm), P("Exemplo enviado do MT5 com a faixa e o rótulo de confluência M5+M1. A cor verde corresponde ao valor real C'90,190,150' usado no arquivo.", "Smallx")]
story += [P("3. PO3 FVG OB Entrada M5 M1", "H1x"), P("Este indicador é diferente do indicador de confluência. Ele funciona de forma independente no M5 ou no M1 e desenha as zonas formadas pelo próprio tempo gráfico. Portanto, ele pode mostrar uma zona mesmo sem haver confirmação entre M5 e M1.")]
story += [P("O que ele desenha", "H2x"), bullets(["FVG de compra ou venda no tempo gráfico atual.", "Order Block formado por candle oposto seguido de impulso.", "Retângulo projetado para a direita.", "Linha pontilhada de 50%.", "Rótulo com tipo, tempo gráfico, direção e 50%." ])]
story += [P("Quando usar", "H2x"), bullets(["Use no M5 para mapear as zonas locais de estrutura.", "Use no M1 para enxergar zonas de entrada locais.", "Compare com o M5 maior e descarte marcações que estejam contra a área principal.", "Se quiser somente confluência, prefira o indicador PO3 Confluência M5 M1."])]
story += [P("Parâmetros reais", "H2x"), color_table([["Parâmetro", "Valor padrão", "Uso"], ["Lookback", "300 candles", "Janela analisada no tempo atual."], ["Máximo de zonas", "8", "Quantidade de retângulos visíveis."], ["Projeção", "120 candles", "Extensão para a direita."], ["Atualização", "A cada 5 s", "Reconstrói o desenho."], ["Cores", "Azul/vermelho claros", "Mesmas cores dos objetivos D1."]], [4.5*cm, 3*cm, 10.3*cm]), PageBreak()]

story += [P("Leitura operacional combinada", "H1x"), P("A sequência abaixo organiza os três indicadores sem transformar a leitura em sinal automático.")]
story += [color_table([["Etapa", "Pergunta", "Indicador"], ["1. Mapa", "Existe uma zona diária ativa acima ou abaixo do preço?", "PO3 D1 Objetivos M15"], ["2. Contexto", "O preço está chegando ou reagindo nessa região no M15?", "Zona projetada no M15"], ["3. Estrutura", "Formou uma zona local no M5?", "PO3 FVG OB Entrada M5 M1"], ["4. Confirmação", "O M1 formou zona do mesmo sentido dentro da área M5?", "PO3 Confluência M5 M1"], ["5. Risco", "Entrada, stop e alvos cabem no risco permitido?", "Conferência manual"], ["6. Execução", "O preço confirmou o plano e o horário é válido?", "Operador"]], [2*cm, 10*cm, 5.8*cm]), Spacer(1, .3*cm)]
story += [P("O que significa uma zona ativa", "H2x"), P("Ativa significa que, segundo a regra do código, os candles posteriores ainda não atravessaram a faixa. Isso não significa que a zona tenha alta probabilidade, que o preço vá retornar ou que a operação deva ser feita.")]
story += [P("O que significa 50%", "H2x"), P("É o ponto médio matemático entre o limite inferior e o superior da zona. Pode ser usado como referência de equilíbrio, reação ou gerenciamento, mas não foi programado como gatilho isolado.")]
story += [P("Checklist antes de considerar uma operação", "H2x"), bullets(["A direção da zona está alinhada com o contexto maior?", "A zona M1 surgiu depois da zona M5?", "As duas zonas estão realmente na mesma área de preço?", "O stop além do M5 respeita o limite financeiro?", "O valor por ponto e o tick do WIN estão corretos no MT5?", "O alvo escolhido é compatível com liquidez e horário?", "A decisão foi confirmada manualmente?"]), PageBreak()]

story += [P("Limitações importantes", "H1x"), bullets(["O indicador usa candles OHLC e não enxerga todo o fluxo intrabar.", "A marcação pode mudar quando uma nova barra fecha ou quando a zona é mitigada.", "O cálculo de valor em reais depende das propriedades do símbolo no MT5. Se o corretor devolver tick value incorreto ou zero, os valores podem não aparecer.", "O indicador não conhece slippage, fila, rejeição, spread, zeragem compulsória ou regras da mesa.", "A leitura de FVG e OB é uma formalização objetiva do código, não uma interpretação completa de todas as variações do livro.", "Nenhum indicador garante acerto, aprovação em mesa ou resultado positivo."])]
story += [P("Cores e origem visual", "H2x"), P("As cores desta apostila foram transcritas dos valores de entrada dos três arquivos MQ5. Os exemplos de gráfico são capturas reais fornecidas na conversa. Quando o MT5 estiver em outra escala, o mesmo retângulo pode parecer mais forte ou mais fraco, mas a cor-base permanece a mesma.")]
story += [P("Resumo de bolso", "H2x"), color_table([["Indicador", "Lembrete"], ["D1 Objetivos M15", "Mapa maior: zonas diárias e 50%."], ["Confluência M5 M1", "Só confirma quando M1 nasce dentro da zona M5 e no mesmo sentido."], ["FVG OB Entrada M5 M1", "Zonas locais do próprio tempo, sem exigir confluência."], ["Todos", "Leitura visual, decisão manual, sem envio de ordens."]], [6.3*cm, 11.5*cm]), Spacer(1, .3*cm), P("Documentação preparada a partir dos códigos MQ5 do projeto, sem alterar os indicadores. Consulte sempre o gráfico atual e as propriedades do símbolo antes de operar.", "Smallx")]

doc = SimpleDocTemplate(str(PDF), pagesize=A4, rightMargin=1.6*cm, leftMargin=1.6*cm, topMargin=1.5*cm, bottomMargin=1.7*cm, title="Guia de Indicadores PO3 MT5", author="PO3 Copilot B3")
doc.build(story, onFirstPage=footer, onLaterPages=footer)
print(PDF)
