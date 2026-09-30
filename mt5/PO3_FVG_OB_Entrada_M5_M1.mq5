#property strict
#property indicator_chart_window
#property indicator_plots 0

input int   InpLookbackBars   = 300;
input int   InpMaxZones       = 8;
input int   InpProjectionBars = 120;
input bool  InpShowLabels     = true;
input color InpBullColor      = C'105,175,230';
input color InpBearColor      = C'235,125,135';
input color InpMidlineColor   = C'205,205,205';

struct EntryZone
  {
   string   kind;
   string   direction;
   double   lower;
   double   upper;
   datetime created;
  };

string PREFIX = "PO3_ENTRY_M5_M1_";
datetime last_chart_bar = 0;

bool IsUntouched(const MqlRates &rates[],const int start,const int count,const double lower,const double upper)
  {
   for(int i=start; i<count; i++)
     {
      if(rates[i].low<=upper && rates[i].high>=lower)
         return false;
     }
   return true;
  }

void AddZone(EntryZone &zones[],const string kind,const string direction,const double lower,const double upper,const datetime created)
  {
   const int size=ArraySize(zones);
   ArrayResize(zones,size+1);
   zones[size].kind=kind;
   zones[size].direction=direction;
   zones[size].lower=lower;
   zones[size].upper=upper;
   zones[size].created=created;
  }

void SortNewestFirst(EntryZone &zones[])
  {
   for(int i=0; i<ArraySize(zones)-1; i++)
      for(int j=i+1; j<ArraySize(zones); j++)
         if(zones[j].created>zones[i].created)
           {
            EntryZone swap=zones[i];
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

void DrawZone(const EntryZone &zone,const int index,const datetime right_time)
  {
   const string name=PREFIX+IntegerToString(index)+"_"+zone.kind;
   const color zone_color=(zone.direction=="COMPRA" ? InpBullColor : InpBearColor);
   if(!ObjectCreate(0,name,OBJ_RECTANGLE,0,zone.created,zone.upper,right_time,zone.lower))
      return;
   ObjectSetInteger(0,name,OBJPROP_COLOR,zone_color);
   ObjectSetInteger(0,name,OBJPROP_FILL,true);
   ObjectSetInteger(0,name,OBJPROP_BACK,true);
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
   if(InpShowLabels)
     {
      const string label=name+"_LABEL";
      const string text=zone.kind+" "+EnumToString(_Period)+" "+zone.direction+" 50%";
      if(ObjectCreate(0,label,OBJ_TEXT,0,zone.created,zone.upper))
        {
         ObjectSetString(0,label,OBJPROP_TEXT,text);
         ObjectSetInteger(0,label,OBJPROP_COLOR,zone_color);
         ObjectSetInteger(0,label,OBJPROP_ANCHOR,ANCHOR_LEFT_LOWER);
         ObjectSetInteger(0,label,OBJPROP_SELECTABLE,false);
         ObjectSetInteger(0,label,OBJPROP_HIDDEN,false);
        }
     }
  }

void RebuildZones()
  {
   DeleteOurObjects();
   if(_Period!=PERIOD_M5 && _Period!=PERIOD_M1)
     {
      ChartRedraw();
      return;
     }

   MqlRates rates[];
   ArraySetAsSeries(rates,false);
   const int copied=CopyRates(_Symbol,_Period,0,InpLookbackBars+1,rates);
   if(copied<4)
     {
      ChartRedraw();
      return;
     }

   const int closed=copied-1;
   EntryZone zones[];
   for(int i=2; i<closed; i++)
     {
      const double left_high=rates[i-2].high;
      const double left_low=rates[i-2].low;
      const double right_high=rates[i].high;
      const double right_low=rates[i].low;
      if(right_low>left_high && IsUntouched(rates,i+1,closed,left_high,right_low))
         AddZone(zones,"FVG","COMPRA",left_high,right_low,rates[i].time);
      else if(right_high<left_low && IsUntouched(rates,i+1,closed,right_high,left_low))
         AddZone(zones,"FVG","VENDA",right_high,left_low,rates[i].time);
     }

   double typical_body=0.0;
   for(int i=0; i<closed; i++)
      typical_body+=MathAbs(rates[i].close-rates[i].open);
   typical_body/=closed;
   if(typical_body<=0.0)
      typical_body=_Point;
   for(int i=0; i<closed-1; i++)
     {
      const double candle_body=MathAbs(rates[i].close-rates[i].open);
      const double impulse_body=MathAbs(rates[i+1].close-rates[i+1].open);
      if(impulse_body<MathMax(candle_body*1.5,typical_body*1.5))
         continue;
      const string direction=(rates[i+1].close>rates[i+1].open ? "COMPRA" : "VENDA");
      const bool opposite=(direction=="COMPRA" ? rates[i].close<rates[i].open : rates[i].close>rates[i].open);
      if(opposite && IsUntouched(rates,i+2,closed,rates[i].low,rates[i].high))
         AddZone(zones,"OB",direction,rates[i].low,rates[i].high,rates[i].time);
     }

   SortNewestFirst(zones);
   const int limit=MathMin(ArraySize(zones),InpMaxZones);
   datetime right_time=iTime(_Symbol,_Period,0)+PeriodSeconds(_Period)*InpProjectionBars;
   if(right_time<=0)
      right_time=TimeCurrent()+PeriodSeconds(_Period)*InpProjectionBars;
   for(int i=0; i<limit; i++)
      DrawZone(zones[i],i,right_time);
   ChartRedraw();
  }

int OnInit()
  {
   EventSetTimer(5);
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
      const datetime chart_bar=iTime(_Symbol,_Period,0);
      if(chart_bar!=last_chart_bar)
        {
         last_chart_bar=chart_bar;
         RebuildZones();
        }
     }
   return rates_total;
  }
