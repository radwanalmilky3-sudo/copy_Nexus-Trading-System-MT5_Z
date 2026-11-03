"""Read account-owned research candles and availability evidence."""
import json
from datetime import datetime

async def load_research_series(store,owner,account_id,timeframe,start=None,end=None,as_of=None):
    account=await store.get_account(owner,account_id)
    def read():
        conn=store.owner_store._conn
        tables={r[0] for r in conn.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='main'").fetchall()}
        if 'research_account_candles' not in tables:return []
        availability='research_candle_availability' in tables
        sql=('SELECT c.symbol,c.bar_json,a.available_at FROM research_account_candles c LEFT JOIN research_candle_availability a ON c.owner_id=a.owner_id AND c.account_id=a.account_id AND c.symbol=a.symbol AND c.timeframe=a.timeframe AND c.bar_time=a.bar_time' if availability else 'SELECT c.symbol,c.bar_json,NULL FROM research_account_candles c')
        sql+=' WHERE c.owner_id=? AND c.account_id=? AND c.timeframe=?'
        args=[owner,account_id,timeframe]
        if start is not None:sql+=' AND c.bar_time>=?';args.append(start)
        if end is not None:sql+=' AND c.bar_time<=?';args.append(end)
        sql+=' ORDER BY c.symbol,c.bar_time'
        return [{'symbol':s,**json.loads(bar),'available_at':at,'available_at_epoch':datetime.fromisoformat(at).timestamp() if at else None,'publication_time':None,'close_utc_epoch':None} for s,bar,at in conn.execute(sql,args).fetchall()]
    rows=await store.owner_store._execute_locked(read)
    if as_of is not None:
        from shared.research_context_engine import point_in_time
        rows=point_in_time(rows,as_of)
    return account,rows
