# TOOLS_MAP — 开源工具对照（本项目选型）

更新日期：2026-07-17  
主源：`docs/OPEN_SOURCE_SELECTION_ZH.md` + 代码/依赖只读核验。  
问题轴：**bid/ask？PIT？多重检验？融资？**

## 决策总表

| 工具 | 决策 | bid/ask 执行 | PIT / vintage | 多重检验 | 融资/swap | 备注 |
|---|---|---|---|---|---|---|
| 项目自研核心 | **采用** | 是（多空侧） | 是（as-of、manifest） | BH/BY/DSR/PBO/SPA 核心 | 合同+挂接 | 共享敞口、点值、组合账本 |
| pandas / NumPy | 直接 | 数据结构 | join 工具 | 数值 | 数值 | 基座 |
| Pydantic / Typer / Rich / HTTPX / pytest / Ruff | 直接 | 配置不变量 | — | — | — | 工程 |
| yfinance | 直接复用 | **否**（公共 mid） | **否** | 否 | 否 | 仅公共研究入口 |
| statsmodels | 直接 | 否 | 否 | 协整等 | 否 | Engle–Granger 等 |
| scikit-learn | 直接 | 否 | 管道需自管泄漏 | 否（非 SPA/FDR） | 否 | elastic-net、校准 |
| Optuna | 可选 extra | 否 | 必须关在 WF 内层 | 增加试验数！ | 否 | 有界搜索；计入 N |
| NautilusTrader | 架构参考 | 强 | 可建 | 非主业 | 可扩展 | 过重，不整包 |
| Qlib | 评估未整包 | 偏股 | 自有数据层 | 有研究组件 | 弱 FX | FX graph/barrier 仍自定义 |
| LightGBM | 暂缓 | 否 | 泄漏风险高 | 否 | 否 | 先线性门槛 |
| QuantConnect Lean | 未作核心 | 有模型 | 平台相关 | 否内建本 lab 栈 | 有 | C#/部署过重 |
| Backtrader | 未采用 | 弱改造 | 弱 | 否 | 弱 | GPL + 活跃度 |
| Backtesting.py | 未采用 | 单资产 | 弱 | 否 | 弱 | 不适共享货币敞口 |
| vectorbt | 未作核心 | 向量化 mid 强 | 弱 | 参数扫描≠多重检验 | 弱 | 事件级 FX 风控旁路多 |
| Zipline | 未采用 | 股偏 | 管道老 | 否 | 弱 | 上游慢 |
| **arch** | **交叉核验 only** | 否 | 否 | SPA 接口存在 | 否 | **见下陷阱** |

## arch SPA studentize 陷阱（显式）

审计结论（选型文档 + 项目 SPA 模块动机）：

1. 官方 `arch` SPA 的 **`studentize` 参数可能不进入真实计算路径** → 即使用户以为开启 studentization，统计量仍可能非 Hansen studentized。  
2. **退化输入可返回 p=0**，违反 plus-one 经验 p 规范。  
3. 因此：**不得**把 `arch.bootstrap.SPA` 当作正式 Hansen studentized SPA。  
4. 项目对策：
   - 透明实现 `hansen_spa.hansen_spa_test`（强制 studentize + recentering + plus-one）
   - `prepare_spa_inputs` 仅适配 loss 供可选交叉核验
   - 正式 runner 当前 **`spa_executed=False`**（输入校验 ≠ 执行）
5. `pyproject.toml` research extra 目前列 `optuna`，**未**把 arch 钉为硬依赖（与“可选交叉核验”一致）。

## 能力缺口：为何自研

| 需求 | 通用回测框架常见缺口 | 本项目位置 |
|---|---|---|
| 共享币种敞口 | 单品种假设 | portfolio / execution |
| 动态点值 / JPY | 固定 pip | instrument metadata |
| 保守 bar/tick 成交 | mid OHLC | bid/ask 入出场 |
| 历史 swap as-of | 固定 overnight | `attach_historical_swaps` + cost contract |
| 完整试验披露 | 只报最优 | registry + DSR N |
| 同步 stationary bootstrap 面板 | 少见 | `statistical_validation` |
| cost_incomplete 门 | 常默认有成本 | `broker_cost_contract` |

## 使用红线

```text
yfinance/mid  → 永不 broker_ready
Optuna 试验  → 全部计入 total_trials_evaluated
arch SPA     → 交叉核验；主结论用 hansen_spa_test
vectorbt 网格 → 参数扫描次数进 FDR/DSR 分母
任何工具净收益 → 无目标账户融资史则 cost_incomplete
```

## 与验证栈接口

```text
工具产出候选收益
  → validate_daily_net_return_matrix
  → BH/BY + DSR + PBO
  → (未来) hansen_spa_test
  → 永不自动 trading_approval
```
