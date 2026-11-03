# 高星开源项目选型记录

审计日期：2026-07-15。星数是审计时 GitHub API 快照，会随时间变化。

| 项目 | 当时星数 | 许可证 | 决策 | 用途/原因 |
|---|---:|---|---|---|
| [NautilusTrader](https://github.com/nautechsystems/nautilus_trader) | 24,694 | LGPL-3.0 | 架构参考 | 事件驱动、模型/风险/执行分层；整包引入对轻量本地 Python 交付过重 |
| [yfinance](https://github.com/ranaroussi/yfinance) | 24,700 | Apache-2.0 | 直接复用 | 公共研究行情下载与缓存入口 |
| [statsmodels](https://github.com/statsmodels/statsmodels) | 11,510 | BSD-3-Clause | 直接复用 | Engle–Granger 协整检验，避免重写统计检验 |
| [scikit-learn](https://github.com/scikit-learn/scikit-learn) | 66,680 | BSD-3-Clause | 直接复用 | Elastic-net Logistic、预处理、Platt 校准和概率评分 |
| [Optuna](https://github.com/optuna/optuna) | 14,502 | MIT | 可选依赖 | 后续只在 walk-forward 内层做有界参数搜索 |
| [Qlib](https://github.com/microsoft/qlib) | 46,238 | MIT | 评估后未整包引入 | 因子理念成熟，但默认数据/组合抽象偏股票；FX graph 与 barrier 仍需自定义 |
| [LightGBM](https://github.com/microsoft/LightGBM) | 18,561 | MIT | 暂缓 | 非线性交互候选；先用可解释线性基线建立无泄漏门槛 |
| [QuantConnect Lean](https://github.com/QuantConnect/Lean) | 20,528 | Apache-2.0 | 未作为核心 | 功能完整但 C#/Python 混合部署和本地 broker 模型明显超出本项目重量 |
| [Backtrader](https://github.com/mementum/backtrader) | 22,439 | GPL-3.0 | 未采用 | 活跃度较低、许可证和跨货币组合敞口改造成本不合适 |
| [Backtesting.py](https://github.com/kernc/backtesting.py) | 8,674 | AGPL-3.0 | 未采用 | 适合单资产研究，不适合本系统共享货币敞口的核心要求 |
| [vectorbt](https://github.com/polakowo/vectorbt) | 8,310 | 仓库 API 未识别 | 未作为核心 | 参数扫描很强，但事件级组合 FX 风控仍需大量旁路逻辑 |
| [Zipline](https://github.com/quantopian/zipline) | 19,974 | Apache-2.0 | 未采用 | 上游更新慢，FX/broker 语义不是其强项 |
| [arch 8.0.0](https://github.com/bashtage/arch/tree/038d78b709e75f2590890757af32705817a6fad8) | — | NCSA | 仅作交叉核验 | 官方 SPA 的 `studentize` 参数未进入计算路径，退化输入还可返回 p=0；不能直接作为正式 Hansen studentized SPA，项目采用透明内部实现 |

此外直接使用 pandas、NumPy、Pydantic、Typer、Rich、HTTPX、pytest 和 Ruff；它们分别承担
表格计算、数值计算、配置不变量、CLI、终端报告、practice HTTP、测试与静态检查。项目自研的
代码被限定在成熟库无法正确表达的部分：共享币种敞口、动态点值、周内退出、组合风险和
bar 级保守成交。
