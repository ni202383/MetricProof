# MetricProof 架构设计

## 1. 架构目标

架构优先保证：

- 规则可确定性测试，不依赖 CLI、Rich、Jinja2 或真实文件系统。
- LaTeX、实验文件、Git 和持久化操作均可替换为测试适配器。
- 同一领域结果可供终端、JSON 和 HTML 报告复用。
- 首版模块数量足以表达职责，但不建立插件系统、数据库或服务端。
- 不可靠或不完整的输入通过显式诊断传播，不静默吞掉。
- Python 3.13 是当前运行、测试、静态检查和构建基线。

## 2. 分层与依赖方向

```text
Composition Root / CLI
        │
        ▼
Application Services ───────────────► Application Ports
        │                                   ▲
        ▼                                   │ implements
Pure Domain Models + Rule Engine        Adapters
                                            │
                    ┌───────────────────────┼──────────────────────┐
                    ▼                       ▼                      ▼
                File/YAML              LaTeX/Results            Git/Reports
```

允许的依赖：

```text
cli → application → domain
adapters → application ports + domain
composition root → cli/application/adapters
```

禁止的依赖：

- `domain` 不依赖 `application`、`adapters` 或 `cli`。
- `application` 不依赖具体适配器、Typer、Rich 或 Jinja2。
- 规则模块不读取文件、不运行 Git、不解析 YAML、不渲染报告。
- 报告层不重新计算规则结论。

## 3. 建议目录

```text
metricproof/
├── src/
│   └── metricproof/
│       ├── domain/
│       │   ├── models.py
│       │   ├── numeric.py
│       │   ├── diagnostics.py
│       │   └── rules/
│       ├── application/
│       │   ├── ports.py
│       │   └── services/
│       ├── adapters/
│       │   ├── config/
│       │   ├── latex/
│       │   ├── experiments/
│       │   ├── claims/
│       │   ├── git/
│       │   └── reports/
│       ├── cli/
│       └── bootstrap.py
├── tests/
│   ├── unit/
│   ├── integration/
│   └── e2e/
├── examples/
├── docs/
├── pyproject.toml
└── AGENTS.md
```

这是职责地图，不要求阶段 1 创建所有空模块。只有出现真实职责时才创建文件。

## 4. 核心领域

领域层负责表达事实与规则，不负责如何读取或显示：

- 源位置与项目相对路径。
- 数值、单位、显示精度与容差。
- 阶段 4A 的 LaTeX 文件图、原始数值候选和基础语法上下文。
- 论文 Claim 和表格结构。
- 实验 Run、MetricObservation 和配置快照。
- DirectLink、DerivedLink、IgnoreRecord 和 ComparisonSpec。
- Evidence、Diagnostic、Severity 和规则代码。
- 五条规则的纯计算。

领域对象的字段设计见 [docs/data-model.md](docs/data-model.md)。

## 5. 应用服务

### 5.1 `InitializeProject`

输入项目根目录和覆盖策略，通过端口创建配置模板。它不直接调用 Typer，也不创建远程资源。

### 5.2 `ScanPaper`

阶段 4A 已实现部分协调配置与 `PaperScanner` 端口，输出：

- `PaperScanResult`
- LaTeX 文件图
- 原始数值候选
- 输入与 limitation 诊断

它不执行 Claim 分类、Claim ID 或表格语义。后续阶段只能基于该结果继续建模。

### 5.3 `LoadExperiments`

协调结果文件和实验配置读取，输出稳定排序的：

- `ExperimentRun`
- `MetricObservation`
- 输入诊断

### 5.4 `SuggestLinks`

接收 Claim、Observation、指标别名和上下文，输出带特征贡献的 `CandidateMatch`。它不自行确认链接。

### 5.5 `UpdateClaimRegistry`

验证用户选择，将 DirectLink、DerivedLink 或 IgnoreRecord 原子持久化。迁移或碰撞不唯一时拒绝写入。

### 5.6 `CheckProject`

构建只读 `CheckContext`，按稳定顺序运行适用规则，返回统一 `CheckResult`。规则本身不通过服务访问文件。

### 5.7 `BuildReport`

把 `CheckResult` 交给报告端口。终端、JSON 和 HTML 不得拥有独立规则语义。

## 6. 应用端口

首版稳定端口以 Python 协议或抽象接口表达，名称可在实现阶段微调，但职责不可混合：

| 端口 | 职责 |
|---|---|
| `ProjectFileSystem` | 安全解析项目相对路径、受控读取、原子写入、文件发现 |
| `ConfigurationRepository` | 读取并验证 `config.yml` |
| `ClaimRegistryRepository` | 读取、验证和原子保存 `claims.yml` |
| `PaperScanner` | 从 LaTeX 入口生成文件图、原始数值候选和解析诊断 |
| `ExperimentSourceReader` | 把 JSON/YAML/CSV 归一化为 Run 和 Observation |
| `ExperimentConfigReader` | 读取受控配置字段及来源位置 |
| `GitEvidenceProvider` | 只读获取仓库、commit、branch 和工作树证据 |
| `ReportRenderer` | 将统一结果模型渲染为目标格式 |

适配器不得通过“万能上下文对象”绕过端口职责。

## 7. 适配器

### 7.1 配置与链接

- Pydantic 负责 schema 验证。
- YAML 使用安全加载。
- 未知顶级字段拒绝。
- 写入临时文件、刷新后在同一文件系统内原子替换。
- schema 版本不兼容时失败，不猜测迁移。

### 7.2 LaTeX

采用“文件图 → 词法/基础结构解析 → Claim 分类 → 表格建模”流水线，避免一个巨大正则模拟 TeX。阶段 4A 只实现前两步：

- `LocalLatexPaperScanner` 负责静态 include、循环、缺失文件、路径边界和集中资源限制。
- 小型确定性状态机屏蔽注释与代码环境，保留原始范围、数值语义、环境栈和基础上下文。
- `scan_paper` 只依赖端口与领域对象；`--file` 只能过滤已构建图中的文件。
- Claim 分类与表格语义尚未实现。

### 7.3 实验结果

阶段 3 当前实现为：

- `YamlConfigurationRepository` 实现 `ConfigurationRepository`，在适配器边界使用 Pydantic 严格模型和安全 YAML loader。
- `LocalExperimentSourceReader` 实现 `ExperimentSourceReader`，按声明格式分派 JSON/YAML/CSV，但共享 Decimal、selector、诊断和资源边界。
- `load_experiments` 只依赖端口与领域对象，按稳定来源顺序合并 run；重复 metric 和冲突 metadata/config reference 形成阻断诊断。
- JSON/YAML 使用显式点路径，不对任意数值字段或数组做自动指标发现。
- CSV 完全由配置声明列角色，使用标准库 `csv`，不依赖 pandas。
- 适配器返回 `SourceReadResult`；领域目录结果统一为 `ExperimentCatalog`。
- 固定资源上限集中位于 `adapters/limits.py`，不是散落魔法数字或可执行配置。

### 7.4 Git

- 使用参数列表调用 Git，不使用 `shell=True`。
- 只执行读取操作，设置超时。
- Git 缺失、浅克隆、detached HEAD 和 dirty state 均显式建模。
- Git 证据缺失不允许被填充为虚假 commit。

### 7.5 报告

- Console adapter 可使用 Rich。
- JSON adapter 输出版本化 schema。
- HTML adapter 使用 Jinja2 自动转义并内嵌必要样式，不依赖 CDN。

## 8. 数据流

### 8.1 Scan

```text
config.yml
  → resolve paper entries
  → build LaTeX file graph
  → extract numeric tokens/tables
  → classify Claims
  → compute Claim fingerprints
  → PaperScan
```

### 8.2 Link

```text
PaperScan + ExperimentCatalog + aliases
  → deterministic candidate features
  → ranked CandidateMatch list
  → user decision
  → validated atomic claims.yml update
```

### 8.3 Check

```text
Config + PaperScan + ExperimentCatalog + ClaimRegistry + GitEvidence
  → CheckContext
  → ordered rule execution
  → Diagnostics + EvidenceGraph + Summary
  → CheckResult
```

### 8.4 Report

```text
CheckResult
  ├── ConsoleRenderer
  ├── JsonRenderer
  └── HtmlRenderer
```

## 9. 确定性与稳定排序

相同输入必须生成相同结果：

- 文件按项目相对 POSIX 风格路径排序。
- Claim 按文件、字符起点、Claim ID 排序。
- Observation 按 run、metric、来源选择器排序。
- CandidateMatch 按总分降序，再按稳定身份排序。
- Diagnostic 按 severity、rule code、位置和证据身份排序。
- YAML/JSON 持久化字段和条目使用定义好的顺序。

不使用当前时间、随机 UUID 或哈希随机化作为领域身份。

## 10. 安全边界

- 所有配置路径规范化后必须留在项目根目录内。
- include、glob、报告输出和临时文件同样执行路径边界检查。
- 不执行 TeX、训练代码、任意表达式或 YAML 对象构造。
- DerivedLink 只允许枚举操作，不允许 `eval` / `exec`。
- HTML 中所有用户文本转义。
- 文件大小、include 深度和文件数量应具有可配置或内置上限。
- Git 子进程禁止 shell，限制命令集合并设置超时。

## 11. 错误传播

- 适配器把预期输入问题转换为结构化诊断或类型化应用错误。
- 应用服务决定错误是否阻断当前命令。
- CLI 只负责映射为 stderr、机器输出和退出码。
- 未预期异常映射为退出码 5，并保留可用于本地排障的错误标识；不把完整环境秘密写入报告。
- 禁止 `except Exception: pass` 或返回空集合伪装成功。

## 12. 测试策略

- Domain：纯单元测试，覆盖数值、ID、规则和排序边界。
- Application：用内存端口测试编排、错误传播和写入决策。
- Adapter：使用临时目录和固定样例验证格式与安全边界。
- CLI：验证参数、stdout/stderr、JSON 纯净度和退出码。
- E2E：在虚构 demo project 上验证五条规则与正常反例。

修复缺陷必须先或同时增加能复现问题的回归测试。

## 13. 不采用的设计

- 不采用事件总线或消息队列：首版本地同步流程没有需求。
- 不采用数据库或 ORM：YAML 配置和链接足以满足首版。
- 不采用插件发现机制：会增加兼容性承诺和抽象成本。
- 不采用全局 Service Locator：会隐藏依赖并降低可测试性。
- 不采用“所有输入都转字典”：领域语义需要明确类型。
- 不采用自动运行实验：超出安全和产品范围。

## 14. 下一阶段稳定接口

工程骨架阶段可以依赖以下稳定边界：

- 包分层：`domain`、`application`、`adapters`、`cli`。
- 应用服务不依赖具体适配器。
- 核心领域不依赖 Pydantic、Typer、Rich、Jinja2 或 Git。
- 所有项目路径以 `pathlib.Path` 进入边界，以项目相对路径进入领域。
- CLI 最终命令集合固定为 `init`、`scan`、`link`、`check`、`report`，可增加辅助子命令但不得替换核心流程。
- `CheckResult` 是所有报告格式的唯一事实来源。
