import MetaTrader5 as mt5
from datetime import datetime, timedelta, timezone

SYMBOLS = ["XAUUSD","XAGUSD","BTCUSD","ETHUSD","DXY","EURUSD","GBPUSD",
           "USDJPY","USDCHF","AUDUSD","USDCAD","US30","US500","WTI"]

if not mt5.initialize():
    raise SystemExit(f"initialize failed: {mt5.last_error()}")

print("server:", mt5.account_info().server)
now_utc = datetime.now(timezone.utc)
t_to = now_utc.replace(tzinfo=None)          # تحقق: هل MT5 يعامل الnaive كـUTC؟
t_from = t_to - timedelta(days=7)

for s in SYMBOLS:
    mt5.symbol_select(s, True)
    info = mt5.symbol_info(s)
    if info is None:
        print(f"{s:8} NOT FOUND {mt5.last_error()}")
        continue
    tick = mt5.symbol_info_tick(s)
    offset = round(tick.time - now_utc.timestamp()) if tick else None
    ticks = mt5.copy_ticks_range(s, t_from, t_to, mt5.COPY_TICKS_ALL)
    rates = mt5.copy_rates_range(s, mt5.TIMEFRAME_M1, t_from, t_to)
    print(f"{s:8} digits={info.digits} point={info.point} "
          f"tick_size={info.trade_tick_size} tick_value={info.trade_tick_value} "
          f"contract={info.trade_contract_size} "
          f"profit_cur={info.currency_profit} margin_cur={info.currency_margin} "
          f"offset_s={offset} "
          f"ticks_7d={0 if ticks is None else len(ticks)} "
          f"M1_7d={0 if rates is None else len(rates)}")

mt5.shutdown()
