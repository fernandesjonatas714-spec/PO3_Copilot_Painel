#property strict
#property indicator_chart_window
#property indicator_plots 0

input int   InpLookbackBars   = 500;
input int   InpMaxZones       = 8;
input int   InpProjectionBars = 80;
input color InpBullColor      = C'90,190,150';
input color InpBearColor      = C'220,135,145';
input color InpMidlineColor   = C'0,0,0';

struct Zone
  {
   string kind;
   string direction;
   double lower;
   double upper;
   datetime created;
  };

string PREFIX="PO3_FVG_OB_M5_";

bool IsValid(const MqlRates &rates[],const int start,const int count,const double lower,const double upper,const string direction)
  {
   for(int i=start;i<count;i++)
     {
      // Toque/pavio não mitiga; somente fechamento além do limite invalida.
      if(direction=="COMPRA" && rates[i].close<lower) return false;
      if(direction=="VENDA" && rates[i].close>upper) return false;
     }
   return true;
  }

void AddZone(Zone &zones[],const string kind,const string direction,const double lower,const double upper,const datetime created)
  {
   int n=ArraySize(zones);
   ArrayResize(zones,n+1);
   zones[n].kind=kind;
   zones[n].direction=direction;
   zones[n].lower=lower;
   zones[n].upper=upper;
   zones[n].created=created;
  }

void SortNewestFirst(Zone &zones[])
  {
   for(int i=0;i<ArraySize(zones)-1;i++)
      for(int j=i+1;j<ArraySize(zones);j++)
         if(zones[j].created>zones[i].created)
           {
            Zone tmp=zones[i]; zones[i]=zones[j]; zones[j]=tmp;
           }
  }

void ClearObjects()
  {
   for(int i=ObjectsTotal(0,0,-1)-1;i>=0;i--)
     {
      string name=ObjectName(0,i,0,-1);
      if(StringFind(name,PREFIX)==0) ObjectDelete(0,name);
     }
  }

void DrawZone(const Zone &zone,const int index,const datetime right_time)
  {
   string name=PREFIX+IntegerToString(index)+"_"+zone.kind;
   // FVGs ficam amarelo claro independentemente da direção; OBs permanecem direcionais.
   color zone_color=zone.kind=="FVG"?C'255,255,197':(zone.direction=="COMPRA"?InpBullColor:InpBearColor);
   if(!ObjectCreate(0,name,OBJ_RECTANGLE,0,zone.created,zone.upper,right_time,zone.lower)) return;
   ObjectSetInteger(0,name,OBJPROP_COLOR,zone_color);
   ObjectSetInteger(0,name,OBJPROP_FILL,true);
   ObjectSetInteger(0,name,OBJPROP_BACK,true);
   ObjectSetInteger(0,name,OBJPROP_WIDTH,2);
   ObjectSetInteger(0,name,OBJPROP_SELECTABLE,false);

   double midpoint=(zone.lower+zone.upper)/2.0;
   string mid=name+"_50";
   if(ObjectCreate(0,mid,OBJ_TREND,0,zone.created,midpoint,right_time,midpoint))
     {
      ObjectSetInteger(0,mid,OBJPROP_COLOR,InpMidlineColor);
      ObjectSetInteger(0,mid,OBJPROP_STYLE,STYLE_DOT);
      ObjectSetInteger(0,mid,OBJPROP_RAY_RIGHT,false);
      ObjectSetInteger(0,mid,OBJPROP_BACK,false);
      ObjectSetInteger(0,mid,OBJPROP_WIDTH,1);
      ObjectSetInteger(0,mid,OBJPROP_SELECTABLE,false);
     }

  }

void Rebuild()
  {
   ClearObjects();
   if(_Period!=PERIOD_M5){ChartRedraw();return;}

   MqlRates rates[];
   ArraySetAsSeries(rates,false);
   int copied=CopyRates(_Symbol,PERIOD_M5,0,InpLookbackBars+1,rates);
   if(copied<5){ChartRedraw();return;}
   int closed=copied-1;
   Zone zones[];

   for(int i=2;i<closed;i++)
     {
      if(rates[i].low>rates[i-2].high && IsValid(rates,i+1,closed,rates[i-2].high,rates[i].low,"COMPRA"))
         AddZone(zones,"FVG","COMPRA",rates[i-2].high,rates[i].low,rates[i].time);
      else if(rates[i].high<rates[i-2].low && IsValid(rates,i+1,closed,rates[i].high,rates[i-2].low,"VENDA"))
         AddZone(zones,"FVG","VENDA",rates[i].high,rates[i-2].low,rates[i].time);
     }


   SortNewestFirst(zones);
   int limit=MathMin(ArraySize(zones),InpMaxZones);
   datetime right_time=iTime(_Symbol,PERIOD_M5,0)+PeriodSeconds(PERIOD_M5)*InpProjectionBars;
   for(int i=0;i<limit;i++) DrawZone(zones[i],i,right_time);
   ChartRedraw();
  }

int OnInit(){EventSetTimer(10);Rebuild();return INIT_SUCCEEDED;}
void OnDeinit(const int reason){EventKillTimer();ClearObjects();ChartRedraw();}
void OnTimer(){Rebuild();}
int OnCalculate(const int rates_total,const int prev_calculated,const int begin,const double &price[]){return rates_total;}
