# MetricProof 产品规格

## 1. 产品定义

MetricProof 是一个开源、本地优先的 Python 3.13 命令行工具。

> Unit tests for experimental claims.

它检查机器学习论文源码中的实验数字、派生数字、表格最优/次优标记和用户声明的受控比较条件，是否与本地实验结果、实验配置及 Git 证据保持一致。

MetricProof 产生的是可复核的“一致性诊断”或“启发式风险”，不是对论文正确性、研究质量或学术诚信的裁决。

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
- 单文件、离线可打开的静态 HTML 报告。
- 稳定退出码，供本地脚本和未来 CI 使用。

### 3.3 首版规则

| 规则 | 目的 |
|---|---|
| `STALE_VALUE` | 检查已链接论文值与当前实验指标是否一致 |
| `WRONG_DELTA` | 重新计算受控派生值并检查论文显示值 |
| `MISSING_PROVENANCE` | 报告未链接且未忽略的实验 Claim |
| `WRONG_BEST_MARK` | 检查基础表格中的最优/次优格式 |
| `UNFAIR_COMPARISON` | 报告用户声明受控字段的配置差异风险 |

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

### 5.1 初始化

```text
metricproof init
```

在项目根目录中创建最小配置模板：

```text
.metricproof/
├── config.yml
└── claims.yml
```

默认不覆盖已有文件，不创建远程资源。

### 5.2 扫描

```text
metricproof scan
```

读取配置指定的 LaTeX 入口，构建受控文件图，提取候选 Claim 和基础表格结构，并报告解析限制。

阶段 4A 交付到“原始数值候选 + 基础语法上下文”为止。原始候选不得被描述为
已确认 Claim，也不生成 Claim ID、表格行列语义或持久链接；这些属于后续阶段。

### 5.3 链接

```text
metricproof link
```

读取实验结果，针对未链接 Claim 生成可解释候选。候选可以被用户确认、跳过或标记为非实验数字。未经确认的候选不得持久化为事实链接。

### 5.4 检查

```text
metricproof check
```

统一加载配置、Claim、链接、实验结果、实验配置和 Git 证据，执行适用规则，输出稳定排序的诊断。

### 5.5 报告

```text
metricproof report --format html
```

基于与 `check` 相同的结果模型生成报告，不维护第二套规则逻辑。

完整示例见 [docs/example-workflow.md](docs/example-workflow.md)。

## 6. 项目配置职责

`.metricproof/config.yml` 描述“项目如何被分析”，不保存某个 Claim 的人工确认状态。它负责：

- 论文入口、结果文件、实验配置文件和排除路径。
- JSON/YAML 的受控提取约定与 CSV 列映射。
- 指标别名和 `higher-is-better` / `lower-is-better` 方向。
- 全局或按指标的绝对容差、相对容差。
- 受控比较字段、允许差异和严重程度。
- 可识别的实验 Claim 范围、忽略模式和解析限制策略。
- 报告失败阈值等项目级策略。

配置必须有 `schema_version`，拒绝未知顶级字段，所有相对路径以项目根目录解析，并默认禁止路径逃逸。

## 7. Claim 链接文件职责

`.metricproof/claims.yml` 描述“用户确认了哪些论文 Claim 与哪些实验来源相关”，不复制完整实验结果。它负责：

- 保存 Claim 身份、来源指纹和用户确认状态。
- 保存直接链接或受控派生链接。
- 保存实验来源、run、metric/selector、scale 和可选容差覆盖。
- 保存忽略记录及原因。
- 保存安全迁移 Claim 身份所需的旧指纹信息。

它必须有 `schema_version`，严格验证未知字段，稳定排序，采用原子写入。来源失效时保留链接并标记为 broken，不静默删除。

详细结构见 [docs/data-model.md](docs/data-model.md)。

## 8. 证据链

完整证据链为：

```text
LaTeX Claim
  → claims.yml 中的用户确认 Link
  → MetricObservation 或 DerivedLink 操作数
  → 实验结果源文件
  → 实验配置源文件
  → Git commit / 工作树状态
```

每个节点都必须可定位。缺失节点显示为 unavailable 或 broken，不能推断或伪造。

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

首版计划支持：

- 正文整数、小数、负数、科学计数法、百分数、基础 `mean ± std`。
- 注释排除。
- 基础 `table` / `tabular`、`\textbf{}`、`\underline{}`、caption 和 label。
- 相对路径 `\input{}` / `\include{}`，含循环与路径逃逸防护。
- 文件、行、列和字符范围。

首版不保证支持：

- 任意自定义宏展开。
- `siunitx` 全部语法。
- `multicolumn`、`multirow` 等复杂结构的可靠语义比较。
- 动态生成表格、LuaTeX 代码、外部命令和编译后 PDF。

无法可靠解析时应保留其他可分析内容并产生 limitation 诊断，不得猜测结构。

阶段 4A 当前已实现静态 include 图、注释/代码环境屏蔽、上述基础数值词法、
源位置和正文/数学/命令参数/表格环境/caption 上下文。表格结构语义与
Claim 分类仍未实现。

## 11. Claim 身份稳定性

Claim ID 不以绝对行号为主键。首版采用版本化上下文指纹，输入至少包括：

- 项目相对文件路径。
- Claim 类型和规范化数值语义。
- 所在结构锚点，例如最近 section、表格 label、行头和列头。
- 去除无关空白与注释后的有限前后文。

绝对行列仅作为当前定位信息。普通前方插行不应改变指纹。

当多个 Claim 得到同一指纹时，系统不得静默绑定；应标记 collision/ambiguous，要求用户重新确认。文件重命名可能改变 ID，首版只尝试基于旧指纹和上下文唯一匹配进行安全迁移。

## 12. 错误模型与退出码

### 12.1 诊断类别

- Rule diagnostic：五条规则的结果。
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

首版本地 MVP 达成的必要条件：

- 五条规则均通过端到端示例验证。
- Claim、Link、Observation 和 Diagnostic 具备稳定、明确的数据模型。
- 所有持久化格式有 schema version 和严格验证。
- 不可靠输入受控降级，不输出过度断言。
- CLI、JSON、HTML 共享同一检查结果模型。
- Windows、Linux、macOS 路径均基于 `pathlib`。
- 自动测试、静态检查、包构建和离线演示通过。

## 14. 阶段依赖顺序

1. 设计规格、架构和仓库约束。
2. Python 工程骨架与质量工具。
3. 配置、领域模型和实验结果读取。
4. LaTeX Claim 与表格提取。
5. Claim-to-Metric 链接。
6. `STALE_VALUE`、`WRONG_DELTA`、`MISSING_PROVENANCE`。
7. `WRONG_BEST_MARK`、`UNFAIR_COMPARISON`。
8. 完整 CLI 与报告。
9. Git 证据链与 GitHub Actions 文件。
10. 端到端加固和开源前准备。

后续阶段不得绕过前置模型直接在 CLI 或报告层实现规则逻辑。
