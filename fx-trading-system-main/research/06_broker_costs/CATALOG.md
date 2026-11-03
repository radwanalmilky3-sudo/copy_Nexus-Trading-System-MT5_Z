# 06 Broker Costs Catalog

| slug | 来源 | URL | L | 用途 | 状态 | 笔记 |
|---|---|---|---|---|---|---|
| oanda_financing_docs | OANDA financing / swap docs | https://www.oanda.com/us-en/trading/financing-fees/ ；UK https://www.oanda.com/uk-en/trading/financing-costs/ ；BVI https://www.oanda.com/bvi-en/cfds/financing-costs/ ；FAQ https://help.oanda.com/us/en/faqs/financing-costs-us.htm | L4 | 账户融资合同 | verified_urls + deep_note | [notes/oanda_financing_docs.md](./notes/oanda_financing_docs.md) |
| oanda_financing_api | financing history 导出 | https://labs-api.oanda.com/v1/financing-rates ；脚本 `scripts/download_oanda_financing_history.py` | L4 | 近年公开序列归档 | script_present；≠10y 账户史 | 见 SWAP_FORWARD_SOURCES |
| du_cip | Du–Tepper–Verdelhan | https://doi.org/10.1111/jofi.12620 ；NBER https://www.nber.org/system/files/working_papers/w23170/w23170.pdf | L4–L5 | CIP 字段与 Qend | deep_note | [notes/du_tepper_verdelhan_cip.md](./notes/du_tepper_verdelhan_cip.md) |
| borio_basis_2016 | BIS basis | https://www.bis.org/publ/qtrpdf/r_qt1609e.htm | L4 | basis 定义 | deep_note | [notes/borio_bis_basis.md](./notes/borio_bis_basis.md) |
| borio_fxswap_2022 | BIS FX swap | https://www.bis.org/publ/qtrpdf/r_qt2212h.htm | L4 | 表外美元义务 | deep_note（同篇） | [notes/borio_bis_basis.md](./notes/borio_bis_basis.md) |
| retail_vs_interbank_exec | 零售 vs 银行间 | OANDA charges + 项目 bid/ask 执行语义 | L4 | mid≠可实现 | partial | SWAP_FORWARD_SOURCES §3 |
| swap_forward_sources | 项目内来源审计 | 本目录 | L4 | 有/缺对照 | written | [SWAP_FORWARD_SOURCES.md](./SWAP_FORWARD_SOURCES.md) |
| cip_contract_checklist | 字段清单 | 本目录 | L4–L5 | fail-closed 合同 | written | [CIP_CONTRACT_CHECKLIST.md](./CIP_CONTRACT_CHECKLIST.md) |
