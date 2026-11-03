# 10_surveys_handbooks

**深度门槛：** L3（学术综述 / 手册章）或 L2（官方调查 methodology，仅结构校准）。  
**角色：** 建立解释谱系与引用锚点；**不替代** `02` / `03` / `04` 单篇精读与复制合同。

## 收

- *Annual Review* / *Handbook* / 顶刊 survey：currency risk premia、carry、forward premium
- FX 微观结构教科书与综述线（Lyons；Evans–Lyons；流动性）
- 资产定价方法综述（可映射到 FX 因子搜索与多重检验）
- BIS Triennial 等官方调查的**解释性**笔记
- 对 SDF–汇率 “asset market view” 的批判性理论文

## 不收

- 零售入门课、无公式信号博客、付费课大纲  
- 把 Triennial 月化后当 alpha  
- 用综述句子替代论文字段级复制合同  
- 盗版 PDF（无法合法 OA 则只留书目/链接）

## 产出

| 文件 | 内容 |
|---|---|
| `CATALOG.md` | survey / handbook / textbook / official survey 总表 |
| `notes/*.md` | L3 深度笔记（8 项规格） |
| `../notes/READING_STACK_ZH.md` | 跨目录精读栈（链到 02/04/06 与 `_pdfs/`） |

## 使用规则

1. 综述 = **地图**；交易主张必须落到单篇 + 成本 + 验证。  
2. 教科书与论文样本定义冲突时，以**论文复制合同**为准。  
3. 任何“可交易结论”过 `04_validation_methods` + `06_broker_costs`。  
4. BIS Triennial **永不进** FDR 方向族。  
5. `_pdfs/` 部分文件名与正文不一致 → 以笔记首页标题 / NBER 编号为准（见 CATALOG「PDF 标签更正」）。

## 教科书 / 手册书目（链接级）

| 条目 | 类型 | 为何相关 | 获取 |
|---|---|---|---|
| Lyons, *The Microstructure Approach to Exchange Rates* | 教科书 | 订单流、报价、银行间微观结构 | 商业出版 / 图书馆 |
| Sarno & Taylor, *The Economics of Exchange Rates* | 教科书 | PPP、UIP、宏观 FX | 商业出版 |
| Mark, *International Macroeconomics and Finance* | 教科书 | 跨期宏观与汇率 | 商业出版 |
| Obstfeld & Rogoff, *Foundations of International Macroeconomics* | 教科书 | 宏观国际金融地基 | 商业出版 |
| James, Marsh & Sarno (eds.), *Handbook of Exchange Rates* | 手册 | Burnside carry 章等 | 商业出版；NBER 章 OA 见 notes |
| Evans, *Exchange-Rate Dynamics* | 教科书 | 微观+宏观统一 | 商业出版 |
| Cochrane, *Asset Pricing* | 教科书 | SDF / GMM 横截面语言 | 商业出版 |
| BIS Triennial Central Bank Survey | 官方调查 | 全球成交结构 | https://www.bis.org/statistics/rpfx.htm |
| BIS AER / 季报 FX 章 | 官方 | 美元、流动性、basis | bis.org |
| LSEG WMR FX Methodology | 官方方法 | 定盘窗口 | 见 `_pdfs/_official/` |

## 推荐阅读顺序（项目内）

1. 本目录 survey 笔记（解释谱系 + 否决）  
2. `01_foundations` 定盘 / settlement / swap  
3. `02_factor_literature` carry–mom–value 主链  
4. `03_microstructure_intraday` 定盘与流动性  
5. `04_validation_methods` 多重检验  
6. `06_broker_costs` 可实现融资  
7. 细节顺序见 `../notes/READING_STACK_ZH.md`

## notes/ 状态（2026-07-17 Survey-Agent）

| slug | 状态 |
|---|---|
| `burnside_arfe_2011` | deep_noted |
| `burnside_handbook_carry_risk` | deep_noted（完整）；`burnside_handbook_2012` 为短卡指针 |
| `burnside_graveline_asset_market_view` | deep_noted |
| `bis_triennial_2022_fx` | deep_noted |
| `fx_microstructure_survey_map` | deep_noted（地图，链 03） |
| `lustig_verdelhan_handbook_2012` | 短卡；**PDF 误标警告** |
| `TEXTBOOKS_AND_SURVEYS` | 书目短表 |
