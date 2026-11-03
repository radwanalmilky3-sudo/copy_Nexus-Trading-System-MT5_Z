# 08 Datasets CATALOG

精简索引；字段细节见 `DATASETS.md`。

| ID | 类 | 官方 | PIT 类 | 主禁令 |
|---|---|---|---|---|
| dukascopy_tick | market | 项目下载 | quote_time | 非全市场深度 |
| yahoo_mid | market | Yahoo | mid | 非利润 |
| bis_reer | value | data.bis.org | current | 非 strict value 晋级 |
| pink_sheet | commodity | World Bank | current | 美元内生 |
| cftc_tff | positioning | cftc.gov | approximate | 非 OF |
| cboe_evz_family | vol | cboe.com | current | 非 1Y VRP |
| ofr_fsi | stress | financialresearch.gov | current | 非方向 |
| ecb_ciss | stress | ECB SDW | current | 非方向 |
| rtdsm | macro vintage | philadelphiafed | strict as-of | 非 surprise |
| alfred | macro vintage | alfred.stlouisfed.org | vintage_query | 非时钟/consensus |
| nyfed_pd | dealer | markets.newyorkfed.org | current aggregate | 2016–25 非 alpha |
| bis_gli_lbs_otc | funding structure | data.bis.org | false as-pub | 非日方向 |
| oanda_financing | cost | OANDA | account | 非价格真理 |
