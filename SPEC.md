# MetricProof 产品规格

## 1. 产品定义

MetricProof 是一个开源、本地优先的 Python 3.13 命令行工具。

> Unit tests for experimental claims.

它检查机器学习论文源码中的实验数字、派生数字、表格最优/次优标记和用户声明的受控比较条件，是否与本地实验结果、实验配置及 Git 证据保持一致。

MetricProof 产生的是可复核的“一致性诊断”或“启发式风险”，不是对论文正确性、研究质量或学术诚信的裁决。

阶段 5 本地 MVP 当前只覆盖实验数字链接、三条核心规则以及终端/JSON。表格最佳值、受控比较、HTML 与 Git 证据链保留在后续路线图，不属于当前实现。

## 2. 目标用户与使用场景

首版面向在本地 Git 仓库中维护 LaTeX 论文和机器学习实验记录的个人研究者或小型研究团队。

典型场景：

- 重新运行实验后，检查论文中的已链接数字是否过期。
- 检查“提升 3.2 个百分点”等派生数字是否计算正确。
- 找出尚未建立实验来源的候选实验数字。
- 检查基础 LaTeX 表格的加粗最优值和下划线次优值。
- 检查 baseline 与 candidate 是否在用户要求保持一致的配置字段上存在差异。
- 在本地或未来的 CI 中生成终端、JSON 和静态 HTML 证据报告。

## 3. 首版范围

### 3.1 输入

- LaTeX 源文件及相对路径的 `\input{}`、`\include{}`。
- JSON 实验结果。
- YAML 实验结果与实验配置。
- 带表头的二维 CSV 实验结果。
- 本地 Git 仓库的只读信息。
- `.metricproof/config.yml` 项目配置。
- `.metricproof/claims.yml` 经用户确认的 Claim 链接。

### 3.2 输出

- 人类可读的终端摘要与诊断。
- 版本化 JSON 结果。
- 后续路线图：单文件、离线可打开的静态 HTML 报告（当前未实现）。
- 稳定退出码，供本地脚本和未来 CI 使用。

### 3.3 规则路线图

| 规则 | 状态 | 目的 |
|---|---|---|
| `STALE_VALUE` | 阶段 5 已实现 | 检查已链接论文值与当前实验指标是否一致 |
| `WRONG_DELTA` | 阶段 5 已实现 | 重新计算受控派生值并检查论文显示值 |
| `MISSING_PROVENANCE` | 阶段 5 已实现 | 报告未链接且未忽略的实验 Claim |
| `WRONG_BEST_MARK` | 后续，未实现 | 检查基础表格中的最优/次优格式 |
| `UNFAIR_COMPARISON` | 后续，未实现 | 报告用户声明受控字段的配置差异风险 |

规则的严格语义见 [docs/rule-semantics.md](docs/rule-semantics.md)。

## 4. 非目标

首版明确不做：

- 不证明论文结论科学正确。
- 不检测或裁定科研不端。
- 不自动复现实验，不执行训练代码或用户脚本。
- 不解析 PDF、Word、在线 Overleaf 项目或任意远程资源。
- 不接入 W&B、MLflow、DVC 云端或其他实验平台 API。
- 不调用 LLM、嵌入模型或任何外部 AI API。
- 不提供账号、数据库、Web 服务、协作平台或付费功能。
- 不自动修改 LaTeX、实验结果、配置或 Git 历史。
- 不实现完整 TeX 引擎、完整统计学审稿或任意表达式求值。
- 不提前建立插件系统、通用工作流引擎或多语言框架。

## 5. 用户工作流

### 5.1 配置

当前没有 `metricproof init`。用户在项目根目录创建严格的
`.metricproof/config.yml`；首次交互确认时 `metricproof link` 可原子创建或更新
`.metricproof/claims.yml`，但不会创建远程资源。

### 5.2 扫描

```text
metricproof scan
```

读取配置指定的 LaTeX 入口，构建受控文件图，提取原始数值候选和基础表格结构，并报告解析限制。

阶段 4B2a 在原始候选和基础表格事实之上，为每个候选生成确定、可解释的启发式分类：
`ClaimDisposition`、`ClaimKind`、0–100 分数、置信等级和正负/中性证据。
默认摘要报告分类与表格统计；`--show-claims` 展示 likely/possible 复核队列，
`--show-all` 展示全部分类，`--show-tables` 保留结构调试，`--json` 使用 schema 3。
分类结果仍不是已确认链接；独立的阶段 5 身份服务随后生成 Claim ID/指纹。表头/方向语义仍未实现。

### 5.3 链接

```text
metricproof link
```

读取实验结果，针对未链接 Claim 生成可解释候选。每个候选保存 0–100 总分、逐项贡献、不确定性、建议 scale 和 direct/derived 类型；数值相同只能是一项证据，领先不足固定 margin 时显式标记 ambiguous。候选可以被用户确认、手工选择 observation、跳过或持久 IGNORE。未经确认的候选不得持久化为事实链接。

`--non-interactive` 和 `--json` 只生成建议，绝不等待输入或写 `claims.yml`。交互确认在内存聚合后只原子写一次；取消、Ctrl+C、无决定和失败都保持旧 Registry 不变。已有 active Link 不自动覆盖，broken Link 仅在 `--show-broken` 或按 Claim 指定时进入复核。

### 5.4 检查

```text
metricproof check
```

统一加载配置、一次论文扫描、Claim/链接和一次实验结果 catalog，迁移身份并执行当前三条规则，输出唯一、稳定排序的 `CheckResult`。当前不加载 Git 证据。

### 5.5 报告（后续）

当前没有 `metricproof report` 或 HTML 输出。未来报告必须基于与 `check` 相同的
`CheckResult`，不得维护第二套规则逻辑。

完整示例见 [docs/example-workflow.md](docs/example-workflow.md)。

## 6. 项目配置职责

`.metricproof/config.yml` 描述“项目如何被分析”，不保存某个 Claim 的人工确认状态。它负责：

- 论文入口、结果文件、实验配置文件、Claim Registry 精确路径和排除路径。
- JSON/YAML 的受控提取约定与 CSV 列映射。
- 指标别名和 `higher-is-better` / `lower-is-better` 方向。
- 全局或按指标的绝对容差、相对容差。
- 受控比较字段、允许差异和严重程度。
- 可识别的实验 Claim 范围、忽略模式和解析限制策略。
- 报告失败阈值等项目级策略。

配置必须有 `schema_version`，拒绝未知顶级字段，所有相对路径以项目根目录解析，并默认禁止路径逃逸。 `claim_registry_path` 默认为 `.metricproof/claims.yml`，只接受项目相对 POSIX `.yml` / `.yaml` 精确路径。

## 7. Claim 链接文件职责

`.metricproof/claims.yml` 描述“用户确认了哪些论文 Claim 与哪些实验来源相关”，不复制完整实验结果。它负责：

- 保存 Claim 身份、来源指纹和用户确认状态。
- 保存直接链接或受控派生链接。
- 保存实验来源、run、metric/selector、scale 和可选容差覆盖。
- 保存忽略记录及原因。
- 保存安全迁移 Claim 身份所需的旧指纹信息。

它必须有 `schema_version`，严格验证所有未知顶级与嵌套字段，按 Claim ID 稳定排序，并采用同目录临时文件、flush、fsync 和原子替换。来源失效时保留链接并标记为 broken，不静默删除。

首版 DirectLink 只引用一个明确 MetricReference。DerivedLink 只允许单层 `subtraction`、`relative_change`、`mean`、`standard_deviation`，不接受嵌套操作、代码或表达式。缩放只允许 identity、fraction_to_percent、percent_to_fraction；所有容差和计算参数均为显式 Decimal 数据。

详细结构见 [docs/data-model.md](docs/data-model.md)。

## 8. 当前证据链

阶段 5 已实现的证据链为：

```text
LaTeX Claim
  → claims.yml 中的用户确认 Link
  → MetricObservation 或 DerivedLink 操作数
  → 声明的本地实验结果源文件与 selector
```

每个节点都可定位；缺失来源形成 link/input diagnostic，不能推断或伪造。实验配置
比较与 Git commit/worktree 证据链属于后续阶段，当前 `check` 不读取它们。

## 9. 数值语义

### 9.1 表示

- 解析和计算使用十进制精确表示，不以二进制浮点字符串比较。
- 原始文本、解析值、单位、缩放、小数位数和来源位置分别保存。
- 百分数先解析为比例语义，例如 `87.2\%` 的规范值为 `0.872`。
- 普通小数不自动解释为百分数；链接必须显式声明必要缩放。

### 9.2 百分比、百分点和普通差值

- 普通差值：`candidate - baseline`，保持指标原生单位。
- 百分点变化：当两侧为比例时，`(candidate - baseline) × 100` points。
- 相对变化：`(candidate - baseline) / |baseline| × 100%`；baseline 为零时不可计算。
- 工具不根据单个 `%` 符号猜测作者意图；派生链接必须声明 operation 和输出单位。

### 9.3 容差与显示精度

比较顺序：

1. 将论文值和实验值转换到同一规范单位。
2. 根据论文显示的小数位数构造可接受的舍入区间。
3. 使用配置的绝对/相对容差扩展该区间。
4. 仅当实验值落在扩展区间之外时，才产生数值不一致诊断。

有效容差使用：

```text
max(abs_tolerance, rel_tolerance × max(|expected|, |observed|))
```

派生值展示默认采用十进制 `ROUND_HALF_UP`，但规则比较优先使用显示区间，避免只因最后一位舍入方式产生误报。

## 10. 格式支持边界

### 10.1 JSON / YAML

- 阶段 3 已实现显式 `structured.metrics` / `structured.metadata` 点路径映射。
- 单 run 来源在固定 `run_id` 与 `run_id_selector` 中二选一；多 run 数组必须显式配置 `records_selector` 和 `run_id_selector`。
- 支持嵌套映射，并用稳定点路径表示 `source_selector`；整数路径段仅作为显式数组索引。
- 只把有限数值识别为指标；布尔值不是指标。
- `NaN`、`Infinity` 和类型冲突必须产生明确输入诊断。
- 数值数组不在没有显式配置时自动解释为多 seed 指标。
- YAML 只使用安全加载，不支持任意对象构造；重复 key、多 document 和递归结构受控失败。
- JSON 检测重复对象 key，并以词法十进制直接构造 `Decimal`。

### 10.2 CSV

- 阶段 3 已实现标准库 `csv` 读取，每一数据行对应一个 run。
- 只支持带表头的普通二维 CSV。
- 通过配置声明 `run_id_column`、`metadata_columns` 和 `metric_columns`。
- 不自动猜测任意 CSV 结构。
- 重复表头、缺列、非法数值和关键空值必须可定位。

### 10.3 LaTeX

阶段 4A 已实现：

- 静态相对 `\input{}` / `\include{}` 文件图，含循环、缺失文件与路径逃逸防护；
- 注释、`\verb` 和代码环境屏蔽；
- 正文、数学、命令参数、表格环境与 caption 中的原始数值候选；
- 文件、行、列和字符范围，以及确定性的 include provenance。

阶段 4B1 已实现基础表格结构事实：

- 可选 `table` / `table*` 容器与独立 `tabular` / `tabular*`；同一容器内多个 tabular 独立建模并共享明确归属的 caption/label；
- 当前 tabular 层级的未转义 `&`、顶层 `\\` 与 `\tabularnewline`；花括号、数学、嵌套环境、注释和代码环境内的分隔符不生效；
- 精确行、单元格和内容范围，空单元格与无显式终止符的最后一行；
- 原始列规格，以及可可靠计数的 `l`/`c`/`r`、`p`/`m`/`b`、竖线、`@{...}` 和受限 `*{N}{spec}`；未知列类型保留原文并降级；
- `\hline`、`\cline`、`\toprule`、`\midrule`、`\bottomrule`、`\cmidrule` 和 `\addlinespace` 结构标记；
- 基础 `\multicolumn{N}{FORMAT}{CONTENT}`，其中 N 必须是受限正整数字面量；
- `\multirow` 只识别并产生 limitation，不展开跨行结构；
- 复用现有 `RawNumericCandidate`，并把 `\textbf{...}` / `\underline{...}` 的精确范围关联到各个具体候选；
- `parsed`、`degraded`、`unsupported` 可靠性；`longtable`、`tabularx`、`array`、`matrix` 和 `aligned` 明确认定为 unsupported。

表格解析不执行 TeX 或宏，不推断表头、指标、模型、数据集、higher/lower-is-better，
也不判断粗体或下划线是否正确。复杂 multirow、动态生成表格、LuaTeX、外部命令和
编译后 PDF 不在本阶段范围。无法可靠解析时保留普通候选和其他表格，产生可定位的
input/limitation diagnostic，不猜测高置信度结构。

固定表格资源上限包括：1,000 张表、单表 10,000 行、单行 1,000 个物理单元格、
单表 100,000 个单元格、单元格 100,000 字符、表格嵌套深度 16、multicolumn span 1,000。

## 11. Claim 身份稳定性

阶段 5 已实现版本 1 的稳定 Claim 身份。claim_id 使用 clm_ 加截断 SHA-256，
不包含论文内容明文、绝对路径、绝对行号、随机 UUID 或 Python hash()。

身份摘要输入包括：

- 项目相对 POSIX 文件路径。
- Claim kind。
- 正文语法环境或表格 label/caption、逻辑行列。
- 规范化、有限、使用数字占位符的前后文锚点。
- 同一局部身份组成下的 occurrence ordinal。
- 显式 fingerprint_version。

规范数值、单位与 Claim kind 另行形成 semantic_digest，不进入稳定 ID 主摘要。因此，
数字本身变化但位置与非数字锚点稳定时可以保持同一 ID，同时保留可审计的语义变化。
绝对行列和字符范围只作为当前定位与迁移弱证据。

迁移按稳定 ID、版本化上下文、结构锚点、有限文本相似度和位置接近度分层评分。
只有唯一候选达到阈值且与次名保持安全分差时才迁移；近似同分、重复内容、摘要碰撞
或多个旧 Claim 指向同一新 Claim 时分别返回 ambiguous / collision，不得自动绑定。
唯一高置信上下文可支持文件重命名；复杂重排仍允许返回 missing 或要求人工确认。
## 12. 错误模型与退出码

### 12.1 诊断类别

- Rule diagnostic：当前三条 MVP 规则的结果。
- Input diagnostic：配置、LaTeX、结果文件、链接文件或 Git 证据问题。
- Limitation diagnostic：输入超出首版可靠支持范围。
- Internal error：未预期的软件缺陷。

所有用户可见诊断至少包含 code/rule、severity、location、message 和 evidence。规则诊断还应包含 observed、expected、confidence 和 remediation。

### 12.2 退出码

| 退出码 | 语义 |
|---:|---|
| `0` | 命令完成，且没有达到配置的失败阈值 |
| `1` | 分析完成，但规则诊断达到 `--fail-on` 阈值 |
| `2` | CLI 用法或项目配置无效 |
| `3` | 输入、解析、链接 schema 或数据完整性错误导致命令无法完成 |
| `4` | 环境或只读工具错误，例如文件权限、Git 不可用或命令超时 |
| `5` | 未处理的内部错误 |
| `130` | 用户中断 |

非致命 limitation 不单独改变退出码，除非用户策略将其严重程度配置到失败阈值。机器可读输出必须同时给出错误结构，不能只依赖退出码。

## 13. 完成标准

阶段 5 本地 MVP 达成的必要条件：

- 三条当前规则均通过端到端示例验证。
- Claim、Link、Observation 和 CheckDiagnostic 具备稳定、明确的数据模型。
- 所有持久化格式有 schema version 和严格验证。
- 不可靠输入受控降级，不输出过度断言。
- 终端与 JSON 共享同一 `CheckResult`。
- Windows、Linux、macOS 路径均基于 `pathlib`。
- 自动测试、静态检查、包构建和离线演示通过。
- 后续两条规则、HTML 与 Git/GitHub evidence 未提前实现。

## 14. 阶段依赖顺序

1. 设计规格、架构和仓库约束。
2. Python 工程骨架与质量工具。
3. 配置、领域模型和实验结果读取。
4. LaTeX 原始候选、基础表格结构，再进入 Claim 提取。
5. Claim-to-Metric 链接。
6. `STALE_VALUE`、`WRONG_DELTA`、`MISSING_PROVENANCE`。
7. `WRONG_BEST_MARK`、`UNFAIR_COMPARISON`。
8. 完整 CLI 与报告。
9. Git 证据链与 GitHub Actions 文件。
10. 端到端加固和开源前准备。

后续阶段不得绕过前置模型直接在 CLI 或报告层实现规则逻辑。
