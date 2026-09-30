#property strict
#property indicator_chart_window
#property indicator_plots 0
#property version   "1.00"
#property description "Vacuum Block do Capitulo 14 - leitura somente no M15"

input int      InpLookbackBars = 300;       // Barras fechadas analisadas
input int      InpExtendBars   = 80;        // Projecao da zona para a direita
input int      InpMinGapPoints = 2;         // Gap minimo em pontos
input double   InpImpulseATR   = 1.35;      // Deslocamento minimo relativo ao range medio
input int      InpImpulseBars  = 8;         // Janela do range medio
input bool     InpShowMidline  = true;      // Linha de 50% da zona
input bool     InpShowSignals  = true;      // Sinal de retorno/rejeicao
input bool     InpShowMitigated = true;     // Mostrar zonas historicas ja preenchidas
input int      InpMaxZones     = 20;        // Maximo de zonas desenhadas
input color    InpBullColor    = clrPaleGreen;
input color    InpBearColor    = clrMistyRose;
input color    InpMidColor     = clrSilver;

string PREFIX = "PO3_VB_M15_";

void DeleteObjects()
{
   ObjectsDeleteAll(0, PREFIX);
}

void SetRectangle(const string name, const datetime t1, const double p1,
                  const datetime t2, const double p2, const color clr)
{
   if(!ObjectCreate(0, name, OBJ_RECTANGLE, 0, t1, p1, t2, p2))
      return;
   ObjectSetInteger(0, name, OBJPROP_COLOR, clr);
   ObjectSetInteger(0, name, OBJPROP_STYLE, STYLE_SOLID);
   ObjectSetInteger(0, name, OBJPROP_WIDTH, 1);
   ObjectSetInteger(0, name, OBJPROP_FILL, true);
   ObjectSetInteger(0, name, OBJPROP_BACK, true);
   ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
   ObjectSetInteger(0, name, OBJPROP_HIDDEN, true);
}

void SetMidline(const string name, const datetime t1, const double mid,
                const datetime t2)
{
   if(!ObjectCreate(0, name, OBJ_TREND, 0, t1, mid, t2, mid))
      return;
   ObjectSetInteger(0, name, OBJPROP_COLOR, InpMidColor);
   ObjectSetInteger(0, name, OBJPROP_STYLE, STYLE_DOT);
   ObjectSetInteger(0, name, OBJPROP_WIDTH, 1);
   ObjectSetInteger(0, name, OBJPROP_RAY_RIGHT, false);
   ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
   ObjectSetInteger(0, name, OBJPROP_HIDDEN, true);
}

void SetSignal(const string name, const datetime t, const double price,
               const bool bullish)
{
   if(!ObjectCreate(0, name, bullish ? OBJ_ARROW_BUY : OBJ_ARROW_SELL, 0, t, price))
      return;
   ObjectSetInteger(0, name, OBJPROP_COLOR, bullish ? clrLimeGreen : clrTomato);
   ObjectSetInteger(0, name, OBJPROP_WIDTH, 1);
   ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
   ObjectSetInteger(0, name, OBJPROP_HIDDEN, true);
}

int OnInit()
{
   IndicatorSetString(INDICATOR_SHORTNAME, "PO3 Vacuum Block M15");
   if(_Period != PERIOD_M15)
      Print("PO3 Vacuum Block M15: anexe este indicador no grafico de 15 minutos.");
   return(INIT_SUCCEEDED);
}

void OnDeinit(const int reason)
{
   DeleteObjects();
}

int OnCalculate(const int rates_total, const int prev_calculated,
                const datetime &time[], const double &open[],
                const double &high[], const double &low[], const double &close[],
                const long &tick_volume[], const long &volume[], const int &spread[])
{
   if(_Period != PERIOD_M15 || rates_total < 10)
      return(rates_total);

   DeleteObjects();
   const int last = MathMin(InpLookbackBars, rates_total - 2);
   const int extension = MathMax(10, InpExtendBars);
   const datetime right_time = time[0] + (datetime)(PeriodSeconds(PERIOD_M15) * extension);
   const double min_gap = MathMax(0, InpMinGapPoints) * _Point;
   int zone_count = 0;

   // Series arrays: index 0 is the current bar; only closed bars are used.
   for(int i = last; i >= 1; i--)
   {
      const double range = high[i] - low[i];
      const double body = MathAbs(close[i] - open[i]);
      double average_range = 0.0;
      int average_count = 0;
      for(int k = i + 1; k <= MathMin(rates_total - 1, i + 1 + InpImpulseBars); k++)
      {
         average_range += high[k] - low[k];
         average_count++;
      }
      if(average_count > 0)
         average_range /= average_count;
      const bool impulse = average_range > 0.0 && range >= average_range * MathMax(1.0, InpImpulseATR)
                           && body >= range * 0.55;
      const bool bullish_gap = (low[i] - high[i + 1]) >= min_gap;
      const bool bearish_gap = (low[i + 1] - high[i]) >= min_gap;
      const bool bullish = bullish_gap || (impulse && close[i] > open[i]);
      const bool bearish = bearish_gap || (impulse && close[i] < open[i]);
      if(!bullish && !bearish)
         continue;

      double zone_low  = bullish ? high[i + 1] : high[i];
      double zone_high = bullish ? low[i] : low[i + 1];
      // Em deslocamento sem gap literal, o vacuum e o corredor entre
      // o extremo do candle anterior e o extremo do candle impulsivo.
      if(!bullish_gap && !bearish_gap && impulse)
      {
         if(bullish)
         {
            zone_low = low[i + 1];
            zone_high = high[i];
         }
         else
         {
            zone_low = low[i];
            zone_high = high[i + 1];
         }
      }
      if(zone_high <= zone_low)
         continue;
      bool mitigated = false;
      int mitigation_index = -1;
      for(int j = i - 1; j >= 1; j--)
      {
         if(high[j] >= zone_low && low[j] <= zone_high)
         {
            mitigated = true;
            mitigation_index = j;
            break;
         }
      }
      if(mitigated && !InpShowMitigated)
         continue;

      zone_count++;
      if(zone_count > MathMax(1, InpMaxZones))
         break;
      const string id = IntegerToString(zone_count);
      const string zone_name = PREFIX + "ZONE_" + id;
      const datetime zone_right = mitigated ? time[mitigation_index] : right_time;
      const color zone_color = mitigated
         ? (bullish ? clrDarkSeaGreen : clrLightCoral)
         : (bullish ? InpBullColor : InpBearColor);
      SetRectangle(zone_name, time[i + 1], zone_high, zone_right, zone_low, zone_color);
      if(InpShowMidline)
         SetMidline(PREFIX + "MID_" + id, time[i + 1], (zone_low + zone_high) / 2.0, zone_right);

      // A return/rejection is a visual alert only; it never submits an order.
      if(InpShowSignals && i == 1)
      {
         const double mid = (zone_low + zone_high) / 2.0;
         const bool rejection = bullish
            ? (low[1] <= zone_high && close[1] > mid && close[1] > open[1])
            : (high[1] >= zone_low && close[1] < mid && close[1] < open[1]);
         if(rejection)
            SetSignal(PREFIX + "SIGNAL_" + id, time[1], bullish ? low[1] : high[1], bullish);
      }
   }
   ChartRedraw(0);
   return(rates_total);
}
