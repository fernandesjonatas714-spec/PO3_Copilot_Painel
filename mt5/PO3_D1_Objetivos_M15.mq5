#property strict
#property indicator_chart_window
#property indicator_plots 0

input int   InpLookbackBars   = 400;
input int   InpMaxZones       = 6;
input int   InpProjectionBars = 80;
input color InpBullColor      = C'105,175,230';
input color InpBearColor      = C'235,125,135';
input color InpMidlineColor   = C'0,0,0';

struct D1Zone
  {
   string   kind;
   string   direction;
   double   lower;
   double   upper;
   datetime created;
  };

string PREFIX = "PO3_D1_OBJ_";
datetime last_chart_bar = 0;

bool IsUntouched(const MqlRates &rates[],const int start,const int count,const double lower,const double upper,const string direction)
  {
   for(int i=start; i<count; i++)
     {
      // Toque/pavio não mitiga; somente fechamento além do limite invalida.
      if(direction=="COMPRA" && rates[i].close<lower)
         return false;
      if(direction=="VENDA" && rates[i].close>upper)
         return false;
     }
   return true;
  }

void AddZone(D1Zone &zones[],const string kind,const string direction,const double lower,const double upper,const datetime created)
  {
   const int size=ArraySize(zones);
   ArrayResize(zones,size+1);
   zones[size].kind=kind;
   zones[size].direction=direction;
   zones[size].lower=lower;
   zones[size].upper=upper;
   zones[size].created=created;
  }

void SortNewestFirst(D1Zone &zones[])
  {
   for(int i=0; i<ArraySize(zones)-1; i++)
      for(int j=i+1; j<ArraySize(zones); j++)
         if(zones[j].created>zones[i].created)
           {
            D1Zone swap=zones[i];
            zones[i]=zones[j];
            zones[j]=swap;
           }
  }

void DeleteOurObjects()
  {
   for(int i=ObjectsTotal(0,0,-1)-1; i>=0; i--)
     {
      const string name=ObjectName(0,i,0,-1);
      if(StringFind(name,PREFIX)==0)
         ObjectDelete(0,name);
     }
  }

void DrawZone(const D1Zone &zone,const int index,const datetime right_time)
  {
   const string name=PREFIX+IntegerToString(index)+"_"+zone.kind;
   // FVGs usam amarelo claro; OBs mantêm a cor direcional.
   const color zone_color=(zone.kind=="FVG" ? C'255,255,197' : (zone.direction=="COMPRA" ? InpBullColor : InpBearColor));
   if(!ObjectCreate(0,name,OBJ_RECTANGLE,0,zone.created,zone.upper,right_time,zone.lower))
      return;
   ObjectSetInteger(0,name,OBJPROP_COLOR,zone_color);
   ObjectSetInteger(0,name,OBJPROP_FILL,true);
   ObjectSetInteger(0,name,OBJPROP_BACK,false);
   ObjectSetInteger(0,name,OBJPROP_WIDTH,2);
   ObjectSetInteger(0,name,OBJPROP_SELECTABLE,false);
   ObjectSetInteger(0,name,OBJPROP_HIDDEN,false);
   const string midpoint_name=name+"_50";
   const double midpoint=(zone.lower+zone.upper)/2.0;
   if(ObjectCreate(0,midpoint_name,OBJ_TREND,0,zone.created,midpoint,right_time,midpoint))
     {
      ObjectSetInteger(0,midpoint_name,OBJPROP_COLOR,InpMidlineColor);
      ObjectSetInteger(0,midpoint_name,OBJPROP_STYLE,STYLE_DOT);
      ObjectSetInteger(0,midpoint_name,OBJPROP_WIDTH,1);
      ObjectSetInteger(0,midpoint_name,OBJPROP_RAY_RIGHT,false);
      ObjectSetInteger(0,midpoint_name,OBJPROP_BACK,true);
      ObjectSetInteger(0,midpoint_name,OBJPROP_SELECTABLE,false);
      ObjectSetInteger(0,midpoint_name,OBJPROP_HIDDEN,false);
     }
  }

void RebuildZones()
  {
   DeleteOurObjects();
   if(_Period!=PERIOD_M15 && _Period!=PERIOD_D1)
     {
      ChartRedraw();
      return;
     }

   MqlRates rates[];
   ArraySetAsSeries(rates,false);
   // O indicador usa exclusivamente o timeframe atual: M15 no M15 e D1 no D1.
   const ENUM_TIMEFRAMES source_tf=(ENUM_TIMEFRAMES)_Period;
   const int copied=CopyRates(_Symbol,source_tf,0,InpLookbackBars+1,rates);
   if(copied<4)
     {
      ChartRedraw();
      return;
     }

   const int closed=copied-1;
   D1Zone zones[];
   for(int i=2; i<closed; i++)
     {
      const double left_high=rates[i-2].high;
      const double left_low=rates[i-2].low;
      const double right_high=rates[i].high;
      const double right_low=rates[i].low;
      if(right_low>left_high && IsUntouched(rates,i+1,closed,left_high,right_low,"COMPRA"))
         AddZone(zones,"FVG","COMPRA",left_high,right_low,rates[i].time);
      else if(right_high<left_low && IsUntouched(rates,i+1,closed,right_high,left_low,"VENDA"))
         AddZone(zones,"FVG","VENDA",right_high,left_low,rates[i].time);
     }

   SortNewestFirst(zones);
   const int limit=MathMin(ArraySize(zones),InpMaxZones);
   datetime right_time=iTime(_Symbol,source_tf,0)+PeriodSeconds(source_tf)*InpProjectionBars;
   if(right_time<=0)
      right_time=TimeCurrent()+PeriodSeconds(source_tf)*InpProjectionBars;
   for(int i=0; i<limit; i++)
      DrawZone(zones[i],i,right_time);
   ChartRedraw();
  }

int OnInit()
  {
   EventSetTimer(10);
   RebuildZones();
   return INIT_SUCCEEDED;
  }

void OnDeinit(const int reason)
  {
   EventKillTimer();
   DeleteOurObjects();
   ChartRedraw();
  }

void OnTimer()
  {
   RebuildZones();
  }

int OnCalculate(const int rates_total,const int prev_calculated,const int begin,const double &price[])
  {
   if(rates_total>0 && price[0]!=EMPTY_VALUE)
     {
      const datetime chart_bar=iTime(_Symbol,PERIOD_CURRENT,0);
      if(chart_bar!=last_chart_bar)
        {
         last_chart_bar=chart_bar;
         RebuildZones();
        }
     }
   return rates_total;
  }
