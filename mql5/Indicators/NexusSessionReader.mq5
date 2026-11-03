#property strict
#property indicator_chart_window
#property indicator_plots 0
#property version "1.02"
#property description "Read-only quote/trade session export. No trading or network calls."

input string SymbolsCsv="XAUUSD";
input int ExportEverySeconds=300;
input string OutputFileName="nexus_sessions_v1.json";
string names[];

string J(const string value)
{
   string out="\"";
   for(int i=0;i<StringLen(value);i++)
   {
      ushort c=StringGetCharacter(value,i);
      if(c==34) out+="\\\"";
      else if(c==92) out+="\\\\";
      else if(c<32) out+=StringFormat("\\u%04x",(int)c);
      else out+=ShortToString(c);
   }
   return out+"\"";
}

string Sessions(const string symbol,const int day,const bool quote,string &state,int &error)
{
   string list="[";int count=0;state="no_sessions";error=0;
   long selected=0;
   ResetLastError();
   bool known=SymbolInfoInteger(symbol,SYMBOL_SELECT,selected);
   // Do not select symbols or change terminal configuration from this reader.
   // Price-series synchronization is independent of session metadata. Ask the
   // session API itself; preserve its error instead of inventing error 1 for
   // every symbol whose chart/history has not yet been synchronized.
   if(!known || selected==0 || !TerminalInfoInteger(TERMINAL_CONNECTED))
   { state="error";error=GetLastError();if(error==0) error=1;return "[]"; }
   for(uint index=0;index<=32;index++)
   {
      datetime from=0,to=0;ResetLastError();
      bool ok=quote ? SymbolInfoSessionQuote(symbol,(ENUM_DAY_OF_WEEK)day,index,from,to)
                    : SymbolInfoSessionTrade(symbol,(ENUM_DAY_OF_WEEK)day,index,from,to);
      if(!ok)
      {
         error=GetLastError();
         // Sequential enumeration ends at the first absent session (4307).
         // Other failures must not be interpreted as a closed market.
         if(error==0 || error==ERR_MARKET_SESSION_INDEX)
         { error=0;state=count>0 ? "ok" : "no_sessions"; }
         else state="error";
         break;
      }
      if(index==32) { state="truncated";break; }
      long begin=(long)from, end=(long)to;
      if(begin<0 || begin>=86400 || end<0 || end>86400 || begin==end)
      { state="error";error=2;break; }
      if(count>0) list+=",";
      list+=StringFormat("{\"start_seconds\":%d,\"end_seconds\":%d}",(int)begin,(int)end);
      count++;
   }
   return list+"]";
}

void ExportSessions()
{
   bool connected=(bool)TerminalInfoInteger(TERMINAL_CONNECTED);
   datetime utc=TimeGMT();
   string stamp=TimeToString(utc,TIME_DATE|TIME_SECONDS);
   StringReplace(stamp,".","-");StringReplace(stamp," ","T");stamp+="Z";
   long offset=(long)TimeTradeServer()-(long)utc;
   // Observed offset is diagnostic, never authority for historical DST.
   if(offset < -86400 || offset > 86400) offset=0;
   string body="{\"schema_version\":1,\"server\":"+J(AccountInfoString(ACCOUNT_SERVER))+
      ",\"company\":"+J(AccountInfoString(ACCOUNT_COMPANY))+",\"captured_at_utc\":"+J(stamp)+
      ",\"connected\":"+(connected ? "true" : "false")+
      ",\"observed_server_offset_seconds\":"+IntegerToString((int)offset)+",\"symbols\":[";
   for(int i=0;i<ArraySize(names);i++)
   {
      if(i>0) body+=",";
      body+="{\"broker_symbol\":"+J(names[i])+",\"days\":[";
      for(int day=0;day<7;day++)
      {
         if(day>0) body+=",";
         string qs,ts;int qe,te;
         string q=Sessions(names[i],day,true,qs,qe),t=Sessions(names[i],day,false,ts,te);
         body+=StringFormat("{\"day\":%d,\"quote_status\":",day)+J(qs)+",\"trade_status\":"+J(ts)+
            StringFormat(",\"quote_error\":%d,\"trade_error\":%d,\"quote_sessions\":",qe,te)+q+",\"trade_sessions\":"+t+"}";
      }
      body+="]}";
   }
   body+="]}";
   if(StringLen(body)>1048576) { Print("Nexus sessions export too large");return; }
   string temp=OutputFileName+"."+IntegerToString(ChartID())+".tmp";
   ResetLastError();
   int handle=FileOpen(temp,FILE_WRITE|FILE_TXT|FILE_ANSI|FILE_COMMON,0,CP_UTF8);
   if(handle==INVALID_HANDLE) { Print("Nexus sessions write failed: ",GetLastError());return; }
   uint wrote=FileWriteString(handle,body);FileFlush(handle);FileClose(handle);
   if(wrote==0) { Print("Nexus sessions empty write rejected");return; }
   if(!FileMove(temp,FILE_COMMON,OutputFileName,FILE_COMMON|FILE_REWRITE))
      Print("Nexus sessions replace failed: ",GetLastError());
}

int OnInit()
{
   if(ExportEverySeconds<60 || StringLen(OutputFileName)<1 || StringLen(OutputFileName)>128 ||
      StringFind(OutputFileName,"/")>=0 || StringFind(OutputFileName,"\\")>=0 ||
      StringFind(OutputFileName,":")>=0 || StringFind(OutputFileName,"..")>=0) return INIT_PARAMETERS_INCORRECT;
   int count=StringSplit(SymbolsCsv,',',names);
   if(count<1 || count>32) return INIT_PARAMETERS_INCORRECT;
   for(int i=0;i<count;i++)
   {
      StringTrimLeft(names[i]);StringTrimRight(names[i]);
      if(StringLen(names[i])<1 || StringLen(names[i])>128) return INIT_PARAMETERS_INCORRECT;
      for(int j=0;j<i;j++) if(names[j]==names[i]) return INIT_PARAMETERS_INCORRECT;
   }
   if(!EventSetTimer(ExportEverySeconds)) return INIT_FAILED;
   ExportSessions();return INIT_SUCCEEDED;
}
void OnTimer() { ExportSessions(); }
void OnDeinit(const int reason) { EventKillTimer(); }
int OnCalculate(const int rates_total,const int prev_calculated,const int begin,const double &price[])
{ return rates_total; }
