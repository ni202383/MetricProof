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
| `char_end` | `int > char_start` | 文件内字符终点 |

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
- `RuleCode`: 五条首版规则代码
- `DiagnosticKind`: `rule`、`input`、`limitation`、`internal`
- `MetricDirection`: `higher`、`lower`
- `ClaimKind`: `body_value`、`table_cell`、`derived_value`
- `ClaimClassification`: `experimental`、`non_experimental`、`uncertain`
- `LinkStatus`: `active`、`ignored`、`broken`、`ambiguous`
- `DerivedOperation`: `subtraction`、`relative_change`、`mean`、`standard_deviation`
- `StdDevMode`: `sample`、`population`

## 3. 论文模型

### 3.1 阶段 4A 原始扫描模型

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

`PaperScanResult` 包含文件图、稳定排序的原始候选、输入/limitation 诊断、
资源统计与 `complete` 标记。阶段 4A 不产生 Claim、Claim ID、表格行列模型或链接。

### 3.2 `ClaimFingerprint`（后续阶段）

| 字段 | 类型 | 说明 |
|---|---|---|
| `version` | `str` | 指纹算法版本 |
| `digest` | `str` | 固定长度摘要 |
| `path` | `ProjectPath` | 项目相对文件 |
| `structural_anchor` | `str | None` | section、table label、行列头等规范锚点 |
| `context_digest` | `str` | 有限前后文摘要 |
| `semantic_digest` | `str` | Claim 类型与规范数值摘要 |

`claim_id` 由版本化指纹生成，例如 `clm_<digest>`。行号不进入主摘要。

### 3.3 `PaperClaim`（后续阶段）

| 字段 | 类型 | 说明 |
|---|---|---|
| `claim_id` | `ClaimId` | 当前稳定身份 |
| `fingerprint` | `ClaimFingerprint` | 用于迁移和碰撞判断 |
| `kind` | `ClaimKind` | 正文、表格或派生值 |
| `value` | `NumericValue` | 数值语义 |
| `location` | `SourceLocation` | 当前源码位置 |
| `context` | `ClaimContext` | 周围文本、section、caption、表头等 |
| `classification` | `ClaimClassification` | 候选分类 |
| `classification_confidence` | `Decimal [0,1]` | 确定性启发式分值 |
| `classification_evidence` | `tuple[Evidence, ...]` | 为什么被分类 |

置信度是规则证据强弱分值，不宣称统计校准概率。

### 3.4 表格模型（后续阶段）

`PaperTable`：

- `table_id`
- `location`
- `caption`
- `label`
- `headers`
- `rows`
- `limitations`

`TableCell`：

- `row_index` / `column_index`
- `raw_text`
- `location`
- `numeric_value`
- `is_bold`
- `is_underlined`
- `row_header`
- `column_header`
- `parse_reliable`

复杂跨度导致行列语义不可靠时，`parse_reliable=false`，规则不得继续比较该范围。

### 3.5 完整 `PaperScan`（后续阶段）

- LaTeX 文件图。
- 稳定排序的 Claim。
- 表格。
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

- `source_file`
- `run_id`
- `metric_name`
- `source_selector`
- `scale: Decimal`

`scale` 把 Observation 值转换到 Claim 的规范比较单位。它是十进制乘数，不是表达式。

### 5.2 `DirectLink`

- `claim_id`
- `claim_fingerprint`
- `metric_reference`
- 可选 `tolerance_override`
- `note`
- `status`

### 5.3 `DerivedOperand`

- `name`
- `metric_reference`

### 5.4 `DerivedLink`

- `claim_id`
- `claim_fingerprint`
- `operation`
- `operands`
- `output_unit`
- `output_scale`
- 可选 `stddev_mode`
- 可选 `tolerance_override`
- `note`
- `status`

操作数约束：

- `subtraction`：恰好两个具名操作数 `candidate`、`baseline`。
- `relative_change`：恰好两个操作数，baseline 不得为零。
- `mean`：至少一个操作数。
- `standard_deviation`：至少两个操作数，且必须声明 sample/population。

### 5.5 `IgnoreRecord`

- `claim_id`
- `claim_fingerprint`
- `reason`
- 可选 `note`

忽略必须显式持久化，不能通过删除历史链接伪装。

### 5.6 `CandidateMatch`

- Claim 引用。
- MetricReference。
- `score: Decimal [0,1]`。
- 各匹配特征及贡献。
- 支持证据。
- 不确定性原因。

候选匹配永远不是持久化 Link，直到用户确认。

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

### 7.2 `Diagnostic`

| 字段 | 类型 | 说明 |
|---|---|---|
| `diagnostic_id` | `str` | 基于规则和证据生成的稳定身份 |
| `kind` | `DiagnosticKind` | rule/input/limitation/internal |
| `code` | `str` | 规则或输入错误代码 |
| `severity` | `Severity` | 严重程度 |
| `message` | `str` | 审慎、可复核的描述 |
| `location` | `SourceLocation | DataLocation | None` | 主位置 |
| `observed` | `StructuredValue | None` | 当前观察 |
| `expected` | `StructuredValue | None` | 规则期望 |
| `evidence` | `tuple[Evidence, ...]` | 证据 |
| `confidence` | `Decimal [0,1]` | 证据强度 |
| `remediation` | `str | None` | 人工处理建议 |
| `related_sources` | `tuple[Location, ...]` | 相关位置 |

### 7.3 `EvidenceGraph`

节点：

- Claim
- Link
- Observation
- ResultSource
- ExperimentConfig
- GitEvidence

边使用固定类型，例如 `linked_to`、`read_from`、`configured_by`、`declared_at_commit`。缺失节点保留 unavailable 状态。

### 7.4 `CheckResult`

- `schema_version`
- `tool_version`
- `project`
- `summary`
- 稳定排序的 `diagnostics`
- `errors`
- `evidence_graph`
- 非敏感执行元数据

所有报告格式都消费该模型。

## 8. `config.yml` 阶段 3 已实现结构

阶段 3 已实现以下严格 schema。JSON/YAML 指标和元数据必须显式声明 selector：

```yaml
schema_version: "1"
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

未知顶级和嵌套字段均拒绝。所有路径以项目根目录为基准，拒绝绝对路径、`..`、缺失文件、重复别名和符号链接逃逸。

### 8.1 后续完整 MVP 配置参考

以下较完整示例中的论文、指标方向、容差、比较策略和 policy 字段可被严格 schema 验证，但阶段 3 不执行相应业务逻辑；读取资源边界使用代码中集中定义的内置常量：

```yaml
schema_version: "1"

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

```yaml
schema_version: "1"

claims:
  - claim_id: clm_example
    fingerprint:
      version: "1"
      digest: example
      path: paper/main.tex
      structural_anchor: "table:main-results|row:Proposed|column:accuracy"
      context_digest: example-context
      semantic_digest: example-semantic
    source_display_value: "87.2\\%"
    status: active
    link:
      type: direct
      metric:
        source_file: runs/proposed.json
        run_id: proposed
        metric_name: accuracy
        source_selector: metrics.accuracy
        scale: "1"
    note: "Confirmed from the final evaluation run."

  - claim_id: clm_year
    fingerprint:
      version: "1"
      digest: year-example
      path: paper/main.tex
      structural_anchor: "section:introduction"
      context_digest: year-context
      semantic_digest: year-semantic
    source_display_value: "2026"
    status: ignored
    ignore:
      reason: non_experimental_number
      note: "Publication year."
```

DerivedLink 在 `link.type: derived` 下保存枚举 operation 和结构化 operands，不接受代码字符串。

## 10. 持久化与迁移

- 所有文件必须先完整验证，再替换当前版本。
- schema 主版本不兼容时退出，不自动猜测升级。
- Claim 指纹算法升级时保留旧版本读取器或提供显式离线迁移命令；首版不预建通用迁移框架。
- Claim 移动后，仅在新扫描中存在唯一高置信度上下文匹配时建议迁移。
- 碰撞、多个近似匹配或来源消失时保持原记录并标记状态，不自动改写。
