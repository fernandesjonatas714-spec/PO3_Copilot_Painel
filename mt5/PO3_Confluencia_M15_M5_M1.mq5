#property strict
#property indicator_chart_window
#property indicator_plots 0
#property description "Confluência M5/M15 com confirmação M1"

input int InpLookbackM5=400;
input int InpLookbackM15=400;
input int InpLookbackM1=1200;
input int InpMaxConfluences=1;
input int InpMaxContextZones=6;
input int InpProjectionBars=120;
input double InpVolume=1.0;
input int InpStopBufferPoints=2;
input int InpMinRiskPoints=10;
input bool InpShowAllToday=true;
input bool InpShowTradeLevels=true;
input color InpBullColor=C'90,190,150';
input color InpBearColor=C'220,135,145';
input color InpMidlineColor=C'0,0,0';
struct Zone { string kind; string dir; double lo; double hi; datetime t; double entry; double stop; double inner_lo; double inner_hi; datetime inner_t; };
// Prefixo versionado para não reutilizar objetos visuais da versão antiga.
string P="PO3_CONFLUENCIA_M15_M5_M1_";

void Add(Zone &a[],string k,string d,double lo,double hi,datetime t){int n=ArraySize(a);ArrayResize(a,n+1);a[n].kind=k;a[n].dir=d;a[n].lo=lo;a[n].hi=hi;a[n].t=t;a[n].entry=0;a[n].stop=0;a[n].inner_lo=0;a[n].inner_hi=0;a[n].inner_t=0;}
// Uma zona só é mitigada por fechamento além do seu limite de invalidação.
// Pavio ou toque dentro da faixa não remove a zona.
bool Fresh(const MqlRates &r[],int from,int to,double lo,double hi,string dir){
 for(int i=from;i<to;i++){
   if(dir=="COMPRA" && r[i].close<lo) return false;
   if(dir=="VENDA" && r[i].close>hi) return false;
 }
 return true;
}
bool SameDate(datetime a,datetime b){MqlDateTime x,y;TimeToStruct(a,x);TimeToStruct(b,y);return x.year==y.year&&x.mon==y.mon&&x.day==y.day;}
void Build(ENUM_TIMEFRAMES tf,int count,Zone &out[]){ArrayFree(out);MqlRates r[];ArraySetAsSeries(r,false);int n=CopyRates(_Symbol,tf,0,count,r);if(n<5)return;int closed=n-1;
 for(int i=2;i<closed;i++){if(r[i].low>r[i-2].high&&Fresh(r,i+1,closed,r[i-2].high,r[i].low,"COMPRA"))Add(out,"FVG","COMPRA",r[i-2].high,r[i].low,r[i].time);else if(r[i].high<r[i-2].low&&Fresh(r,i+1,closed,r[i].high,r[i-2].low,"VENDA"))Add(out,"FVG","VENDA",r[i].high,r[i-2].low,r[i].time);}}
void Clear(){for(int i=ObjectsTotal(0,0,-1)-1;i>=0;i--){string n=ObjectName(0,i,0,-1);if(StringFind(n,P)==0)ObjectDelete(0,n);}}
void DrawContextZone(Zone &z,int i,datetime right,string source){
 string n=P+"CTX_"+source+"_"+IntegerToString(i); color c=z.dir=="COMPRA"?InpBullColor:InpBearColor;
 if(!ObjectCreate(0,n,OBJ_RECTANGLE,0,z.t,z.hi,right,z.lo)) return;
 ObjectSetInteger(0,n,OBJPROP_COLOR,c); ObjectSetInteger(0,n,OBJPROP_FILL,true); ObjectSetInteger(0,n,OBJPROP_BACK,true); ObjectSetInteger(0,n,OBJPROP_SELECTABLE,false);
 double mid=(z.lo+z.hi)/2; string m=n+"_50";
 if(ObjectCreate(0,m,OBJ_TREND,0,z.t,mid,right,mid)){ObjectSetInteger(0,m,OBJPROP_COLOR,InpMidlineColor);ObjectSetInteger(0,m,OBJPROP_STYLE,STYLE_DOT);ObjectSetInteger(0,m,OBJPROP_RAY_RIGHT,false);ObjectSetInteger(0,m,OBJPROP_BACK,true);ObjectSetInteger(0,m,OBJPROP_SELECTABLE,false);}
}
void DrawLevelLabel(const string name,const datetime when,const double price,const string text,const color tone)
  {
   if(!ObjectCreate(0,name,OBJ_TEXT,0,when,price)) return;
   ObjectSetString(0,name,OBJPROP_TEXT,text);
   ObjectSetInteger(0,name,OBJPROP_COLOR,tone);
   ObjectSetInteger(0,name,OBJPROP_FONTSIZE,9);
   ObjectSetInteger(0,name,OBJPROP_ANCHOR,ANCHOR_LEFT);
   ObjectSetInteger(0,name,OBJPROP_SELECTABLE,false);
   ObjectSetInteger(0,name,OBJPROP_HIDDEN,false);
  }
void Draw(Zone &z,int i,datetime right){string n=P+IntegerToString(i);color c=(StringFind(z.kind,"+FVG")>=0?C'255,255,197':(z.dir=="COMPRA"?InpBullColor:InpBearColor));if(z.inner_t<=0||z.inner_hi<=z.inner_lo)return;double lo=z.inner_lo,hi=z.inner_hi;if(!ObjectCreate(0,n,OBJ_RECTANGLE,0,z.inner_t,hi,right,lo))return;ObjectSetInteger(0,n,OBJPROP_COLOR,c);ObjectSetInteger(0,n,OBJPROP_FILL,true);ObjectSetInteger(0,n,OBJPROP_BACK,true);ObjectSetInteger(0,n,OBJPROP_SELECTABLE,false);double mid=(lo+hi)/2;string m=n+"_50";if(ObjectCreate(0,m,OBJ_TREND,0,z.inner_t,mid,right,mid)){ObjectSetInteger(0,m,OBJPROP_COLOR,InpMidlineColor);ObjectSetInteger(0,m,OBJPROP_STYLE,STYLE_DOT);ObjectSetInteger(0,m,OBJPROP_RAY_RIGHT,false);ObjectSetInteger(0,m,OBJPROP_BACK,false);ObjectSetInteger(0,m,OBJPROP_WIDTH,1);ObjectSetInteger(0,m,OBJPROP_SELECTABLE,false);}if(_Period!=PERIOD_M1||!InpShowTradeLevels||z.entry<=0||z.stop<=0)return;double risk=MathAbs(z.entry-z.stop),tick=SymbolInfoDouble(_Symbol,SYMBOL_TRADE_TICK_SIZE),tv=SymbolInfoDouble(_Symbol,SYMBOL_TRADE_TICK_VALUE);bool money_ok=(tick>0&&tv>0);double money=money_ok?MathAbs(risk/tick)*tv*InpVolume:0.0;datetime label_time=iTime(_Symbol,PERIOD_M1,60);if(label_time<=0)label_time=z.inner_t;string en=n+"_ENTRY",st=n+"_STOP";string entry_text="Entrada "+DoubleToString(z.entry,_Digits);if(ObjectCreate(0,en,OBJ_HLINE,0,0,z.entry)){ObjectSetInteger(0,en,OBJPROP_COLOR,clrWhite);ObjectSetInteger(0,en,OBJPROP_WIDTH,2);ObjectSetString(0,en,OBJPROP_TEXT,entry_text);ObjectSetString(0,en,OBJPROP_TOOLTIP,entry_text);}DrawLevelLabel(n+"_ENTRY_LABEL",label_time,z.entry,entry_text,clrWhite);string stop_text=money_ok?"Stop -R$ "+DoubleToString(money,2):"Stop -R$ indisponível";if(ObjectCreate(0,st,OBJ_HLINE,0,0,z.stop)){ObjectSetInteger(0,st,OBJPROP_COLOR,InpBearColor);ObjectSetString(0,st,OBJPROP_TEXT,stop_text);ObjectSetString(0,st,OBJPROP_TOOLTIP,stop_text);}DrawLevelLabel(n+"_STOP_LABEL",label_time,z.stop,stop_text,InpBearColor);for(int r=1;r<=5;r++){double target=z.dir=="COMPRA"?z.entry+r*risk:z.entry-r*risk;string tn=n+"_TP"+IntegerToString(r);string target_text=money_ok?"Alvo "+IntegerToString(r)+"R R$ "+DoubleToString(money*r,2):"Alvo "+IntegerToString(r)+"R - R$ indisponível";if(ObjectCreate(0,tn,OBJ_HLINE,0,0,target)){ObjectSetInteger(0,tn,OBJPROP_COLOR,InpBullColor);ObjectSetString(0,tn,OBJPROP_TEXT,target_text);ObjectSetString(0,tn,OBJPROP_TOOLTIP,target_text);}DrawLevelLabel(n+"_TP_LABEL"+IntegerToString(r),label_time,target,target_text,InpBullColor);}}
void Rebuild(){
 Clear();
 if(_Period!=PERIOD_M5&&_Period!=PERIOD_M1){ChartRedraw();return;}
 Zone hi[],m15[],lo[],valid[]; Build(PERIOD_M5,InpLookbackM5,hi); Build(PERIOD_M15,InpLookbackM15,m15); Build(PERIOD_M1,InpLookbackM1,lo);
 Zone best; bool found=false; datetime now=TimeCurrent();
 for(int i=0;i<ArraySize(hi);i++) for(int j=0;j<ArraySize(lo);j++){
   if(lo[j].t<=hi[i].t||lo[j].dir!=hi[i].dir) continue;
   if(lo[j].lo<hi[i].lo||lo[j].hi>hi[i].hi) continue;
   if(!SameDate(lo[j].t,now)) continue;
   // Mantém somente a confluência mais recente; evita várias zonas sobrepostas.
   if(found&&lo[j].t<=best.t) continue;
   double entry=(lo[j].lo+lo[j].hi)/2.0;
   double stop=hi[i].dir=="COMPRA"?hi[i].lo-InpStopBufferPoints*_Point:hi[i].hi+InpStopBufferPoints*_Point;
   if(MathAbs(entry-stop)/_Point<InpMinRiskPoints) continue;
   Zone candidate; candidate.kind=hi[i].kind+"+"+lo[j].kind; candidate.dir=hi[i].dir; candidate.lo=hi[i].lo; candidate.hi=hi[i].hi; candidate.t=lo[j].t; candidate.entry=entry; candidate.stop=stop; candidate.inner_lo=lo[j].lo; candidate.inner_hi=lo[j].hi; candidate.inner_t=lo[j].t;
   int q=ArraySize(valid); ArrayResize(valid,q+1); valid[q]=candidate;
   best=candidate; found=true;
 }
 for(int i=0;i<ArraySize(m15);i++) for(int j=0;j<ArraySize(lo);j++){
   if(lo[j].t<=m15[i].t||lo[j].dir!=m15[i].dir) continue;
   if(lo[j].lo<m15[i].lo||lo[j].hi>m15[i].hi) continue;
   if(!SameDate(lo[j].t,now)) continue;
   if(found&&lo[j].t<=best.t) continue;
   double entry=(lo[j].lo+lo[j].hi)/2.0;
   double stop=m15[i].dir=="COMPRA"?m15[i].lo-InpStopBufferPoints*_Point:m15[i].hi+InpStopBufferPoints*_Point;
   if(MathAbs(entry-stop)/_Point<InpMinRiskPoints) continue;
   Zone candidate; candidate.kind=m15[i].kind+"+"+lo[j].kind; candidate.dir=m15[i].dir; candidate.lo=m15[i].lo; candidate.hi=m15[i].hi; candidate.t=lo[j].t; candidate.entry=entry; candidate.stop=stop; candidate.inner_lo=lo[j].lo; candidate.inner_hi=lo[j].hi; candidate.inner_t=lo[j].t;
   int q=ArraySize(valid); ArrayResize(valid,q+1); valid[q]=candidate;
   best=candidate; found=true;
 }
 datetime right=iTime(_Symbol,_Period,0)+PeriodSeconds(_Period)*InpProjectionBars;
 if(!found){ChartRedraw();return;}
 if(InpShowAllToday){
   int limit=MathMin(ArraySize(valid),InpMaxConfluences);
   for(int k=0;k<limit;k++) Draw(valid[ArraySize(valid)-1-k],k,right);
 }
 else Draw(best,0,right);
 ChartRedraw();
}
int OnInit(){EventSetTimer(5);Rebuild();return INIT_SUCCEEDED;}void OnDeinit(const int r){EventKillTimer();Clear();ChartRedraw();}void OnTimer(){Rebuild();}int OnCalculate(const int n,const int p,const int b,const double &price[]){return n;}
