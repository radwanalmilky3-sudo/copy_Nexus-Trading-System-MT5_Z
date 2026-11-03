# 纯价格因子第一轮最终整改接手任务书

日期：2026-07-22。

项目根目录：`/Users/open/fx-trading-system`

研究产物目录：`outputs/price_only_round1_20260717/`

本文件位于 `docs/`，而不是研究产物目录。原因是研究产物目录已有完整 artifact manifest；把接手
说明放入该目录会立即改变文件集合并再次破坏 manifest 闭合。

## 1. 任务性质和不可改变的结论

这不是新一轮因子挖掘，也不是重新评价 EURUSD/GBPUSD 因子是否盈利。本任务只负责完成第一轮
历史筛选的工程整改、证据链收口和回归测试硬化。

第一轮历史已经打开收益标签，且经独立验收确认违反了原冻结合同。无论本次代码和文档整改得
多完善，下列状态都不得改变：

```text
historical_run_status=invalidated_but_data_inspected
provisional_interpretation=insufficient_valid_oos_evidence
historical_run_valid_for_inference=false
approved_strategy=false
trading_approval=false
formal_net_returns_ready=false
fresh_forward_required=true
```

整改成功表示“这次失败记录已经诚实、完整、可审计，未来运行的合同已被锁死”，不表示历史结果
重新获得统计有效性，也不表示已经找到可盈利策略。

## 2. 来龙去脉

### 2.1 原始第一轮

第一轮仅使用 EURUSD 和 GBPUSD 的 Dukascopy 价格、bid/ask、点差及时间字段，在
`[2016-01-01, 2025-09-15)` 上运行：

- 16 个纯价格因子；
- 21、42、63 个交易日三个 horizon；
- 4 个 walk-forward fold；
- 每折 48 个统一 BH 检验；
- 共 192 条训练检验；
- 训练期选中 11 条 factor/horizon/fold；
- 原程序实际物化了全部 192 条 OOS 统计，而不是仅物化 11 条训练入选项。

原始任务书见 `docs/PRICE_ONLY_FACTOR_MINING_AGENT_BRIEF_ZH.md`。原始交付报告见
`outputs/price_only_round1_20260717/ROUND1_DELIVERY_REPORT_ZH.md`。

### 2.2 独立验收发现的问题

`ROUND1_INDEPENDENT_REVIEW_ZH.md` 在 2026-07-21 确认：

1. 两行 `_entry_time == _feature_time`，但程序没有按预注册失败关闭；
2. 全 catalog 的 192 条 OOS 被打开，原 registry 只登记 11 条；
3. 每个 horizon 都有部分 OOS 标签越过 `test_end_exclusive`；
4. OOS 每品种每折约 9--10 个再平衡点，达不到统计量最小样本门，全部 OOS IC=0 只能解释为
   `insufficient_valid_oos_evidence`；
5. 原始预注册及源码 hash 链没有完整闭合；
6. 负对照未执行，且机器 verdict 和主 registry 不完整。

因此第一轮从原先的空模型解释改判为 `invalidated_but_data_inspected`，但已经打开的 192 条训练
暴露和 192 条 OOS 暴露不能归零。

### 2.3 第一轮整改已经完成的内容

第一轮整改完成了：

- registry 按 192 训练 + 192 OOS 如实登记；
- `screen_summary.json` 和 `two_pair_run_summary.json` 增加安全 verdict；
- 未来 OOS 只对训练入选项计算；未入选项保留 `oos_evaluated=false` 骨架；
- OOS 增加 per-horizon `label_end < test_end_exclusive` 过滤；
- 时间顺序违规改为 raise；
- 增加完整 output artifact manifest。

第一次整改后的复验又发现：时间门仍在 return 计算之后、失败路径缺少测试、Ruff 实际失败、
artifact manifest 漏整改报告、旧 summary 解释未标失效，而且原 prereg 被事后字段覆盖。

### 2.4 第二轮整改已经完成的内容

第二轮整改在 2026-07-22 完成了以下实质修复：

- `src/fx_system/long_horizon.py` 现在先验证 entry/feature 时间，再处理 entry price；每个 horizon
  也先验证 label end，再计算 forward return；
- `src/fx_system/long_horizon_research.py` 的 per-horizon spill 过滤当前实现正确；
- 新增时间失败和 spill 相关测试；
- Ruff 已通过；全量测试实测 488 collected/passed；
- summary 中旧解释已改名为 `original_invalidated_interpretation`，当前解释明确为 invalidated；
- 新建 `post_run_adjudication_manifest.json` 及 sidecar；
- `output_artifact_manifest.json` 已覆盖除自身及 sidecar 外的 23 个文件；目录共 25 个文件；
- 23 项 bytes/SHA-256 全部匹配，6 个 sidecar 全部通过；
- 主 registry 和独立 registry entry 均为 invalidated、192/192，screen hash 与当前文件一致。

这些已通过项不要回滚，也不要借整改之名重写原始统计 CSV、压缩数据集或市场数据。

## 3. 当前仍未通过的三个问题

### 3.1 原始 prereg provenance 被描述得过于确定

当前 `preregistration_manifest.json` 声称自己是 screen-time frozen 内容，但它不是原始字节快照。

已知证据：

- 独立验收报告第 106--107 行记录：原 prereg 的 `immutable_inputs.runner` 是
  `3740 bytes / 5ab87d41...`；
- 当前 prereg 第 52--55 行已变成实际 runner 的
  `3774 bytes / b93f286a...`；
- 整改报告第 93--95 行也承认 runner SHA 是事后刷新；
- 当前 prereg 和 sidecar 的修改时间均为 2026-07-22；
- 目录中没有原始 prereg bytes、原始 sidecar或可信备份。

因此，精确的原始 prereg 文件目前不可恢复。允许重构其已知内容，但不允许把重构文件描述成原始
冻结文件，更不允许猜测或伪造原始文件 SHA。

### 3.2 Post-run adjudication 的当前实现 hash 已过期

当前 `post_run_adjudication_manifest.json` 记录：

```text
src/fx_system/long_horizon.py
bytes=55418
sha256=eb658c43b1b9f90afc3542ce759b31d488e26bfe98ac1e63eca13a059b55ff98
```

2026-07-22 复验时的实际文件是：

```text
bytes=55720
sha256=16918ad8a74000f172a286b6f47375a2d0c05cf3afebd6ce61bf695e15996bb6
```

Manifest 还只登记第一轮整改的 `485 passed`，没有登记第二轮的 488 tests 和新的时间门实现。
其他四个 `implementation_inputs` 在本次复验时匹配，但最终仍必须全部重新计算，不能直接照抄
本任务书中的基线值。

### 3.3 Spill 回归测试名义存在，但不能捕获过滤被删除

`tests/test_long_horizon.py::test_evaluated_oos_respects_per_horizon_spill_gate` 当前最终只断言：

```python
group["test_end_exclusive"] == fold_row["test_end_exclusive"]
```

生产代码无论是否执行 spill filter，都会把同一个 fold 值写入聚合结果。因此即使删除
`long_horizon_research.py` 第 312--316 行的真正过滤，这个测试仍可能通过。测试没有读取或捕获
实际传入 `_one_factor_statistic` 的 `test_horizon`，也没有断言这些输入行的
`_label_end_time_{horizon}d < test_end_exclusive`。

此外，测试必须先断言至少发生一次 `oos_evaluated=true`，防止空集合上的循环使测试虚假通过。

## 4. 接手 Agent 的精确工作包

### WP1：诚实重建 prereg provenance

目标不是恢复已经丢失的原始字节，而是让机器记录准确表达“哪些是原始已知事实，哪些是事后
重构，哪些不可恢复”。

最低要求：

1. 不删除当前 prereg，不伪造原始 sidecar。
2. 在 `preregistration_manifest.json` 增加明确的 provenance 字段，建议至少包含：

   ```json
   {
     "provenance_quality": "reconstructed_post_run_not_byte_identical",
     "original_preregistration_bytes_available": false,
     "original_preregistration_sha256": null,
     "reconstruction_date": "2026-07-22",
     "reconstruction_basis": [
       "ROUND1_INDEPENDENT_REVIEW_ZH.md",
       "ROUND1_DELIVERY_REPORT_ZH.md",
       "surviving_artifacts_and_sidecars"
     ]
   }
   ```

3. 把当前 `manifest_scope_note` 中“Frozen at screen-run time”改成不误导的表述，例如
   “reconstructed representation of known screen-time intent; not the original byte-identical file”。
4. 在 `post_run_adjudication_manifest.json` 增加 `original_preregistration_provenance`，至少记录：
   - 原始 bytes/SHA 不可用；
   - 原 prereg 曾声明 runner `3740 / 5ab87d41...`；
   - 实际 screen runner 为 `3774 / b93f286a...`；
   - 该差异由独立验收发现，不能在事后悄悄覆盖；
   - 当前 prereg 是重构记录而非原件。
5. 明确区分：
   - `original_declared_inputs`：原 prereg 当时声明的内容；
   - `screen_execution_inputs`：有证据支持的实际执行输入；
   - `remediation_implementation_inputs`：整改后当前代码。

如果接手 Agent 在其他可信归档中找到原始 prereg，才可以新增只读的 exact-byte snapshot 和
sidecar；找到前必须保持 `original_preregistration_bytes_available=false`。

### WP2：冻结第二轮整改后的真实实现

1. 重新计算以下文件的 bytes 和 SHA-256：
   - `src/fx_system/long_horizon.py`；
   - `src/fx_system/long_horizon_research.py`；
   - `src/fx_system/dukascopy_daily.py`；
   - `src/fx_system/long_horizon_config.py`；
   - `src/fx_system/statistical_validation.py`；
   - `tests/test_long_horizon.py`；
   - `scripts/run_two_pair_long_horizon_research.py`；
   - `configs/long_horizon_two_pair_time_series.yaml`。
2. 不要用一个含糊的 `implementation_inputs` 覆盖所有历史阶段。建议在 adjudication 中保存：
   - `screen_execution_inputs`；
   - `first_remediation_inputs`，若证据不全则明确 incomplete；
   - `second_remediation_inputs`，记录最终代码和测试 hash；
   - 每轮的测试数、Ruff 命令和日期。
3. 把 `full_pytest=485 passed` 明确标为第一轮整改记录；新增第二轮/最终验证记录。完成 WP3 后
   测试数可能超过 488，应记录实际 collect 数，不能硬编码 488。
4. 保留历史 hash，不要通过静默改值把旧 hash 假装成当时就存在的正确值。

### WP3：写一个会真实失败的 spill 回归测试

推荐实现方式有两种，至少完成一种；优先采用 A。

#### 方案 A：提取纯过滤 helper，并做边界单元测试

把生产代码第 312--316 行提取为语义明确的内部 helper，例如：

```python
def _filter_oos_horizon_before_test_end(
    test: pd.DataFrame,
    horizon: int,
    test_end_exclusive: pd.Timestamp,
) -> pd.DataFrame:
    ...
```

单元测试必须构造四类行：

- label end 严格早于 test end：保留；
- label end 等于 test end：排除；
- label end 晚于 test end：排除；
- label end 为 `NaT`：排除。

断言必须直接检查返回 frame 中的时间列，不得只检查聚合 summary 元数据。

#### 方案 B：捕获实际进入统计函数的 OOS frame

使用 `monkeypatch` 包装 `long_horizon_research._one_factor_statistic`。当
`run_bootstrap=False` 时，捕获 `frame.copy()`、horizon 和对应 fold；逐次断言：

```python
assert not frame.empty  # 或另行证明至少有一次真实 evaluated 调用
assert frame[f"_label_end_time_{horizon}d"].notna().all()
assert (
    frame[f"_label_end_time_{horizon}d"] < fold_row["test_end_exclusive"]
).all()
```

必须确保 synthetic 配置至少选择一个训练假设并触发一次真实 OOS 调用；测试末尾增加
`assert captured_oos_frames`，禁止空列表通过。

无论采用哪个方案，做一次 mutation sanity check：临时移除或反转生产 spill 条件，确认新测试
失败；然后恢复正确条件。不要把 mutation 留在工作树。

### WP4：加强 label-end 的集成测试

当前 label-end 测试只直接调用私有 helper。源码调用顺序目前正确，但测试没有锁住
`build_long_horizon_labels` 是否始终调用该门。

新增或改造为 build-level 测试：构造 `_label_end <= _entry_time` 的 daily frame，直接调用
`build_long_horizon_labels` 并断言 `ValueError`。如需严格证明 return 尚未计算，可 monkeypatch
`numpy.log` 为一旦调用就抛出 `AssertionError`；期望最终收到的是时间合同 `ValueError`，而不是
`AssertionError`。

这个工作包风险较低，但应与 WP3 同轮完成，避免下一次重构绕过 helper。

### WP5：整理整改报告并重建 hash 链

`ROUND1_REMEDIATION_REPORT_ZH.md` 当前同时保留第一轮的“485 passed / 19 项”和第二轮的
“488 passed / 23 项”，如果没有明确阶段标签会形成冲突。

要求：

1. 按“第一轮整改记录”“第二轮整改记录”“最终收口”整理章节；历史数字可保留，但必须标明对应
   阶段，不能都写成当前状态。
2. 报告明确说明原 prereg 不可按 exact bytes 恢复，当前为 honest reconstruction。
3. 报告明确说明没有重跑 screen、没有新增 outcome exposure、verdict 没有改变。
4. 修改完成后按第 6 节规定的顺序重建 sidecar 和 artifact manifest。

## 5. 禁止事项

- 不得重跑 `--open-return-labels --screen`；
- 不得重新解释、筛选或挑选原始 192 条训练/OOS 结果；
- 不得修改 `train_factor_statistics.csv`、`oos_factor_statistics.csv`、`factor_panel.csv.gz`、
  `research_dataset.csv.gz` 或市场数据库；
- 不得把历史状态改成 `empty_price_factor_model`、`rejected`、`candidate` 或 approved；
- 不得把 2026-07-13 以前的数据称为 untouched holdout；
- 不得减少 registry 中 192 训练 + 192 OOS 暴露；
- 不得补造未执行的 canary/负对照结果；
- 不得伪造原始 prereg bytes、时间戳或 SHA；
- 不得执行 `git reset --hard`、`git checkout --`、`git clean` 或清理用户未提交工作；
- 不做与三个剩余问题无关的重构。

## 6. 最终生成顺序

Hash 文件存在依赖顺序。修改时必须从内向外生成：

1. 完成生产代码和测试修改；
2. 跑全量 pytest 和 Ruff，记录实际结果；
3. 计算源码、测试、runner、config 的最终 bytes/SHA，写入 post-run adjudication；
4. 更新 reconstructed prereg 及其 sidecar；
5. 更新 post-run adjudication 及其 sidecar；
6. 更新整改报告及其 sidecar；
7. 最后重生成 `output_artifact_manifest.json`；
8. 最后生成 `output_artifact_manifest.json.sha256`；
9. 从磁盘重新复算全部条目，禁止只相信生成脚本退出码。

不要把 output manifest 自身或它的 sidecar列进 `artifacts`，否则形成自引用。除此之外，研究产物
目录中的每个普通文件都必须被列入。若文件集合未增加，预期仍是目录 25 项、manifest 列 23 项；
如果整改 Agent 在产物目录新增报告，则 count 必须相应增加。

## 7. 必跑验收命令

```bash
cd /Users/open/fx-trading-system

uv run pytest -q

uv run ruff check \
  src/fx_system \
  tests \
  scripts/run_two_pair_long_horizon_research.py

uv run pytest -q \
  tests/test_long_horizon.py \
  tests/test_research_registry.py \
  tests/test_two_pair_long_horizon_runner.py

cd outputs/price_only_round1_20260717
sha256sum -c preregistration_manifest.json.sha256
sha256sum -c post_run_adjudication_manifest.json.sha256
sha256sum -c ROUND1_DELIVERY_REPORT_ZH.md.sha256
sha256sum -c ROUND1_INDEPENDENT_REVIEW_ZH.md.sha256
sha256sum -c ROUND1_REMEDIATION_REPORT_ZH.md.sha256
sha256sum -c output_artifact_manifest.json.sha256
```

还必须逐项复算 artifact manifest。macOS/zsh 中不要把循环变量命名为 `path`，因为 `path` 是
zsh 的特殊变量，会破坏 `PATH`。使用 `rel`：

```bash
jq -r '.artifacts[] | [.path, (.bytes|tostring), .sha256] | @tsv' \
  output_artifact_manifest.json |
while IFS=$'\t' read -r rel bytes hash; do
  actual_bytes=$(/usr/bin/stat -f %z "$rel")
  actual_hash=$(/usr/bin/shasum -a 256 "$rel" | /usr/bin/awk '{print $1}')
  test "$bytes" = "$actual_bytes" || echo "BYTE_FAIL $rel"
  test "$hash" = "$actual_hash" || echo "HASH_FAIL $rel"
done
```

最后比较文件集合：

```bash
find . -maxdepth 1 -type f -print | sed 's#^./##' | sort > /tmp/round1_all.txt
jq -r '.artifacts[].path, .self_and_sidecar_excluded_from_listing[]' \
  output_artifact_manifest.json | sort > /tmp/round1_manifest.txt
comm -3 /tmp/round1_all.txt /tmp/round1_manifest.txt
rm /tmp/round1_all.txt /tmp/round1_manifest.txt
```

`comm -3` 必须无输出。

## 8. 最终验收标准

只有同时满足以下条件，才可以声明工程整改完成：

1. prereg 明确标为事后重构，不再声称是原始 exact-byte frozen 文件；
2. 不可恢复的原始 prereg SHA 明确为 `null/unknown`，没有伪造；
3. original declared runner、实际 screen runner、各整改阶段代码 hash 被分层记录；
4. post-run adjudication 的最终实现 hashes 与当前磁盘逐项一致；
5. spill 测试直接检查标签终点，并且 mutation sanity check 证明删除过滤会失败；
6. label-end 失败路径经过 build-level 测试；
7. 全量 pytest 和 Ruff 通过；
8. registry 仍为 invalidated，暴露仍为 192/192；
9. summary 仍明确 `approved_strategy=false`；
10. artifact manifest 文件集合、bytes、SHA 和所有 sidecar 全部闭合；
11. 没有重跑历史 screen，没有新增因子 outcome exposure；
12. 整改报告不存在未标阶段的 19/23、485/最终测试数冲突。

## 9. 接手后建议的执行顺序

```text
WP1 诚实标记 reconstructed prereg
  -> WP3 修复 spill 测试
  -> WP4 增强 build-level 时间失败测试
  -> 全量 pytest/Ruff
  -> WP2 冻结最终实现 hash
  -> WP5 整理报告
  -> 按依赖顺序重建 sidecar/manifest
  -> 独立复算验收
```

完成后暂停，不启动新的因子筛选。把修改文件清单、测试输出、最终机器状态和任何仍不可恢复的
证据明确报告给用户，由独立 Agent 做最终验收。
