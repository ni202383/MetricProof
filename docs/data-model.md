# MetricProof 数据模型

## 1. 设计原则

- 领域模型表达语义，不携带 Typer、Rich、Jinja2 或具体 YAML/JSON 实现。
- 持久化模型使用 Pydantic 严格验证，领域模型可使用不可变 dataclass 或等价明确类型。
- 所有项目文件位置保存为项目相对、POSIX 风格路径；绝对路径只存在于文件系统适配器内部。
- 所有可参与计算的十进制值以 `Decimal` 表示，序列化为字符串以避免浮点漂移。
- 身份、位置和显示文本分开：文件插行可以改变位置，但不应必然改变身份。
- 所有集合输出都定义稳定排序。

## 2. 基础值对象

### 2.1 `SourceLocation`

| 字段 | 类型 | 说明 |
|---|---|---|
| `path` | `ProjectPath` | 项目相对路径 |
| `line` | `int >= 1` | 起始行 |
| `column` | `int >= 1` | 起始列 |
| `end_line` | `int >= line` | 结束行 |
| `end_column` | `int >= 1` | 结束列 |
| `char_start` | `int >= 0` | 文件内字符起点 |
| `char_end` | `int >= char_start` | 文件内字符终点；空单元格允许零宽范围 |

`SourceLocation` 是当前定位，不作为持久化主身份。JSON/YAML selector 位置通常只填写 `path`；CSV 位置填写 `path`、`line`、`column`。阶段 4A 的 LaTeX 候选填写完整行列和字符范围。

### 2.2 `NumericValue`

| 字段 | 类型 | 说明 |
|---|---|---|
| `raw_text` | `str` | 论文或结果文件中的原始表示 |
| `parsed` | `Decimal` | 解析后的字面值 |
| `canonical` | `Decimal` | 进入比较语义后的规范值 |
| `unit` | `NumericUnit` | `scalar`、`ratio`、`percent_points` 等 |
| `kind` | `NumericKind` | `integer`、`decimal`、`scientific`、`percent`、`mean_std` |
| `decimal_places` | `int | None` | 显示小数位数 |
| `scale` | `Decimal` | `canonical = parsed × scale` |
| `sign` | `str` | 原文显式符号：`"+"`、`"-"` 或空字符串 |

例：

| 原文 | parsed | scale | canonical | unit |
|---|---:|---:|---:|---|
| `0.872` | 0.872 | 1 | 0.872 | scalar |
| `87.2\%` | 87.2 | 0.01 | 0.872 | ratio |
| `3.1 points` | 3.1 | 1 | 3.1 | percent_points |

普通 `0.872` 是否代表比例由链接和指标语义决定，解析器不得仅凭数值范围猜测。

### 2.3 `NumericTolerance`

| 字段 | 类型 | 说明 |
|---|---|---|
| `absolute` | `Decimal >= 0` | 绝对容差 |
| `relative` | `Decimal >= 0` | 相对容差 |

有效容差：

```text
max(absolute, relative × max(abs(expected), abs(observed)))
```

显示精度区间独立计算，再由有效容差扩展。

### 2.4 枚举

- `Severity`: `info`、`warning`、`error`
- 当前 `RuleCode`: `STALE_VALUE`、`WRONG_DELTA`、`MISSING_PROVENANCE`
- `CheckDiagnosticKind`: `rule`、`input`、`link`、`limitation`、`internal`
- `ClaimKind`: `direct_result`、`derived_result`、`summary_statistic`、`experiment_quantity`、`unknown`
- `ClaimDisposition`: `likely_experiment_claim`、`possible_experiment_claim`、`ambiguous`、`non_experiment`
- Registry status: `active`、`ignored`、`broken`、`ambiguous`、`missing`
- Link session 另有只读 `unlinked` 状态
- `DerivedOperation`: `subtraction`、`relative_change`、`mean`、`standard_deviation`
- `StandardDeviationMode`: `sample`、`population`

## 3. 论文模型

### 3.1 阶段 4A/4B1 扫描模型

`RawNumericCandidate` 是源码词法与基础语法事实，不是 `PaperClaim`。它包含：

- `kind`：单值或基础 `mean ± std`；
- `raw_text`、`value` 与可选 `uncertainty`；
- 完整 `SourceLocation`；
- `LatexSyntacticContext`：正文、数学、命令参数、表格环境、caption 或 unknown；
- 当前环境栈、最近命令、有限前后文；
- 可达的配置入口集合与每个入口的规范 include 链。

`LatexSourceGraph` 包含排序后的入口、文档和 include 边。每个
`LatexSourceDocument` 保存项目相对路径与字节数；`LatexIncludeEdge` 保存来源、
目标、include 命令和源码位置。

`PaperScanResult` 包含文件图、稳定排序的原始候选、基础表格、输入/limitation 诊断、
资源统计与 `complete` 标记。`PaperScanStatistics` 同时保存 table 总数以及
parsed/degraded/unsupported 的精确分区。

### 3.2a 阶段 4B2a Claim 候选分类

`ClaimCandidateClassification` 直接引用一个现有 `RawNumericCandidate`，不复制数值，也不建立
持久身份。它保存 `ClaimDisposition`、`ClaimKind`、0–100 整数分数、`ClaimConfidence`、
是否建议进入未来默认复核队列，以及排序后的 `ClaimEvidence`。

`ClaimEvidence` 保存 reason code、positive/negative/neutral 方向、整数分数影响、简短解释、
来源范围和必要的结构上下文。`ClaimClassificationResult` 保存稳定排序的全部分类、精确
disposition 分区统计和非阻断诊断。

当前 `ClaimKind` 是分类提示：`direct_result`、`derived_result`、`summary_statistic`、
`experiment_quantity`、`unknown`；它不同于后续持久 `PaperClaim` 的来源位置类型。

分类阈值和权重集中在领域模块中；表格索引一次构建，mean ± std 保持单个复合候选。
schema 3 通过当前扫描的零基 `candidate_index` 关联分类与 raw candidate。该索引不是 Claim ID。
分类步骤本身仍不产生持久身份或链接；阶段 5 的独立身份、Registry、link 和 check 服务消费该结果。表头/方向语义仍未实现。
详细规则见 [claim-classification.md](claim-classification.md)。

### 3.2 阶段 5 Claim 身份模型

StableClaimId 是 clm_ 加 20 位小写十六进制摘要。它不含论文明文或绝对路径，
不使用绝对行号、随机 UUID、Python hash() 或扫描 candidate index。

ClaimContext 保存：

- 最长 240 字符的复核摘要；
- 结构锚点；
- 最长 120 字符、数字替换为占位符的前后文锚点；
- LaTeX 语法上下文；
- 同一身份组成下的 occurrence ordinal；
- 可选表格 label/caption 锚点与逻辑行列。

ClaimFingerprint 保存：

| 字段 | 类型 | 说明 |
|---|---|---|
| version | str | 当前固定为 1 |
| digest | str | 身份组成的完整 SHA-256 |
| path | ProjectPath | 项目相对 POSIX 文件 |
| structural_anchor | str | 正文语法环境或表格结构位置 |
| context_digest | str | 非数字有限上下文摘要 |
| semantic_digest | str | Claim kind、规范数值和单位摘要 |
| components | tuple[(str, str), ...] | 有序、可解释的身份组成 |

稳定 ID 使用 digest 的前 20 位；semantic_digest 不进入主身份摘要，所以数值演化不会
仅因数字本身变化而丢失身份。组件包含 fingerprint_version、相对路径、Claim kind、
结构锚点、有限前后文、语法上下文和 occurrence ordinal。

IdentifiedClaim 组合 StableClaimId、当前 ClaimFingerprint、当前 SourceLocation、
原始显示文本、NumericValue、Claim kind、disposition、ClaimContext、原分类结果和
当前扫描 candidate index。candidate index 只作为当前扫描引用，不参与身份摘要。

ClaimIdentityResult 按当前源码位置稳定排序，并显式保存任何截断摘要碰撞。
碰撞不得静默覆盖或进入自动链接。

### 3.3 迁移模型

ClaimIdentitySnapshot 是 claims registry 后续持久化所需的旧身份事实：稳定 ID、
旧指纹、旧位置、上次显示文本、kind、disposition 和 ClaimContext。

ClaimMigrationResult 至少保存：

- previous_claim_id；
- EXACT / MIGRATED / AMBIGUOUS / MISSING / COLLISION；
- 匹配方法；
- 0–100 分数；
- 正面证据与冲突原因；
- 旧位置、新位置和当前生成 ID；
- 成功时已恢复旧持久 ID 的 resolved Claim。

迁移先执行稳定 ID 完全匹配，再按同路径、版本、结构锚点、context digest、
有限 token 重合、表格锚点和位置距离进行确定性评分。候选必须达到 70 分，
且领先次名至少 15 分。两个旧 Claim 选择同一个新 Claim 时全部返回 COLLISION；
近似同分返回 AMBIGUOUS；迁移失败不删除旧快照。
### 3.4 阶段 4B1 基础表格模型

基础表格模型只表达可从源码确定的结构事实：

- `LatexTableKind`：`table`、`table*` 容器归属，以及 `tabular`、`tabular*`、`longtable`、`tabularx`、`array`、`matrix`、`aligned` 环境类型；
- `LatexTableReliability`：`parsed`、`degraded`、`unsupported`；
- `LatexFormattingKind`：`bold`、`underline`；
- `LatexTableStructureKind`：hline、cline 与 booktabs 结构标记。

`LatexTable` 保存：

- tabular 环境的精确 `SourceLocation`；
- 可选 `table` / `table*` 容器类型和范围；
- 可选 `LatexTableText` caption/label，其原文、受控规范文本和范围；
- 可选 `LatexColumnSpec` 原始规格与可靠 `expected_column_count`；
- 排序后的 `LatexTableRow`、尾部结构标记、诊断与可靠性。

`LatexTableRow` 保存连续 `row_index`、源码范围、物理单元格、逻辑列数、
行边界结构标记和可靠性。逻辑列数等于各单元格 span 之和。

`LatexTableCell` 保存：

- 连续物理索引、逻辑起始列和 `logical_column_span`；
- 可选 `multicolumn_format`；
- 原始单元格范围与实际内容范围；
- `raw_latex`、受控 `normalized_text`、`is_empty`；
- 指向既有对象的 `LatexCellNumericReference`，不复制或重建数值候选；
- 精确 `LatexCellFormatting` 命令范围和内容范围；
- 可靠性与稳定 limitation code 集合。

`LatexCellNumericReference.formatting` 逐候选记录格式。例如同一单元格中的
`84.1` 与 `\textbf{87.2}` 分别得到空格式和 `bold`，不能用单元格级布尔值混淆。
`\textbf{\underline{87.2}}` 可同时记录 `bold` 和 `underline`。

`\multicolumn{N}{FORMAT}{CONTENT}` 只在 N 为受限正整数字面量且参数闭合时展开逻辑
span；`multirow` 不展开跨行内容，产生 limitation 并降级。未知列类型、列数不匹配、
未闭合上下文和恢复后的结构同样标记 degraded。`longtable`、`tabularx`、`array`、`matrix`、`aligned`
只保留环境范围、候选和 unsupported 诊断，不伪造普通 tabular 行列。

这些模型不包含 table ID、表头角色、metric/model/dataset、方向、best/second-best、
Claim 分类或 Claim ID。

### 3.5 完整 `PaperScan`（后续阶段）

- LaTeX 文件图与阶段 4B1 基础表格事实。
- 稳定排序的 Claim 与版本化身份。
- 表头/指标等经后续阶段建立的语义。
- 输入诊断和 limitation 诊断。
- 指纹碰撞集合。

## 4. 实验模型

### 4.1 `MetricObservation`

| 字段 | 类型 | 说明 |
|---|---|---|
| `observation_id` | `ObservationId` | 确定性身份 |
| `run_id` | `RunId` | 所属实验 |
| `metric_name` | `str` | 规范指标名 |
| `value` | `Decimal` | 结果文件中的值 |
| `unit` | `NumericUnit | None` | 若配置声明则保存 |
| `source_file` | `ProjectPath` | JSON/YAML/CSV 文件 |
| `source_selector` | `str` | 点路径或 CSV 行列选择器 |
| `location` | `DataLocation` | 文件、行列或结构路径 |
| `dataset` | `str | None` | 可选数据集 |
| `split` | `str | None` | 可选划分 |
| `seed` | `str | int | None` | 可选 seed |
| `commit` | `str | None` | 来源声明的 commit |
| `config_reference` | `ProjectPath | None` | 关联配置 |
| `metadata` | `Mapping[str, ScalarValue]` | 受控元数据 |

`ObservationId` 基于来源文件、selector、run 和 metric 生成，不使用随机 UUID。

### 4.2 `ExperimentRun`

- `run_id`
- `observations`
- `metadata`
- `config_snapshot`
- `result_sources`
- `declared_commit`
- `diagnostics`

同一 run 中相同规范 metric 出现多个 Observation 时，除非配置定义了维度或聚合语义，否则产生重复诊断，不自动覆盖。

### 4.3 `ExperimentConfigSnapshot`

- `run_id`
- `source_file`
- `values: Mapping[DotPath, ConfigValue]`
- 每个值的来源定位
- 不可用或解析失败字段

配置值支持有限 JSON/YAML 数据类型：null、bool、str、Decimal、list、mapping。比较语义见规则文档。

### 4.4 `ExperimentCatalog`

- 稳定排序的 Run。
- Observation 索引。
- 配置快照索引。
- 输入诊断。

## 5. 链接模型

### 5.1 `MetricReference`

- `source_file`：项目相对 POSIX 结果文件路径。
- `run_id`
- `metric_name`
- `source_selector`
- `scale: LinkScale`

`scale` 把 Observation 值转换到 Claim 比较值，只允许 `identity`、`fraction_to_percent`、`percent_to_fraction`。对应确定性 Decimal 乘数 1、100、0.01；它不是表达式。

### 5.2 `DirectLink`

- `claim_id`
- `metric`
- `confirmed_fingerprint`：确认时的完整 64 位 SHA-256 Claim 指纹。
- 可选 `tolerance_override: NumericTolerance`
- `note`

状态由外层 `ClaimRegistryEntry` 保存，不在 Link 中复制。

### 5.3 `DerivedOperand`

- `name`：小写 snake_case，单个 Link 内唯一并稳定排序。
- `metric`

### 5.4 `DerivedLink`

- `claim_id`
- `operation`
- `operands`
- `output_unit: scalar | ratio | percent_points`
- `output_scale: LinkScale`
- `confirmed_fingerprint`
- `rounding: RoundingPolicy`
- 可选 `standard_deviation_mode`
- 可选 `tolerance_override`
- `note`

操作数约束：

- `subtraction`：恰好两个具名操作数，稳定顺序为 `baseline`、`candidate`。
- `relative_change`：同样要求 `baseline`、`candidate`；baseline 为零的不可计算诊断由规则阶段产生。
- `mean`：至少一个操作数。
- `standard_deviation`：至少两个操作数，且必须声明 `sample` 或 `population`。

首版只允许单层枚举操作。操作数只能是 `MetricReference`，不能嵌套 DerivedLink，也不接受表达式、函数名或代码。RoundingPolicy 只支持可选非负小数位和 `half_up`。

### 5.5 `ClaimRegistryEntry`

- `identity: ClaimIdentitySnapshot`
- `status: active | ignored | broken | ambiguous | missing`
- 恰好一个 `link` 或 `ignore`
- 可选 `note`
- 可选 `migration: RegistryMigrationRecord`

`IgnoreRecord` 保存受控 `reason` 与可选 note。忽略必须显式持久化，不能通过删除历史链接伪装。`broken` 必须保留原 Link；`active` 必须有 Link；`ignored` 必须有 IgnoreRecord。

`ClaimRegistry` 固定使用 schema version `1`，entries 按 Claim ID 排序且 ID 唯一。
### 5.6 `CandidateMatch`

- `claim_id`
- `suggestion_type: direct | derived`
- `score: int [0,100]`
- `features: tuple[MatchFeature, ...]`
- 排序、去重的 `uncertainties`
- `suggested_scale`
- Direct 专用 `metric`
- Derived 专用 `operation`、`operands`、`output_unit` 和可选 std mode

每个 `MatchFeature` 保存稳定 code、-100–100 contribution 和人工可读 summary；CandidateMatch 的 score 必须等于全部 contribution 的 0–100 有界和，不能保存不可解释的黑盒分数。

候选排序依次使用总分降序、Direct 优先、来源/operation 稳定身份和 scale。领先不足 8 分时 `ClaimMatchResult.ambiguous=true`。候选匹配永远不是持久化 Link，直到用户逐项确认；数值相同只能贡献一个 feature。

`LinkSession` 把同一次 scan、ExperimentCatalog、ClaimRegistry 和迁移结果组合为 active、ignored、broken、ambiguous、missing、unlinked review items。它只构建会话，不读写具体文件。
## 6. 比较模型

### 6.1 `ComparisonSpec`

| 字段 | 类型 | 说明 |
|---|---|---|
| `comparison_id` | `str` | 稳定用户定义身份 |
| `baseline_run` | `RunId` | 基线实验 |
| `candidate_run` | `RunId` | 候选实验 |
| `controlled_keys` | `tuple[DotPath, ...]` | 必须一致的字段 |
| `allowed_differences` | `Mapping[DotPath, str]` | 合法差异及理由 |
| `numeric_tolerance` | `NumericTolerance | None` | 配置数值比较容差 |
| `severity` | `Severity` | 规则严重程度 |

列表默认按顺序比较；首版不隐式按集合比较。需要允许的列表差异应显式加入 `allowed_differences`。

## 7. 证据和诊断

### 7.1 `Evidence`

- `evidence_id`
- `kind`
- `summary`
- 可选 `location`
- 可选结构化 `details`
- 相关领域对象身份

Evidence 必须描述已观察事实，不包含规则结论本身。

### 7.2 `CheckDiagnostic`

| 字段 | 类型 | 说明 |
|---|---|---|
| `diagnostic_id` | `str` | 基于 kind、code、Claim、位置、值和 evidence ID 的稳定摘要 |
| `kind` | `CheckDiagnosticKind` | rule/input/link/limitation/internal |
| `code` | `str` | 规则或输入/链接代码 |
| `severity` | `Severity` | 严重程度 |
| `message` | `str` | 审慎、可复核的描述 |
| `location` | `SourceLocation` | 必需的项目相对主位置 |
| `claim_id` | `str | None` | 相关稳定 Claim ID |
| `observed` | `ScalarValue` | 当前观察 |
| `expected` | `ScalarValue` | 规则期望 |
| `evidence` | `tuple[Evidence, ...]` | 支持事实 |
| `confidence` | `Decimal [0,1]` | 确定性证据强度，不是错误概率 |
| `remediation` | `str` | 必需的人工处理建议 |
| `related_sources` | `tuple[SourceLocation, ...]` | 去重排序后的相关位置 |
| `uncertainties` | `tuple[str, ...]` | 去重排序后的限制/不确定性 |

### 7.3 `CheckSummary`

保存 checked Claim 数，以及按稳定 key 排序的 registry、migration、diagnostic code 和
severity 计数。所有计数非负且 key 唯一。

### 7.4 `CheckResult`

当前 schema version `1` 只包含：

- `schema_version`
- `tool_version`
- 项目显示名 `project`
- `CheckSummary`
- 按 severity、code、位置、Claim ID 和诊断 ID 稳定排序的 `diagnostics`

终端和 JSON 只渲染这一模型。未来 HTML 也必须消费同一事实来源，但 HTML、独立
EvidenceGraph 和 Git evidence 当前均未实现。

## 8. `config.yml` 阶段 3 与 5D 已实现结构

阶段 3 实现结果来源 schema；阶段 5 增加严格 Registry 路径、metric aliases、数值容差和 check policy。JSON/YAML 指标和元数据必须显式声明 selector：

```yaml
schema_version: "1"
claim_registry_path: .metricproof/claims.yml
result_paths:
  - path: runs/baseline.json
    format: json
    run_id: baseline
    structured:
      metrics:
        accuracy: metrics.accuracy
      metadata:
        dataset: context.dataset
        split: context.split
        seed: context.seed

  - path: runs/all.yml
    format: yaml
    structured:
      records_selector: runs
      run_id_selector: id
      metrics:
        accuracy: metrics.accuracy

  - path: runs/seeds.csv
    format: csv
    csv:
      run_id_column: run_id
      metadata_columns: [dataset, split, seed]
      metric_columns: [accuracy, f1]

experiment_config_paths:
  - configs/**/*.yml
exclude_paths:
  - build/**
```

结构化单 run 来源必须在固定 `run_id` 与相对根 mapping 的 `run_id_selector` 中二选一。多 run 数组必须同时声明 `records_selector` 和相对记录的 `run_id_selector`，且不得固定一个 run ID。`metrics` 映射规范指标名到点路径；`metadata` 映射受控元数据名到点路径。点路径中的整数段是显式数组索引，数组不会自动展开为指标。

每个结果来源可声明一个精确 `config_reference`。`experiment_config_paths` 的匹配文件在阶段 3 中只验证、稳定记录并作为后续配置快照输入，不比较配置，也不运行 `UNFAIR_COMPARISON`。

未知顶级和嵌套字段均拒绝。所有路径以项目根目录为基准，拒绝绝对路径、`..`、缺失文件、重复别名和符号链接逃逸。 `claim_registry_path` 例外地允许文件尚不存在，以便首次链接时创建 registry；但其父目录必须在保存前存在，且路径仍须通过项目边界检查。

### 8.1 后续完整 MVP 配置参考

以下较完整示例中的论文、指标方向、容差、比较策略和 policy 字段可被严格 schema 验证，但阶段 3 不执行相应业务逻辑；读取资源边界使用代码中集中定义的内置常量：

```yaml
schema_version: "1"
claim_registry_path: .metricproof/claims.yml

paper_paths:
  - paper/main.tex

result_paths:
  - path: runs/**/*.json
    format: json
  - path: runs/seeds.csv
    format: csv
    csv:
      run_id_column: run_id
      metadata_columns: [dataset, split, seed]
      metric_columns: [accuracy, f1]

experiment_config_paths:
  - configs/**/*.yml

exclude_paths:
  - build/**

metric_aliases:
  accuracy: [acc, top-1 accuracy]

metric_directions:
  accuracy: higher
  latency_ms: lower

numeric_tolerances:
  default:
    absolute: "0"
    relative: "0.000001"
  metrics:
    accuracy:
      absolute: "0.00005"
      relative: "0"

controlled_config_keys:
  - dataset.name
  - dataset.split
  - training.seed

ignored_claim_patterns:
  - "\\b20[0-9]{2}\\b"

comparisons:
  - comparison_id: baseline-vs-proposed
    baseline_run: baseline
    candidate_run: proposed
    controlled_keys:
      - dataset.name
      - dataset.split
      - evaluation.script
    allowed_differences:
      model.name: "The compared method is expected to differ."
    severity: warning

policy:
  missing_provenance_severity: warning
  fail_on: error

limits:
  max_file_bytes: 5000000
  max_include_depth: 32
  max_files: 1000
```

未知顶级字段拒绝。未来阶段启用这些字段时不得改变已持久化语义。

## 9. `claims.yml` 首版结构

以下示例展示实际层级；摘要值为文档占位，真实文件必须满足长度和格式校验：

```yaml
schema_version: "1"
claims:
  - identity:
      claim_id: clm_0123456789abcdef0123
      fingerprint:
        version: "1"
        digest: 0000000000000000000000000000000000000000000000000000000000000000
        path: paper/main.tex
        structural_anchor: "table:main-results|row:1|column:2"
        context_digest: 00000000000000000000
        semantic_digest: 11111111111111111111
        components:
          - [kind, direct_result]
          - [path, paper/main.tex]
      location:
        path: paper/main.tex
        selector: ""
        line: 18
        column: 22
        end_line: 18
        end_column: 27
        char_start: 410
        char_end: 415
      raw_text: "87.2\\%"
      kind: direct_result
      disposition: likely_experiment_claim
      context:
        summary: "Proposed accuracy <number>"
        structural_anchor: "table:main-results|row:1|column:2"
        prefix_anchor: "proposed accuracy"
        suffix_anchor: ""
        syntactic_context: table
        occurrence_ordinal: 0
        table_anchor: "label:tab:main-results"
        table_row: 1
        table_column: 2
    status: active
    link:
      type: direct
      metric:
        source_file: runs/proposed.json
        run_id: proposed
        metric_name: accuracy
        source_selector: metrics.accuracy
        scale: fraction_to_percent
      confirmed_fingerprint: 0000000000000000000000000000000000000000000000000000000000000000
      tolerance_override:
        absolute: "0.05"
        relative: "0"
      note: "Confirmed from the final evaluation run."
```

每项把完整 `ClaimIdentitySnapshot` 放在 `identity` 下。`status`、`link` / `ignore`、可选 entry note 和 migration 位于同级。DirectLink 与 DerivedLink 都保存 `confirmed_fingerprint`，用于发现确认后 Claim 语义变化。

DerivedLink 在 `link.type: derived` 下保存枚举 `operation`、结构化 `operands`、`output_unit`、`output_scale`、`rounding`，以及标准差专用的 `standard_deviation_mode`。它不接受代码字符串。IgnoreRecord 则保存受控 `reason` 和 note。

读取时未知顶级或嵌套字段、重复 Claim ID、无效状态组合和不兼容 schema 均失败。写出时字段顺序固定、Claim 按 ID 排序、Decimal 以字符串保存；采用同目录临时文件、flush、fsync 和原子替换。
## 10. 持久化与迁移

- 所有文件必须先完整验证，再替换当前版本。
- schema 主版本不兼容时退出，不自动猜测升级。
- Claim 指纹算法升级时保留旧版本读取器或提供显式离线迁移命令；首版不预建通用迁移框架。
- Claim 移动后，仅在新扫描中存在唯一高置信度上下文匹配时建议迁移。
- 碰撞、多个近似匹配或来源消失时保持原记录并标记状态，不自动改写。
