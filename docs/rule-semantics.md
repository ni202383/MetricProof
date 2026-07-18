# MetricProof 规则语义

当前本地 MVP 仅实现 STALE_VALUE、WRONG_DELTA 和 MISSING_PROVENANCE。WRONG_BEST_MARK 与 UNFAIR_COMPARISON 仅作为后续设计保留，不得由当前 check 选择或输出。

## 1. 通用规则协议

规则接收已经准备好的 Claim、Link、Observation 与策略领域对象，只读取领域对象。规则不得读取文件、解析 YAML、调用 Git、访问 CLI 或渲染输出。

每条规则返回零个或多个 `CheckDiagnostic`。规则执行和诊断排序必须确定。

规则诊断必须包含：

- 规则代码。
- 严重程度。
- 主来源位置。
- 审慎的消息。
- observed 与 expected。
- 支持证据和相关来源。
- 证据强度 confidence。
- 可执行的人工 remediation。

confidence 是确定性证据强度，不是缺陷概率。消息必须使用“does not match”“may indicate”“comparison settings differ”等措辞，禁止声称论文错误、结论虚假或存在学术不端。

## 2. 通用数值比较

### 2.1 规范化

比较前：

1. 从链接读取 Observation。
2. 应用 Link 的十进制 `scale`。
3. 转换到 Claim 的规范单位。
4. 验证单位组合合法。

单位或缩放不合法时，产生输入/链接诊断，不运行会误导的规则判断。

### 2.2 显示精度区间

若 Claim 显示 `d` 位小数，则以其规范值为中心构造半个最小显示单位的区间。百分数先转换到比例，再计算区间。

例如 `87.2%` 表示的基础接受区间为：

```text
[0.8715, 0.8725)
```

边界实现应与文档规定的十进制舍入语义一致，并为精确边界写测试。

### 2.3 容差扩展

有效容差：

```text
t = max(abs_tolerance, rel_tolerance × max(abs(expected), abs(observed)))
```

把显示区间向两侧扩展 `t`。只有当前实验值落在扩展区间之外才视为不一致。

若 Claim 无可识别显示精度，则围绕 Claim 规范值使用 `±t`。

## 3. `STALE_VALUE`

### 3.1 意图

检查一个 active DirectLink 的论文显示值是否仍与当前链接 Observation 一致。

### 3.2 输入

- `PaperClaim`
- active `DirectLink`
- 当前 `MetricObservation`
- 全局/按指标/按 Claim 容差

### 3.3 适用条件

- Link 唯一解析到一个 Observation。
- Claim 和 Observation 可转换到同一单位。
- Claim 具有单一可比较数值。

### 3.4 判断

把 Observation 转换到 Claim 规范单位，并应用通用数值比较。超出接受区间时产生一个 `STALE_VALUE`。

### 3.5 输出证据

- 论文原始值和位置。
- 论文规范值与显示精度区间。
- 当前 Observation 值、来源文件、selector 和 run。
- 应用的 scale 与容差。
- 可用时附带配置和 Git 证据。

### 3.6 不触发

- 值落在显示精度与容差允许范围内。
- Link 为 ignored、broken 或 ambiguous。
- 来源缺失、重复或无法解析。
- 单位关系不合法。

后三类情况产生输入/链接诊断，而不是伪造 `STALE_VALUE`。

### 3.7 局限

- 只能确认“链接来源当前值与论文显示值不一致”，不能判断哪个值科学上正确。
- 用户链接到错误 run 时，规则仍会忠实检查该链接。

## 4. `WRONG_DELTA`

### 4.1 意图

重新计算用户确认的受控派生值，检查论文显示结果是否一致。

### 4.2 输入

- `PaperClaim`
- active `DerivedLink`
- 所有可解析操作数 Observation
- operation、输出单位、scale、容差和可选标准差模式

### 4.3 运算

#### subtraction

```text
candidate - baseline
```

输出单位由链接声明，不自动变成百分数。

#### relative_change

```text
(candidate - baseline) / abs(baseline)
```

若输出显示为百分数，再按百分数语义展示。baseline 为零时不可计算，产生派生链接输入诊断。

#### mean

```text
sum(values) / count(values)
```

至少一个操作数。

#### standard_deviation

使用 Decimal 兼容的确定性算法。必须显式声明：

- `population`：分母为 `N`
- `sample`：分母为 `N - 1`

sample 模式至少两个操作数。

### 4.4 百分点

当 baseline 和 candidate 都表示比例，且输出单位声明为 `percent_points`：

```text
(candidate - baseline) × 100
```

示例：`0.872 - 0.841 = 0.031`，即 `3.1` percentage points。

相对提升则为：

```text
(0.872 - 0.841) / 0.841 × 100% ≈ 3.686%
```

两者不可互换。

### 4.5 判断与输出

计算派生规范值后，使用通用显示精度和容差比较。超出范围时产生 `WRONG_DELTA`，证据包括：

- 每个操作数的 run、metric、值和来源。
- operation 与公式。
- 重新计算值。
- 论文值、显示精度、单位和容差。

### 4.6 不触发

- 派生值在允许范围内。
- 操作数缺失、重复、broken 或单位不兼容。
- baseline 为零导致相对变化未定义。
- 标准差模式缺失或样本数量不足。

这些情况产生输入/链接诊断，不输出错误派生值。

### 4.7 局限

- 首版只支持四个枚举运算，不支持组合表达式或任意公式。
- 不判断作者选择该统计量是否合理。

## 5. `MISSING_PROVENANCE`

### 5.1 意图

找出被系统识别为实验数值、处于分析范围内、但没有 active Link 或显式 IgnoreRecord 的 Claim。

### 5.2 输入

- `PaperClaim`
- Claim registry
- 配置的分析范围、忽略模式和严重程度

### 5.3 适用条件

必须同时满足：

- `classification == experimental`
- Claim 位于配置分析范围
- 没有 active DirectLink 或 DerivedLink
- 没有 IgnoreRecord
- 未命中项目级忽略规则

默认不对 `POSSIBLE_EXPERIMENT_CLAIM` 触发；只有 `policy.include_possible_missing_provenance: true` 时才纳入。`AMBIGUOUS` 与 `NON_EXPERIMENT` 不触发。

### 5.4 判断与输出

每个适用 Claim 产生一个 `MISSING_PROVENANCE`，confidence 使用 Claim 分类证据强度。证据包括：

- Claim 原文、位置与上下文。
- 被判定为实验数值的特征。
- 当前 registry 中没有 active link/ignore 的事实。

remediation 应建议运行 `metricproof link` 或显式标记非实验数字。

### 5.5 不触发

- 年份、引用编号、章节编号等 `non_experimental` 内容。
- `uncertain` 内容的默认策略。
- 已链接或已忽略 Claim。
- 被排除文件或忽略模式命中的 Claim。

### 5.6 局限

- Claim 分类是启发式的；规则不保证找出所有实验结论。
- 为降低误报，首版宁可把不确定数字留给 link 工作流，也不默认全部报错。

## 6. 后续设计：`WRONG_BEST_MARK`（未实现）

### 6.1 意图

检查可靠解析的基础 LaTeX 表格中，粗体最优值和下划线次优值是否符合用户配置的指标方向。

### 6.2 输入

- `PaperTable`
- 可可靠比较的数值列
- 列对应规范指标
- `MetricDirection`
- 按指标的并列容差

### 6.3 适用条件

- 表格行列结构可靠。
- 列能唯一映射到一个指标。
- 配置明确声明 `higher` 或 `lower`。
- 至少有一个可比较数值。

缺少方向或表格结构不可靠时只产生 limitation/config diagnostic，不猜测。

### 6.4 最优与次优集合

1. 按方向找到最优值。
2. 与最优值在并列容差内的所有单元格组成 best set。
3. 排除 best set 后，找到下一组不同值作为 second-best set。
4. 若不存在第二组值，则 second-best set 为空。

缺失值、破折号和非数值单元格不参与排序。

### 6.5 判断

可产生以下子情形，但规则代码保持 `WRONG_BEST_MARK`：

- 非 best set 单元格被加粗。
- best set 单元格未加粗。
- 非 second-best set 单元格被下划线。
- second-best set 单元格未下划线。

若项目策略不要求“必须标全所有并列值”，该策略必须显式配置；默认要求所有 best/second-best 单元格按约定标记。

### 6.6 输出证据

- 表格、caption/label 和指标列位置。
- 指标方向和并列容差。
- 参与比较的单元格、数值和标记状态。
- 计算得到的 best/second-best 集合。

### 6.7 局限

- 首版不可靠支持复杂跨行跨列表头、宏生成单元格或隐藏数值变换。
- 规则检查的是源码显示值和格式，不证明表格数字有实验来源；来源由其他规则处理。

## 7. 后续设计：`UNFAIR_COMPARISON`（未实现）

### 7.1 意图

报告 baseline 与 candidate 在用户明确要求保持一致的实验配置字段上存在差异。规则名是风险标签，不表示已确认比较不公平。

### 7.2 输入

- `ComparisonSpec`
- baseline 与 candidate 的 `ExperimentConfigSnapshot`
- 受控字段、允许差异、数值容差和严重程度

### 7.3 适用条件

- 两个 run 都可唯一解析。
- comparison 明确列出 `controlled_keys`。
- 对应配置快照可读取。

工具不得自动推断哪些字段“应该”受控。

### 7.4 比较语义

- 标量：类型和值都必须一致；数值可使用 comparison 容差。
- 映射：通过点路径读取目标字段。
- 列表：默认顺序和元素都必须一致。
- 字段仅一侧缺失：记录 `missing_on_baseline` 或 `missing_on_candidate`。
- 双方都缺失：产生配置不足诊断，不作为字段差异证据。
- `allowed_differences` 中的字段不触发规则，并在证据中保留用户理由。

### 7.5 判断与输出

一个 comparison 可输出一个聚合 `UNFAIR_COMPARISON` 诊断，列出所有未被允许的差异：

- comparison ID。
- baseline/candidate run。
- 受控字段及其来源。
- 双方值或缺失状态。
- 为什么字段被要求一致。
- 用户允许差异的排除记录。

消息必须说明“配置差异可能削弱归因，需要人工复核”，不能断言实验无效。

### 7.6 不触发

- 受控字段一致。
- 差异被 `allowed_differences` 明确允许并给出理由。
- 字段不在 `controlled_keys` 中。

### 7.7 局限

- 规则无法判断未记录配置、环境差异或数据泄漏。
- 相同配置不证明实验公平。
- 受控字段选择质量由用户负责，MetricProof 只执行声明的契约。

## 8. 当前规则组合与去重

- broken Link 先产生链接诊断，相关 `STALE_VALUE` / `WRONG_DELTA` 跳过。
- `MISSING_PROVENANCE` 不对 registry 中已有 broken Link 的 Claim 重复报告；broken 状态已有更具体诊断。
- ignored Claim 不产生 `MISSING_PROVENANCE`。
- 同一 code、Claim、位置、observed/expected 与 evidence ID 集合只产生一个稳定 Diagnostic ID。
- 后续两条规则尚未参与组合或去重。

## 9. 默认严重程度建议

| 规则 | 默认严重程度 |
|---|---|
| `STALE_VALUE` | error |
| `WRONG_DELTA` | error |
| `MISSING_PROVENANCE` | warning |

`WRONG_BEST_MARK` 与 `UNFAIR_COMPARISON` 当前没有运行时严重程度，因为尚未实现。

严重程度可以在受控配置范围内覆盖，但规则代码与事实语义不能被配置改变。

