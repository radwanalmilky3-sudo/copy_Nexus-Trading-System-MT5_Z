# FX 微观结构综述地图（survey map → 03 深读）

- 深度层级: L3（地图；单篇精读在 03）
- 引用链角色: foundational map
- DOI/URL: 见下表；本文件不替代单篇 DOI
- 开放获取: 视单篇；项目已有 03 笔记与部分 methodology PDF
- 本项目映射: FIX-W / LOCAL-PAPER / spread 过滤 / blackout；**无签名 OF 则机制 only**
- 复制状态: 分条见 03 CATALOG
- 公式置信度: medium（地图层）；单篇 notes 为准
- published premium vs implementable: 微观结构“可预测片段”最易被点差与定盘竞争摧毁
- 2016–2025 外推风险: 高（电子化、last-look、定盘改革、零售 LP 结构）

## 1. 经济机制（综述层）

FX 微观结构把汇率变动从“宏观消息瞬间进入 mid”扩展为：

1. **库存 / 做市**：dealer 管理库存与风险极限 → 报价与成交反馈。  
2. **订单流信息**：签名主动买卖量聚合分散信息（Evans–Lyons 线）；宏观新闻可经 OF **间接**进入价格。  
3. **流动性状态**：价差、深度、弹性随时段与压力变化（Mancini–Ranaldo–Wrampelmeyer）。  
4. **基准 / 定盘**：WMR 等窗口吸引对冲流，产生可重复的日内模式与抢跑问题（Krohn–Mueller–Whelan；Melvin–Prins）。  
5. **本地信息 / 营业时段**：本地交易时段与海外时段收益不对称（Breedon–Ranaldo）。  

教科书锚点：**Lyons (2001)** *The Microstructure Approach to Exchange Rates* — 建立 OF、报价、银行间分层语言。  
现代调查线：King–Osler–Rime 等 survey（planned 落盘）把电子化与多平台结构纳入。

## 2. 精确公式（跨文献公共符号）

```text
# 签名订单流
OF_t = buyer_initiated_volume - seller_initiated_volume

# 价格影响（示意）
Δp_t = α + β News_t + γ OF_t + ε_t
# 间接渠道: OF_t = δ News_t + η_t

# 流动性（示意；具体度量见 Mancini 笔记）
spread_t = ask_t - bid_t
# 或有效价差、lambda 冲击系数、重回中间价时间

# 定盘窗（示意；精确 civil→UTC 见 WMR methodology）
# FIX window = [T0, T1] around benchmark
# 策略收益必须用窗内可成交价，不能用 1h bar 冒充 :55–:00
```

## 3. 数据与样本（地图）

| 文献线 | 典型数据 | 本项目 |
|---|---|---|
| Evans–Lyons | 授权交易级签名 OF | **无** → 机制 only |
| Andersen / Faust | 高频 + 定时公告 + consensus | consensus 通常缺 |
| Krohn et al. | 定盘窗 tick | Dukascopy 可部分逼近，非银行间 |
| Breedon–Ranaldo | 本地时段 | 时区/DST 合同 |
| Mancini et al. | 多指标流动性 | spread 可；深度有限 |
| WMR/ECB methodology | 官方规则 | `_pdfs/_official/` |

## 4. 成本与可实现性

- 学术日内异象在**指示性 mid** 上成立 ≠ 零售可成交净收益。  
- 定盘策略对点差、滑点、拒单极度敏感；项目冻结规格要求成本后可转负。  
- CFTC 仓位、quote size、tick count **都不是** signed OF。

## 5. 识别与稳健性

| 陷阱 | 否决 |
|---|---|
| 用 1h bar 验证 5 分钟定盘窗 | 时间聚合错误 |
| 用未来 spread 过滤入场 | look-ahead |
| 用 CFTC 替代 OF | 定义错误 |
| 无 consensus 的 “surprise” 方向 | 禁止 |
| 单一零售源宣称市场深度 | 外推失败 |

## 6. 复制清单（总表）

| 字段 | 需要？ | 本项目 | 缺失时 |
|---|---|---|---|
| 签名 OF | Evans 线 | 无 | fail closed / 机制 only |
| 定盘 civil 时间与 DST | FIX | 可定义 | 见 01/03 |
| Tick bid/ask | 成本 | Dukascopy 进行中 | 净收益 fail closed |
| Consensus | surprise | 通常无 | 禁止方向 surprise |
| 流动性指标 | 过滤 | 部分 | 保守 q90 等扩展 |

## 7. 本项目映射

| 实验 | 文献锚 | 笔记 |
|---|---|---|
| FIX-W | Krohn–Mueller–Whelan | `03/.../krohn_mueller_whelan.md` |
| LOCAL-PAPER | Breedon–Ranaldo | `03/.../breedon_ranaldo.md` |
| WMR 月末 | Melvin–Prins | `03/.../melvin_prins.md` |
| spread 过滤 | Mancini–Ranaldo–Wrampelmeyer | `03/.../mancini_ranaldo_wrampelmeyer.md` |
| blackout | Andersen；Faust | `03/.../andersen_et_al_aer.md` 等 |
| OF 机制 | Evans–Lyons | `03/.../evans_lyons.md` |
| 定盘规则 | LSEG WMR | `03/.../lseg_wmr_methodology.md`；`_pdfs/_official/wmr_fx_methodology.pdf` |

**结构背景：** `bis_triennial_2022_fx.md`（成交工具与中心地理）。

## 8. 引用链

| 角色 | 文献 | 关系 |
|---|---|---|
| textbook | Lyons 2001 | 共同语言 |
| foundational | Evans–Lyons | OF 与新闻 |
| liquidity | Mancini et al. | 流动性度量 |
| fix | Krohn et al.；Melvin–Prins | 定盘 |
| official | WMR methodology；BIS Triennial | 规则与结构 |
| 本库 03 | CATALOG + INTRADAY_SOURCE_MAP | 实验映射 |

## 9. 精读问题

1. 在无 OF 时，哪些“微观结构 alpha”主张必须降级为时段/定盘**描述性**事实？  
2. Dukascopy 单一源对 Mancini 式多平台流动性指标的哪些分量不可识别？  
3. 定盘改革后，Krohn 窗定义是否需冻结新 methodology 版本号？  
4. 项目 blackout 规则如何同时服务统计干净与可交易现实？  
5. Triennial 显示 FX swap 主导时，现货定盘策略的资金腿风险是否被系统低估？
