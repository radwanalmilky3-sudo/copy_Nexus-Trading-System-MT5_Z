# Dukascopy 冻结后 Forward 数据合同

日期：2026-07-23。

本合同只设计未来数据管道，不启动额外下载。当前项目已查看市场历史至 `2026-07-13`，因此
`2026-01-01` 至 `2026-07-13` 不能重新命名为 untouched forward。正式 forward 的第一条
观测必须严格满足：

```text
observation_time > alpha_freeze_time
```

当前没有通过历史筛选的 frozen alpha，故配置固定为
`status=blocked_until_alpha_freeze`、`alpha_freeze_time=null`。不得预填一个方便的日期。

## 存储规则

- 历史 14 库批次保持只读，不向其中追加 forward payload；
- 每次采集写入独立 generation，先进入 quarantine；
- generation 必须有源 manifest、SHA-256、UTC 区间、父 generation SHA 和 immutable 标志；
- 验收后只把 manifest 加入 accepted 链，不覆盖旧 generation；
- 相同小时再次抓取若字节不同，创建新 revision generation，不能原地替换；
- 外部宏观 vintage、事件、融资和 forward points 使用同样的 `available_time` 与版本链；
- 任何数据重抓、模型调参或特征变化都不能回写原 alpha freeze。

## 评价门

- 前 90 天只能标记 `collecting`；
- 至少 180 天且覆盖不同波动状态后才允许申请 review；
- 评价只运行 frozen alpha，不重新筛选因子、窗口、方向、阈值或成本假设；
- 失败即淘汰；修改模型必须建立新的 registry 条目、freeze 和 forward 起点；
- forward 通过也不自动产生交易批准。

机器配置位于 `configs/dukascopy_forward_collection.yaml`，校验实现位于
`src/fx_system/forward_collection_contract.py`。
