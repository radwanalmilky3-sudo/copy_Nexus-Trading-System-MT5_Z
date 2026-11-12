//+------------------------------------------------------------------+
//|                                              NexusBridgeEA.mq5  |
//|        Nexus Trader MT5 bridge — polls the command queue and    |
//|        executes OPEN / MODIFY / CLOSE / PARTIAL_CLOSE orders.   |
//|                                                                 |
//| Protocol (item 3 + item 4):                                     |
//|   POST {BaseURL}/api/ea/handshake   — bind terminal identity    |
//|   POST {BaseURL}/api/ea/poll        — report results + claim    |
//|   Auth: Authorization: Bearer nexus_ea_... (never stored server- |
//|   side in clear: only its SHA-256 hash lives in the database).  |
//|                                                                 |
//| Idempotency: command_id is the idempotency key. Executed ids    |
//| are journaled (terminal Global Variables + MQL5\Files CSV), so  |
//| a re-claimed command is never executed twice on the terminal.   |
//|                                                                 |
//| Setup: Tools -> Options -> Expert Advisors -> "Allow WebRequest |
//| for listed URL" must contain exactly the BaseURL origin.        |
//+------------------------------------------------------------------+
#property copyright "Nexus Trader"
#property link      "https://github.com/radwanmhh-svg/Nexus-Trading-System-MT5"
#property version   "1.00"
#property description "Nexus Trader EA bridge: executes queue commands on a real MT5 terminal."

#include <Trade\Trade.mqh>

//--- inputs
input group "Nexus EA Bridge"
input string InpBaseURL   = "http://127.0.0.1:9000"; // Base URL (use https:// in production)
input string InpToken     = "";                      // API token nexus_ea_... (shown once in dashboard)
input int    InpPollSec   = 3;                       // Poll interval, seconds (1-3 recommended)
input int    InpTimeoutMs = 5000;                    // HTTP timeout, ms
input long   InpMagic     = 860401;                  // Magic number for EA-placed orders
input bool   InpVerbose   = true;                    // Verbose Experts-journal logging
input bool   InpCalendarSync     = true;              // Sync MT5 native economic calendar
input int    InpCalendarSyncSec  = 300;               // Calendar sync interval, seconds
input int    InpCalendarDaysBack = 7;                 // Calendar history window, days back
input int    InpCalendarDaysFwd  = 7;                 // Calendar forecast window, days forward
input int    InpCalendarChunk    = 40;                // Events per HTTP batch (max 200 server-side)

//--- state
CTrade   g_trade;
string   g_status   = "init";
bool     g_bound    = false;
datetime g_last_hs  = 0;
datetime g_last_cal = 0;   // last successful calendar sync (GMT)
int      g_auth_fail_streak = 0;

//--- result waiting to be reported
struct SResult
  {
   string   command_id;
   bool     ok;
   string   detail;
   long     ticket;
   double   price;
  };
SResult g_results[];

//+------------------------------------------------------------------+
//| Small JSON helpers (targeted, shallow — enough for this API)     |
//+------------------------------------------------------------------+
string JsonEscape(const string s)
  {
   string out = s;
   StringReplace(out, "\\", "\\\\");
   StringReplace(out, "\"", "\\\"");
   StringReplace(out, "\n", " ");
   StringReplace(out, "\r", " ");
   return out;
  }

ushort ChrAt(const string s, const int i)
  {
   if(i < 0 || i >= StringLen(s))
      return 0;
   return StringGetCharacter(s, i);
  }

// Returns the raw JSON token starting at i: "string", number, true/false/null, {...} or [...]
string JsonTokenAt(const string json, const int start)
  {
   int    i    = start;
   ushort c    = ChrAt(json, i);
   int    n    = StringLen(json);
   while(c == ' ' || c == '\t' || c == '\n' || c == '\r')
     {
      i++;
      c = ChrAt(json, i);
     }
   if(i >= n)
      return "";
   if(c == '"')
     {
      int j = i + 1;
      bool esc = false;
      while(j < n)
        {
         ushort d = ChrAt(json, j);
         if(esc)                { esc = false; }
         else if(d == '\\')     { esc = true;  }
         else if(d == '"')      { return StringSubstr(json, i, j - i + 1); }
         j++;
        }
      return StringSubstr(json, i);
     }
   if(c == '{' || c == '[')
     {
      ushort open = c, close = (c == '{') ? '}' : ']';
      int depth = 0;
      int j = i;
      bool esc = false, instr = false;
      while(j < n)
        {
         ushort d = ChrAt(json, j);
         if(instr)
           {
            if(esc)            esc = false;
            else if(d == '\\') esc = true;
            else if(d == '"')  instr = false;
           }
         else
           {
            if(d == '"')       instr = true;
            else if(d == open) depth++;
            else if(d == close)
              {
               depth--;
               if(depth == 0)
                  return StringSubstr(json, i, j - i + 1);
              }
           }
         j++;
        }
      return StringSubstr(json, i);
     }
   // bare token: number / true / false / null
   int j = i;
   while(j < n)
     {
      ushort d = ChrAt(json, j);
      if(d == ',' || d == '}' || d == ']' || d == ' ' || d == '\n' || d == '\r' || d == '\t')
         break;
      j++;
     }
   return StringSubstr(json, i, j - i);
  }

// Finds "key": and returns the raw token of its value ("" when missing)
string JsonValue(const string json, const string key)
  {
   string pat = "\"" + key + "\"";
   int k = StringFind(json, pat);
   if(k < 0)
      return "";
   int colon = StringFind(json, ":", k + StringLen(pat));
   if(colon < 0)
      return "";
   return JsonTokenAt(json, colon + 1);
  }

string JsonString(const string json, const string key, const string def = "")
  {
   string raw = JsonValue(json, key);
   int n = StringLen(raw);
   if(n >= 2 && ChrAt(raw, 0) == '"' && ChrAt(raw, n - 1) == '"')
      raw = StringSubstr(raw, 1, n - 2);
   // minimal unescape
   StringReplace(raw, "\\\"", "\"");
   StringReplace(raw, "\\\\", "\\");
   StringReplace(raw, "\\n", " ");
   return (raw == "" ? def : raw);
  }

double JsonNumber(const string json, const string key, const double def = 0.0)
  {
   string raw = JsonValue(json, key);
   if(raw == "" || raw == "null")
      return def;
   return StringToDouble(raw);
  }

//+------------------------------------------------------------------+
//| Split {"commands":[{...},{...}]} into object substrings          |
//+------------------------------------------------------------------+
int JsonSplitArrayObjects(const string json, const string array_key, string &objects[])
  {
   ArrayResize(objects, 0);
   string arr = JsonValue(json, array_key);
   int n = StringLen(arr);
   if(n < 2 || ChrAt(arr, 0) != '[')
      return 0;
   int depth = 0, start = -1;
   bool instr = false, esc = false;
   for(int i = 0; i < n; i++)
     {
      ushort c = ChrAt(arr, i);
      if(instr)
        {
         if(esc)            esc = false;
         else if(c == '\\') esc = true;
         else if(c == '"')  instr = false;
         continue;
        }
      if(c == '"')      { instr = true; }
      else if(c == '{') { if(depth == 0) start = i; depth++; }
      else if(c == '}')
        {
         depth--;
         if(depth == 0 && start >= 0)
           {
            int sz = ArraySize(objects);
            ArrayResize(objects, sz + 1);
            objects[sz] = StringSubstr(arr, start, i - start + 1);
            start = -1;
           }
        }
     }
   return ArraySize(objects);
  }

//+------------------------------------------------------------------+
//| Idempotency journal                                              |
//+------------------------------------------------------------------+
string JournalGlobalName(const string command_id)
  {
   return "NXEAJ_" + command_id;
  }

bool JournalHas(const string command_id, bool &was_ok)
  {
   string name = JournalGlobalName(command_id);
   if(GlobalVariableCheck(name))
     {
      was_ok = (GlobalVariableGet(name) == 1.0);
      return true;
     }
   return false;
  }

void JournalPut(const string command_id, const bool ok)
  {
   GlobalVariableSet(JournalGlobalName(command_id), ok ? 1.0 : 2.0);
   int fh = FileOpen("NexusBridgeEA_journal.csv",
                     FILE_READ | FILE_WRITE | FILE_CSV | FILE_ANSI | FILE_SHARE_READ, ',');
   if(fh != INVALID_HANDLE)
     {
      FileSeek(fh, 0, SEEK_END);
      FileWrite(fh, TimeToString(TimeGMT(), TIME_DATE | TIME_SECONDS),
                command_id, ok ? "OK" : "FAIL");
      FileClose(fh);
     }
  }

//+------------------------------------------------------------------+
//| HTTP                                                             |
//+------------------------------------------------------------------+
bool HttpPost(const string path, const string body, string &response, int &status)
  {
   string url  = InpBaseURL + path;
   string head = "Content-Type: application/json\r\n" +
                 "Authorization: Bearer " + InpToken + "\r\n";
   char data[];
   char result[];
   string result_headers;
   // CP_UTF8: default CP_ACP mangles non-ASCII (Arabic event names) in the body
   StringToCharArray(body, data, 0, WHOLE_ARRAY, CP_UTF8);
   ArrayResize(data, ArraySize(data) - 1); // strip terminating zero
   ResetLastError();
   status = WebRequest("POST", url, head, InpTimeoutMs, data, result, result_headers);
   response = CharArrayToString(result, 0, WHOLE_ARRAY, CP_UTF8);
   if(status == -1)
     {
      int err = GetLastError();
      PrintFormat("NexusBridgeEA: WebRequest failed err=%d — is '%s' whitelisted in "
                  "Tools->Options->Expert Advisors->Allow WebRequest?", err, InpBaseURL);
      return false;
     }
   return (status == 200);
  }

//+------------------------------------------------------------------+
//| Volume / price normalization                                     |
//+------------------------------------------------------------------+
double NormalizeVolume(const string symbol, double vol)
  {
   double vmin  = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MIN);
   double vmax  = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MAX);
   double vstep = SymbolInfoDouble(symbol, SYMBOL_VOLUME_STEP);
   if(vstep > 0)
      vol = MathRound(vol / vstep) * vstep;
   if(vol < vmin) vol = vmin;
   if(vol > vmax) vol = vmax;
   return vol;
  }

double NormalizePrice(const string symbol, double price)
  {
   int digits = (int)SymbolInfoInteger(symbol, SYMBOL_DIGITS);
   return NormalizeDouble(price, digits);
  }

//+------------------------------------------------------------------+
//| Command execution                                                |
//+------------------------------------------------------------------+
bool PositionMatches(const string symbol, const string side, const string comment)
  {
   if(PositionGetString(POSITION_SYMBOL) != symbol)
      return false;
   if((long)PositionGetInteger(POSITION_MAGIC) != InpMagic)
      return false;
   if(side == "BUY"  && (ENUM_POSITION_TYPE)PositionGetInteger(POSITION_TYPE) != POSITION_TYPE_BUY)
      return false;
   if(side == "SELL" && (ENUM_POSITION_TYPE)PositionGetInteger(POSITION_TYPE) != POSITION_TYPE_SELL)
      return false;
   if(comment != "")
     {
      string pos_comment = PositionGetString(POSITION_COMMENT);
      if(StringFind(pos_comment, comment) < 0)
         return false;
     }
   return true;
  }

bool ExecuteOpen(const string symbol, const string payload, string &detail,
                 long &ticket, double &price)
  {
   if(!SymbolSelect(symbol, true))
     {
      detail = "unknown symbol " + symbol;
      return false;
     }
   string side      = JsonString(payload, "side", "BUY");
   string otype     = JsonString(payload, "order_type", "MARKET");
   string comment   = JsonString(payload, "comment", "nexus:ea");
   int    slippage  = (int)JsonNumber(payload, "slippage", 10);
   double vol       = NormalizeVolume(symbol, JsonNumber(payload, "size", 0.01));
   double sl        = NormalizePrice(symbol, JsonNumber(payload, "sl", 0.0));
   double tp        = NormalizePrice(symbol, JsonNumber(payload, "tp", 0.0));
   double lim       = NormalizePrice(symbol, JsonNumber(payload, "price", 0.0));

   g_trade.SetExpertMagicNumber(InpMagic);
   g_trade.SetDeviationInPoints((ulong)MathMax(1, slippage));
   g_trade.SetTypeFillingBySymbol(symbol);

   bool sent = false;
   bool is_buy = (side == "BUY");
   if(otype == "MARKET")
      sent = is_buy ? g_trade.Buy(vol, symbol, 0.0, sl, tp, comment)
                    : g_trade.Sell(vol, symbol, 0.0, sl, tp, comment);
   else if(otype == "LIMIT")
      sent = is_buy ? g_trade.BuyLimit(vol, lim, symbol, sl, tp, ORDER_TIME_GTC, 0, comment)
                    : g_trade.SellLimit(vol, lim, symbol, sl, tp, ORDER_TIME_GTC, 0, comment);
   else if(otype == "STOP")
      sent = is_buy ? g_trade.BuyStop(vol, lim, symbol, sl, tp, ORDER_TIME_GTC, 0, comment)
                    : g_trade.SellStop(vol, lim, symbol, sl, tp, ORDER_TIME_GTC, 0, comment);
   else
     {
      detail = "unsupported order_type " + otype;
      return false;
     }

   uint  ret = g_trade.ResultRetcode();
   detail = otype + " " + side + " " + DoubleToString(vol, 2) + " " + symbol +
            " retcode=" + IntegerToString((int)ret) + " (" + g_trade.ResultRetcodeDescription() + ")";
   ticket = (long)g_trade.ResultOrder();
   price  = g_trade.ResultPrice();
   bool ok = sent && (ret == TRADE_RETCODE_DONE || ret == TRADE_RETCODE_DONE_PARTIAL ||
                      ret == TRADE_RETCODE_PLACED || ret == TRADE_RETCODE_NO_CHANGES);
   if(!ok && ticket == 0)
      detail = detail + " lastError=" + IntegerToString(GetLastError());
   return ok;
  }

bool ExecuteClose(const string symbol, const string payload, string &detail,
                  long &ticket, double &price)
  {
   if(!SymbolSelect(symbol, true))
     {
      detail = "unknown symbol " + symbol;
      return false;
     }
   string side    = JsonString(payload, "side", "");
   string comment = JsonString(payload, "comment", "");
   double vol     = JsonNumber(payload, "volume", 0.0);

   g_trade.SetExpertMagicNumber(InpMagic);
   g_trade.SetTypeFillingBySymbol(symbol);

   bool any = false, all_ok = true;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong pos_ticket = PositionGetTicket(i);
      if(pos_ticket == 0)
         continue;
      if(!PositionMatches(symbol, side, comment))
         continue;
      any = true;
      double pos_vol = PositionGetDouble(POSITION_VOLUME);
      bool closed;
      if(vol > 0.0 && vol + 1e-9 < pos_vol)
         closed = g_trade.PositionClosePartial(pos_ticket, NormalizeVolume(symbol, vol));
      else
         closed = g_trade.PositionClose(pos_ticket);
      if(!closed)
        {
         all_ok = false;
         detail = "close failed retcode=" + IntegerToString((int)g_trade.ResultRetcode()) +
                  " (" + g_trade.ResultRetcodeDescription() + ")";
        }
      else
        {
         ticket = (long)pos_ticket;
         price  = g_trade.ResultPrice();
        }
      if(vol > 0.0) // partial close: handle only the first matching position
         break;
     }
   if(!any)
     {
      detail = "no matching position (symbol=" + symbol + " side=" + side + ")";
      return true; // nothing to close is a success: queue stays consistent
     }
   if(all_ok && detail == "")
      detail = "closed";
   return all_ok;
  }

bool ExecuteModify(const string symbol, const string payload, string &detail,
                   long &ticket, double &price)
  {
   if(!SymbolSelect(symbol, true))
     {
      detail = "unknown symbol " + symbol;
      return false;
     }
   string comment = JsonString(payload, "comment", "");
   double sl      = JsonNumber(payload, "sl", 0.0);
   double tp      = JsonNumber(payload, "tp", 0.0);

   g_trade.SetExpertMagicNumber(InpMagic);

   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong pos_ticket = PositionGetTicket(i);
      if(pos_ticket == 0)
         continue;
      if(!PositionMatches(symbol, "", comment))
         continue;
      double cur_sl = PositionGetDouble(POSITION_SL);
      double cur_tp = PositionGetDouble(POSITION_TP);
      double new_sl = (sl > 0.0) ? NormalizePrice(symbol, sl) : cur_sl;
      double new_tp = (tp > 0.0) ? NormalizePrice(symbol, tp) : cur_tp;
      bool ok = g_trade.PositionModify(pos_ticket, new_sl, new_tp);
      detail = "modify retcode=" + IntegerToString((int)g_trade.ResultRetcode()) +
               " (" + g_trade.ResultRetcodeDescription() + ")";
      ticket = (long)pos_ticket;
      return ok;
     }
   detail = "no matching position to modify";
   return false;
  }

//+------------------------------------------------------------------+
//| One command with journal replay                                  |
//+------------------------------------------------------------------+
void ProcessCommand(const string cmd_json)
  {
   string command_id = JsonString(cmd_json, "command_id", "");
   string symbol     = JsonString(cmd_json, "symbol", "");
   string action     = JsonString(cmd_json, "action", "");
   string payload    = JsonValue(cmd_json, "payload");
   if(command_id == "" || action == "")
      return;

   SResult r;
   r.command_id = command_id;
   r.ticket     = 0;
   r.price      = 0.0;

   bool already_ok = false;
   if(JournalHas(command_id, already_ok))
     {
      r.ok     = already_ok;
      r.detail = "already executed (journal replay)";
      AddResult(r);
      return;
     }

   if(InpVerbose)
      PrintFormat("NexusBridgeEA: executing %s %s %s payload=%s", action, symbol, command_id, payload);

   if(action == "OPEN")
      r.ok = ExecuteOpen(symbol, payload, r.detail, r.ticket, r.price);
   else if(action == "CLOSE" || action == "PARTIAL_CLOSE")
      r.ok = ExecuteClose(symbol, payload, r.detail, r.ticket, r.price);
   else if(action == "MODIFY")
      r.ok = ExecuteModify(symbol, payload, r.detail, r.ticket, r.price);
   else
     {
      r.ok = false;
      r.detail = "unknown action " + action;
     }

   if(r.detail == "")
      r.detail = r.ok ? "done" : "failed";
   JournalPut(command_id, r.ok);
   AddResult(r);
  }

void AddResult(const SResult &r)
  {
   int n = ArraySize(g_results);
   ArrayResize(g_results, n + 1);
   g_results[n] = r;
  }

string BuildResultsBody()
  {
   string items = "";
   for(int i = 0; i < ArraySize(g_results); i++)
     {
      if(items != "")
         items += ",";
      items += "{\"command_id\":\"" + JsonEscape(g_results[i].command_id) + "\"" +
               ",\"ok\":" + (g_results[i].ok ? "true" : "false") +
               ",\"detail\":\"" + JsonEscape(g_results[i].detail) + "\"" +
               ",\"ticket\":" + IntegerToString(g_results[i].ticket) +
               ",\"price\":" + DoubleToString(g_results[i].price, 8) + "}";
     }
   return "{\"results\":[" + items + "]}";
  }

//+------------------------------------------------------------------+
//| Handshake                                                        |
//+------------------------------------------------------------------+
bool DoHandshake()
  {
   string body = "{\"mt5_login\":\"" + IntegerToString(AccountInfoInteger(ACCOUNT_LOGIN)) + "\"" +
                 ",\"mt5_broker\":\"" + JsonEscape(AccountInfoString(ACCOUNT_COMPANY)) + "\"" +
                 ",\"mt5_server\":\"" + JsonEscape(AccountInfoString(ACCOUNT_SERVER)) + "\"" +
                 ",\"terminal_version\":\"" + JsonEscape(TerminalInfoString(TERMINAL_NAME) + " build " + IntegerToString(TerminalInfoInteger(TERMINAL_BUILD))) + "\"}";
   string response;
   int status;
   if(!HttpPost("/api/ea/handshake", body, response, status))
     {
      g_status = "handshake failed (HTTP " + IntegerToString(status) + ")";
      return false;
     }
   g_bound   = true;
   g_last_hs = TimeGMT();
   g_status  = "bound: " + JsonString(response, "username", "?");
   return true;
  }

//+------------------------------------------------------------------+
//| Poll cycle                                                       |
//+------------------------------------------------------------------+
void DoPoll()
  {
   string response;
   int status;
   if(!HttpPost("/api/ea/poll", BuildResultsBody(), response, status))
     {
      if(status == 401)
        {
         g_auth_fail_streak++;
         g_status = "401 — token revoked/invalid";
         if(g_auth_fail_streak > 20)
            EventKillTimer(); // stop hammering a revoked token
         return;               // keep results for a future (re-authorized) poll
        }
      g_status = "poll unreachable (HTTP " + IntegerToString(status) + ")";
      return;                   // keep results; retry next tick
     }
   g_auth_fail_streak = 0;
   ArrayResize(g_results, 0); // results accepted by the server

   string cmds[];
   int n = JsonSplitArrayObjects(response, "commands", cmds);
   for(int i = 0; i < n; i++)
      ProcessCommand(cmds[i]);

   g_status = "last poll " + TimeToString(TimeGMT(), TIME_SECONDS) +
              " — claimed " + IntegerToString(n) + " command(s)";
  }

//+------------------------------------------------------------------+
//| Expert init/deinit/timer                                         |
//+------------------------------------------------------------------+
int OnInit()
  {
   if(StringLen(InpToken) < 16 || StringFind(InpToken, "nexus_ea_") != 0)
     {
      Alert("NexusBridgeEA: set InpToken to a nexus_ea_ token from the Nexus dashboard");
      return INIT_PARAMETERS_INCORRECT;
     }
   if(StringFind(InpBaseURL, "http") != 0)
     {
      Alert("NexusBridgeEA: InpBaseURL must start with http:// or https://");
      return INIT_PARAMETERS_INCORRECT;
     }
   EventSetTimer(MathMax(1, InpPollSec));
   g_status = "starting";
   PrintFormat("NexusBridgeEA: init base=%s poll=%ds magic=%I64d", InpBaseURL, InpPollSec, InpMagic);
   return INIT_SUCCEEDED;
  }

//+------------------------------------------------------------------+
//| Calendar — MT5 native economic calendar → nexus                   |
//+------------------------------------------------------------------+
int CalNum(const ENUM_CALENDAR_EVENT_IMPORTANCE importance)
  {
   switch(importance)
     {
      case CALENDAR_IMPORTANCE_HIGH:     return 3;
      case CALENDAR_IMPORTANCE_MODERATE: return 2;
      case CALENDAR_IMPORTANCE_LOW:      return 1;
      default:                           return 0;
     }
  }

// MqlCalendarValue holds values as long ×1e6; LONG_MIN means "no value".
// Convert to a JSON number, or the literal null when unset — never zero.
string CalValJson(const long raw)
  {
   if(raw == LONG_MIN)
      return "null";
   return DoubleToString((double)raw / 1000000.0, 6);
  }

string BuildCalendarBody(MqlCalendarValue &values[], const int start, const int count,
                         const bool has_more, const int chunk_index)
  {
   // Trade-server offset: TimeTradeServer() - TimeGMT(), rounded to seconds.
   const int server_offset = int(TimeTradeServer() - TimeGMT());
   string items = "";
   for(int i = start; i < start + count && i < ArraySize(values); i++)
     {
      MqlCalendarEvent event;
      if(!CalendarEventById(values[i].event_id, event))
         continue;                     // event metadata unavailable — skip honestly
      MqlCalendarCountry country;
      string currency = "";
      if(CalendarCountryById(event.country_id, country))
         currency = country.currency;
      if(currency == "")
         continue;                     // cannot route without a currency
      if(items != "")
         items += ",";
      items += "{\"id\":" + IntegerToString((long)values[i].id) +
               ",\"name\":\"" + JsonEscape(event.name) + "\"" +
               ",\"country\":\"" + JsonEscape(country.code) + "\"" +
               ",\"currency\":\"" + JsonEscape(currency) + "\"" +
               ",\"importance\":" + IntegerToString(CalNum(event.importance)) +
               ",\"time\":" + IntegerToString((long)values[i].time) +
               ",\"period\":" + IntegerToString((long)values[i].period) +
               ",\"actual\":" + CalValJson(values[i].actual_value) +
               ",\"forecast\":" + CalValJson(values[i].forecast_value) +
               ",\"previous\":" + CalValJson(values[i].prev_value) +
               ",\"revised_previous\":" + CalValJson(values[i].revised_prev_value) +
               ",\"updated\":" + IntegerToString((long)TimeTradeServer()) + "}";
     }
   return "{\"events\":[" + items + "]" +
          ",\"server_offset_sec\":" + IntegerToString(server_offset) +
          ",\"chunk_index\":" + IntegerToString(chunk_index) +
          ",\"has_more\":" + (has_more ? "true" : "false") +
          ",\"terminal_time\":" + IntegerToString((long)TimeTradeServer()) + "}";
  }

bool DoCalendarSync()
  {
   // Window is evaluated in trade-server time (calendar times are server-side).
   datetime from = TimeTradeServer() - InpCalendarDaysBack * 86400;
   datetime to   = TimeTradeServer() + InpCalendarDaysFwd  * 86400;
   MqlCalendarValue values[];
   ResetLastError();
   if(CalendarValueHistory(values, from, to, NULL, NULL) <= 0)
     {
      int err = GetLastError();
      // Silent failures (err=0) are the hardest to diagnose — always report
      // the count and error when verbose.
      PrintFormat("NexusBridgeEA: CalendarValueHistory returned <=0 (err=%d) "
                  "window=%s..%s — check View->Economic Calendar has data",
                  err, TimeToString(from, TIME_DATE), TimeToString(to, TIME_DATE));
      return false;                    // next timer tick retries the full window
     }
   const int total = ArraySize(values);
   if(total == 0)
     {
      g_last_cal = TimeGMT();          // empty window is still a successful sync
      return true;
     }
   int sent = 0, chunk = 0;
   while(sent < total)
     {
      const int count = MathMin(InpCalendarChunk, total - sent);
      const bool has_more = (sent + count < total);
      string response;
      int status = 0;
      string body = BuildCalendarBody(values, sent, count, has_more, chunk);
      if(!HttpPost("/api/ea/calendar", body, response, status))
        {
         PrintFormat("NexusBridgeEA: calendar chunk %d failed (status=%d) — cycle aborted, "
                     "full window re-covered on next sync", chunk, status);
         return false;                 // cursor not advanced → resume covers the gap
        }
      sent += count;
      chunk++;
     }
   g_last_cal = TimeGMT();
   if(InpVerbose)
      PrintFormat("NexusBridgeEA: calendar sync ok — %d events in %d chunk(s)", total, chunk);
   return true;
  }

//+------------------------------------------------------------------+
void OnDeinit(const int reason)
  {
   EventKillTimer();
   Comment("");
  }

void OnTimer()
  {
   // (Re)bind at start and every 10 minutes as a heartbeat refresh.
   if(!g_bound || TimeGMT() - g_last_hs >= 600)
     {
      if(!DoHandshake())
        {
         UpdateChart();
         return;
        }
     }
   DoPoll();
   if(InpCalendarSync && g_bound && TimeGMT() - g_last_cal >= InpCalendarSyncSec)
      DoCalendarSync();
   UpdateChart();
  }

void UpdateChart()
  {
   if(!InpVerbose)
      return;
   Comment("NexusBridgeEA\n" +
           "URL: " + InpBaseURL + "\n" +
           "Token: " + StringSubstr(InpToken, 0, 12) + "...\n" +
           "Magic: " + IntegerToString(InpMagic) + "\n" +
           "State: " + g_status + "\n" +
           "Pending results: " + IntegerToString(ArraySize(g_results)));
  }
//+------------------------------------------------------------------+
