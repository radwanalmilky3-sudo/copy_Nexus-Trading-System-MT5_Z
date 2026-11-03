import duckdb
con = duckdb.connect(r"C:\نسخه البرنامج الاصل\Nexus-Trading-System-MT5-main\data\nexus.duckdb", read_only=True)
tables = con.execute("SHOW TABLES").fetchall()
print("TABLES:", tables)
for t in tables:
    name = t[0]
    try:
        cnt = con.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
        print(f"  {name}: {cnt} rows")
    except Exception as e:
        print(f"  {name}: err {e}")
con.close()
