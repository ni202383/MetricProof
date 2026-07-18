# MetricProof 架构设计

## 1. 架构目标

架构优先保证：

- 规则可确定性测试，不依赖 CLI、Rich、Jinja2 或真实文件系统。
- LaTeX、实验文件、Git 和持久化操作均可替换为测试适配器。
- 同一 `CheckResult` 已供终端和 JSON 复用；未来 HTML 必须复用同一模型。
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
- 阶段 4B1 的基础表格、行、单元格、格式范围和可靠性事实。
- 后续阶段的论文 Claim 与表头/指标/最佳值语义。
- 实验 Run、MetricObservation 和配置快照。
- DirectLink、DerivedLink、IgnoreRecord 和 ComparisonSpec。
- Evidence、Diagnostic、Severity 和规则代码。
- 当前三条 MVP 规则的纯计算；后续两条规则不在本阶段。

领域对象的字段设计见 [docs/data-model.md](docs/data-model.md)。

## 5. 应用服务

### 5.1 `InitializeProject`

输入项目根目录和覆盖策略，通过端口创建配置模板。它不直接调用 Typer，也不创建远程资源。

### 5.2 `ScanPaper`

阶段 4B1 已实现的 `ScanPaper` 协调配置与 `PaperScanner` 端口，输出：

- `PaperScanResult`
- LaTeX 文件图
- 原始数值候选
- 基础 LaTeX 表格、行、单元格、结构标记与格式事实
- 输入与 limitation 诊断

它不执行 Claim 分类、Claim ID、表头/指标推断或最佳值判断。阶段 4B2a 的独立分类服务只消费该结果。

### 5.3 `ClassifyClaimCandidates`

接收 `PaperScanResult` 和已验证的指标别名，构建一次候选到表格上下文索引，返回稳定排序的
`ClaimClassificationResult`。它不读取磁盘、实验结果或具体适配器，不修改 `PaperScanResult`，
也不建立持久 Claim 身份或链接。

### 5.3a PrepareClaimIdentities

阶段 5 的身份服务复用同一个 PaperScanResult 与分类结果，为 likely/possible
（以及用户显式要求的 ambiguous）建立版本 1 指纹和稳定 ID。它只消费领域对象，
不重新读取 LaTeX。可选迁移接收持久身份快照，按稳定 ID、上下文、结构和位置分层匹配，
输出 EXACT、MIGRATED、AMBIGUOUS、MISSING 或 COLLISION；成功迁移保留旧的
持久 Claim ID，任何非唯一结果都不自动绑定。

### 5.4 `LoadExperiments`

协调结果文件和实验配置读取，输出稳定排序的：

- `ExperimentRun`
- `MetricObservation`
- 输入诊断

### 5.5 `SuggestLinks`

阶段 5C 的纯领域匹配器接收 `IdentifiedClaim`、已加载 `ExperimentCatalog` 和严格 metric aliases，输出带逐项贡献、建议 scale/type 和不确定性的 `CandidateMatch`。应用层 `suggest_links` 只适配 `ProjectConfiguration`；同分/近似同分标记 ambiguous，任何候选都不自行确认或写 Registry。

### 5.6 `UpdateClaimRegistry`

阶段 5B 由 `load_claim_registry`、`save_claim_registry` 和 `save_claim_registry_entry` 通过 `ClaimRegistryRepository` 读取或持久化已验证领域对象。应用层不实例化 YAML 或文件适配器。迁移或碰撞不唯一时，上游不得构造 active 写入；Registry 保留 ambiguous/missing/broken 状态和迁移证据。

### 5.7 `CheckProject`

阶段 5D 已实现。它消费一次 `PaperScanResult`、一次 `ExperimentCatalog`、已验证配置和
`ClaimRegistry`，构建一个 `LinkSession`，处理迁移/失效链接，再按选择运行三条纯规则。
输出是稳定排序、schema version `1` 的唯一 `CheckResult`。规则不访问文件，应用服务
不实例化适配器。

### 5.8 输出渲染

当前终端与 JSON renderer 都只消费 `CheckResult`，不重新执行或复制规则。HTML
`BuildReport` 仍是后续设计，当前未实现。

## 6. 应用端口

首版稳定端口以 Python 协议或抽象接口表达，名称可在实现阶段微调，但职责不可混合：

| 端口 | 职责 |
|---|---|
| `ProjectFileSystem` | 安全解析项目相对路径、受控读取、原子写入、文件发现 |
| `ConfigurationRepository` | 读取并验证 `config.yml` |
| `ClaimRegistryRepository` | 读取、验证和原子保存 `claims.yml` |
| `PaperScanner` | 从 LaTeX 入口生成文件图、原始数值候选、基础表格事实和解析诊断 |
| `ExperimentSourceReader` | 把 JSON/YAML/CSV 归一化为 Run 和 Observation |
| `ExperimentConfigReader` | 读取受控配置字段及来源位置 |
| `GitEvidenceProvider` | 只读获取仓库、commit、branch 和工作树证据 |
| `ReportRenderer` | 后续 HTML 等报告端口；当前终端/JSON 为 CLI 纯渲染函数 |

适配器不得通过“万能上下文对象”绕过端口职责。

## 7. 适配器

### 7.1 配置与链接

阶段 5B 的 `YamlClaimRegistryRepository` 已实现：

- Pydantic strict/extra-forbid 模型负责顶级和全部嵌套字段 schema 验证。
- YAML 只安全加载一个文档，危险标签、重复键、多文档和错误类型受控失败。
- Registry 路径和所有 Link 来源均为项目相对 POSIX 路径；拒绝绝对路径、反斜杠、`..` 与符号链接逃逸。
- 缺失 registry 读取为空集合，不隐式创建目录；保存要求项目内父目录已存在。
- Claim ID 稳定排序且唯一，每项必须恰好保存 link 或 ignore；领域不变量在反序列化后再次验证。
- 写入同目录临时文件，flush/fsync 后以 `os.replace` 原子替换；失败时保留旧文件并清理临时文件。
- schema 版本不兼容时失败，不猜测迁移。

### 7.2 LaTeX

采用“文件图 → 词法/遮罩 → 基础表格结构 → Claim 分类 → 表格语义”流水线，避免用巨大正则模拟 TeX。阶段 4B2a 已实现前四步：

- `LocalLatexPaperScanner` 负责静态 include、循环、缺失文件、路径边界和集中资源限制；每个物理文件只读取一次。
- Stage 4A 状态机生成原始文本、等长注释/代码遮罩、位置映射、环境上下文与 `RawNumericCandidate`。
- `latex_tables` 适配器只消费上述已准备数据，不重新读取文件、不生成第二套位置或数值候选。
- 表格状态机在当前 tabular 层级跟踪花括号深度、数学上下文、嵌套环境和转义，只把顶层 `&`、`\\` 与 `\tabularnewline` 作为分隔符。
- adapter 将解析事实转换为不可变领域对象；domain 不保存第三方 parser、文件系统或 Rich 对象。
- `scan_paper` 只依赖端口与领域对象；`--file` 同时过滤已构建图中的候选和表格。
- `parsed` 可供后续结构消费；`degraded` 保留恢复结果但不得当作完全可靠；`unsupported` 只确认环境边界，不伪造行列。
- Claim 分类使用纯领域启发式和一次表格索引；阶段 5 身份服务在其上建立版本化 Claim ID 与可解释迁移。表头/指标正式映射和 best/second-best 判断仍未实现。

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

当前只有 `doctor` 的本地只读 Git 检查：使用参数列表、禁止 `shell=True` 并设置超时。
`check` 不加载 Git 证据；Git evidence chain 属于后续阶段。

### 7.5 输出

- Console renderer 可使用 Rich，但只展示 `CheckResult`。
- JSON renderer 输出 schema version `1`，字段与排序由同一 `CheckResult` 决定。
- HTML adapter 尚未实现。

## 8. 数据流

### 8.1 Scan

```text
config.yml
  → resolve paper entries
  → build LaTeX file graph
  → extract raw numeric candidates
  → parse bounded basic table structures
  → classify raw candidates
  → compute versioned Claim fingerprints and stable identities
  → PaperScan
```

### 8.2 Link

```text
one PaperScan + ExperimentCatalog + ClaimRegistry + aliases
  → classify and identify current Claims
  → deterministic one-to-one migration
  → active/ignored/broken/ambiguous/missing/unlinked LinkSession
  → explainable, stable CandidateMatch ranking
  → explicit user decision or read-only non-interactive output
  → one validated atomic claims.yml update
```

### 8.3 Check

```text
Config + one PaperScan + one ExperimentCatalog + ClaimRegistry
  → LinkSession + deterministic identity migration
  → selected STALE_VALUE / WRONG_DELTA / MISSING_PROVENANCE rules
  → CheckSummary + stable CheckDiagnostics
  → CheckResult schema 1
```

### 8.4 Output

```text
CheckResult
  ├── ConsoleRenderer (implemented)
  ├── JsonRenderer (implemented)
  └── HtmlRenderer (future; not implemented)
```

## 9. 确定性与稳定排序

相同输入必须生成相同结果：

- 文件按项目相对 POSIX 风格路径排序。
- 基础表格按文件和字符起点排序；行、单元格、结构标记和候选引用按源码顺序排序。
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
- 未来 HTML 实现必须转义所有用户文本；当前没有 HTML 输出。
- 文件大小、include 深度、文件数量、表格数、行/单元格数、单元格长度、表格嵌套和 multicolumn span 具有集中内置上限。
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
- E2E：在虚构 demo project 上验证三条 MVP 规则、正常反例、ignore 与前插迁移。

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
- 当前用户闭环命令是 `scan`、`link`、`check` 与 `experiments`；`doctor` 提供环境检查。`init`、`report` 当前未实现。
- `PaperScanResult.tables` 是后续 Claim/表格语义阶段唯一允许消费的基础表格事实来源。
- `CheckResult` 是当前终端/JSON以及未来报告格式的唯一事实来源。
