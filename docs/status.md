# MetricProof 项目状态

更新日期：2026-07-18

## 当前阶段

阶段 5：本地可演示 MVP（5A–5E）。

状态：稳定身份、严格 Registry、可解释 link、三条核心规则、统一 CheckResult、check CLI 与虚构 MVP demo 已实现并通过最终验收。

## 阶段 5A 已实现

- likely/possible 分类默认进入身份系统；ambiguous 仅在调用方显式要求时进入，non-experiment 默认不创建待链接身份。
- StableClaimId 使用 clm_ 加 20 位截断 SHA-256；不含论文明文、绝对路径或绝对行号，不使用随机 UUID 或 Python hash()。
- 版本 1 指纹组合项目相对 POSIX 路径、Claim kind、语法/表格结构锚点、数字占位后的有限前后文与 occurrence ordinal。
- 规范数值和单位单独形成 semantic digest，不进入主 ID；数字演化可保持身份并保留语义变化证据。
- 表格 Claim 使用 label 优先、caption 次之的锚点，并保存逻辑行列；正文 Claim 使用语法环境与命令上下文。
- ClaimIdentityResult 稳定排序并显式报告任何截断摘要碰撞，不静默覆盖。
- 迁移先按稳定 ID，再按版本化 context digest、结构锚点、有限 token 重合、表格锚点和位置接近度评分。
- 自动迁移最低 70 分且要求领先次名 15 分；近似同分返回 AMBIGUOUS，重复旧 ID、当前 ID 碰撞或多个旧 Claim 指向同一新 Claim 返回 COLLISION。
- 成功迁移保留原持久 StableClaimId，同时记录当前生成 ID、旧/新位置、方法、分数和正面证据。
- 普通插行、轻微非数字编辑、数字变化和唯一高置信文件重命名已覆盖；重复段落和复合低置信场景明确拒绝自动选择。
- prepare_claim_identities 复用同一个 PaperScanResult，不重新读取 LaTeX。

## 阶段 5B 已实现

- `ProjectConfiguration.claim_registry_path` 默认为 `.metricproof/claims.yml`；仅接受项目相对 POSIX `.yml` / `.yaml` 精确路径，不接受 glob、绝对路径、反斜杠或 `..`。
- `ClaimRegistry` 使用 schema version `1`，按 Claim ID 稳定排序并拒绝重复 ID；每项必须恰好保存一个 link 或 ignore 决策。
- Registry 状态包括 active、ignored、broken、ambiguous 与 missing；broken 记录必须保留原链接，不能静默删除来源失效的用户决策。
- `MetricReference` 显式保存项目相对结果文件、run、metric、selector 和受控 scale；scale 仅允许 identity、fraction_to_percent、percent_to_fraction。
- `DirectLink` 保存确认时的完整 SHA-256 Claim 指纹和可选绝对/相对 Decimal 容差覆盖。
- `DerivedLink` 仅允许单层 subtraction、relative_change、mean、standard_deviation；操作数具名且稳定排序，标准差必须显式声明 sample/population。
- 派生链接显式保存输出单位、输出缩放和可选 HALF_UP 小数位策略；不接受表达式、代码字符串、嵌套操作或任意函数。
- IgnoreRecord 使用受控原因枚举；RegistryMigrationRecord 保存迁移状态、方法、分数、旧/新路径、证据和冲突。
- `ClaimRegistryRepository` 隔离应用服务与 YAML/文件系统；load/save/save_entry 服务不实例化具体适配器。
- `YamlClaimRegistryRepository` 使用安全单文档 YAML、Pydantic strict/extra-forbid 模型和完整领域校验；未知字段、危险对象标签、错误类型、不兼容 schema、非法 Decimal 和碰撞均受控失败。
- 保存采用同目录临时文件、flush、fsync 和 `os.replace`；替换失败保留旧 registry 并清理临时文件。
- 空 registry 路径不存在时按空集合读取，不自动创建目录；保存要求项目内父目录已存在，所有持久位置只保存项目相对路径。

## 阶段 5C 已实现

- 纯领域匹配器只消费 `IdentifiedClaim`、已加载 `ExperimentCatalog` 和严格别名，不读取文件、不写 Registry，也不依赖 CLI 或具体适配器。
- `CandidateMatch` 保存 0–100 总分、每项正负贡献、建议 scale、建议 direct/derived 类型和排序后的不确定性；总分必须等于分项贡献的有界和。
- Direct 候选综合 Decimal 数值/显示精度、显式 fraction/percent 转换、metric name/alias、run、dataset、split 和 Claim kind；数值相同只是一项证据。
- 同分或领先不足 8 分显式标记 ambiguous，永不自动确认；无候选保留未链接并允许人工选择任意已加载 run/metric。
- 清晰 Derived 候选支持 subtraction、relative_change 和 mean；percentage points 与相对百分比使用不同 operation/output unit/scale。
- `mean ± std` 可用多 observation 的 mean 建议，并用 sample/population std 匹配作为复核证据；当前链接目标只覆盖 mean，± 分量保留明确 MVP limitation。
- 派生搜索按 metric 一次分组，仅在清晰 derived 上下文运行；单指标超过 200 observations 时跳过组合搜索，避免无界二次扩展。
- `build_link_session` 在同一扫描上执行身份迁移，合并 active/ignored/broken/ambiguous/missing/unlinked 状态，并检查持久 Link 的所有来源是否仍存在。
- `metricproof link`、`--claim`、`--non-interactive`、`--json`、`--show-broken` 已实现；JSON 和非交互模式只输出建议，绝不提示或写文件。
- 交互模式支持选择建议、确认 scale、手工选择 observation、IGNORE、skip 和 cancel；active Link 更新前单独确认，全部决定在内存聚合后只原子保存一次。
- Ctrl+C、quit、最终取消、无决定或错误均不修改 claims.yml；scan 仍保持只读。
- 插入前置文本后，既有 Link 通过确定性迁移继续映射到原持久 Claim ID，不创建重复 unlinked Claim。

## 阶段 5D/5E 已实现

- `STALE_VALUE` 对 active DirectLink 使用 Decimal、显式 scale、全局/指标/Link 容差与半开显示精度区间；一致及舍入可接受值保持安静，来源失效先形成 link diagnostic。
- `WRONG_DELTA` 只计算受控单层 subtraction、relative_change、mean、sample/population standard_deviation；百分点、比例差和相对百分比严格区分，rounding 明确。
- `MISSING_PROVENANCE` 默认只报告当前可定位 LIKELY Claim；POSSIBLE 仅在显式 policy 开启时包含，ignored、active、broken、ambiguous/missing 历史记录不重复报告。
- `CheckDiagnostic` 与 `CheckResult` schema `1` 是终端/JSON 的唯一事实来源；稳定 ID、排序、完整 evidence、observed/expected、confidence、uncertainties 与 remediation 均由领域/应用事实构建。
- `check_project` 复用一个 PaperScanResult、一个 ExperimentCatalog 和一个 LinkSession，不在规则中读文件，不按 Claim 重载实验数据。
- `metricproof check` 支持 `--json`、三个 `--rule` 选择和 `--fail-on warning|error`；规则阈值退出 `1`，配置/输入/链接阻断不受 fail-on 掩盖并退出 `2`/`3`。
- 数值容差、POSSIBLE provenance policy、缺失来源严重程度和默认 fail-on 由严格配置解析；未知或非法值受控失败。
- 迁移在原有分数/安全 margin 上仅用 semantic digest 作为唯一近似同分 tie-break 证据；它不提高最低阈值，相同数值的重复候选仍拒绝自动选择。
- `examples/mvp-demo` 包含 6 个当前 Claim：4 active、1 ignored、1 unlinked；两个一致反例保持安静，三条规则各产生一条预期诊断。
- 演示副本在论文前插文本后 5 条持久决定全部迁移，无 duplicate/unlinked 新记录；原演示输入保持只读。
- `docs/linking-and-checking.md`、README、SPEC、ARCHITECTURE、data model 与 rule semantics 已同步当前三规则边界。
## 阶段 4A、4B1 与 4B2a 已实现

- `paper_paths` 保存严格、排序后的精确 `.tex` 入口；不接受 glob，也允许只配置论文扫描的项目。
- 静态解析相对 `\input{}` / `\include{}`，支持省略 `.tex`，检测缺失文件、循环、动态参数和路径逃逸。
- 每个物理文件只扫描一次；候选保留所有可达入口和规范 include 链。
- 注释、`\verb`、`verbatim`、`Verbatim`、`lstlisting` 与 `minted` 内容不产生候选。
- 识别整数、小数、前导点小数、正负号、科学计数法、普通/转义百分数和基础 `mean ± std`。
- 数值直接解析为有限 `Decimal`，保存原文、规范值、单位、类型、显示精度和符号。
- 候选保存项目相对文件、行列、字符范围、有限前后文、环境栈、最近命令、语法上下文和入口 provenance。
- 语法上下文区分正文、数学、命令参数、表格环境、caption 和 unknown；基础表格结构在同一已读取源码和等长遮罩上继续解析。
- 新增 `PaperScanner` 端口、`scan_paper` 应用服务与 `LocalLatexPaperScanner` 适配器。
- `metricproof scan` 支持 `--json`、`--show-claims`、`--show-all`、`--show-tables` 和 `--file`；scan JSON 显式升级为 schema version `3`。
- `--file` 只能过滤已构建依赖图中的真实文件，不能读取图外任意路径。
- 缺失 include 等可恢复问题保留其他结果并形成结构化诊断；阻断输入退出码为 `3`。
- 扫描只读，不执行 TeX、宏、代码环境、用户脚本或表达式，不修改论文文件。
- 支持可选 `table` / `table*` 容器、独立 `tabular` / `tabular*`，以及同一容器中的多个 tabular。
- 表格状态机只把当前层级未转义 `&`、顶层 `\\` 与 `\tabularnewline` 作为分隔符；尊重花括号、数学、嵌套环境、注释、代码环境、空单元格和无终止符最后一行。
- 保存 caption/label、基础列规格与可用 expected column count、行/单元格精确范围、逻辑列起点/span、结构命令和受控规范文本。
- 基础 `\multicolumn{N}{FORMAT}{CONTENT}` 参与逻辑列计算；`multirow` 明确产生 limitation 并降级，不复制跨行内容。
- 单元格通过文件与字符范围直接引用既有 `RawNumericCandidate`；`\textbf` / `\underline` 精确关联到具体候选，可表达嵌套和同一单元格内不同格式。
- `parsed`、`degraded`、`unsupported` 可靠性和统计进入 `PaperScanResult`；`longtable`、`tabularx`、`array`、`matrix`、`aligned` 明确认定 unsupported。
- 每个 `RawNumericCandidate` 恰好生成一个非持久 `ClaimCandidateClassification`，包含 disposition、kind、0–100 分数、置信等级、复核建议和证据。
- 小型内置指标词表可由严格 `metric_aliases` 扩展；权重与阈值集中在领域模块，不提供插件、代码或任意权重配置。
- 引用/结构/排版/URL/版本/日期/颜色上下文提供强负面证据；实验数量保留为 possible/ambiguous，`mean ± std` 保持复合分类。
- 表格候选索引一次构建；`parsed`、`degraded`、`unsupported` 使用不同证据强度，不重新读取或解析 LaTeX。
- 分类是可人工复核的启发式结果；`LIKELY` 不等于已确认论文结论，`NON_EXPERIMENT` 也可能存在极端误分。

阶段 3 的严格配置和 JSON/YAML/CSV 实验结果读取能力保持兼容。

## 集中资源限制

- 单文件最大 5,000,000 bytes。
- LaTeX 图最大总字节数 25,000,000。
- 最大 LaTeX 文件数 1,000。
- 最大 include 深度 32。
- 最大 LaTeX 环境深度 128。
- 最大原始数值候选数 100,000。
- 最大表格数 1,000；单表最大 10,000 行。
- 单行最大 1,000 个物理单元格；单表最大 100,000 个单元格。
- 单元格最大 100,000 字符；表格嵌套深度最大 16。
- `multicolumn` span 最大 1,000。
- JSON/YAML 最大嵌套深度 64。
- 最大实验结果来源数 1,000。
- 单 CSV 最大数据行数 100,000。

这些是集中定义的内置常量；配置中的未来 `limits` 字段当前不改变读取边界。

## 当前测试证据

在 Python 3.13.9 下，阶段 5 最终验证结果：

- 修改前基线：247 passed，2 skipped；90.26% branch coverage。
- 阶段 5A：270 passed，2 skipped；90.70% branch coverage。
- 阶段 5B：310 passed，2 skipped；91.20% branch coverage。
- 阶段 5C：330 passed，2 skipped；90.41% branch coverage。
- 最终 `python -m pytest`：退出码 0，372 passed、2 skipped；两个 skip 仅为当前 Windows 账户无法创建符号链接。
- 最终 `python -m pytest --cov=metricproof --cov-report=term-missing`：退出码 0，372 passed、2 skipped，90.22% branch coverage。
- `python --version`：退出码 0，Python 3.13.9。
- `python -m ruff check .`：退出码 0，All checks passed。
- `python -m ruff format --check .`：退出码 0，74 files already formatted。
- `pyright` strict：退出码 0，0 errors、0 warnings、0 informations。
- `python -m compileall -q src`：退出码 0。
- `python -m build`：退出码 0，生成 `metricproof-0.1.0.dev0.tar.gz` 与 `metricproof-0.1.0.dev0-py3-none-any.whl`。
- `metricproof --help`、`metricproof link --help`、`metricproof check --help`、`python -m metricproof link --help`、`python -m metricproof check --help`：均退出码 0，入口一致。
- `metricproof doctor`：退出码 0，4 PASS、1 WARN；WARN 仅为仓库根没有 `.metricproof`，演示配置位于子目录。
- demo `metricproof experiments validate`：退出码 0，2 runs、6 observations、0 diagnostics。
- demo `metricproof scan --show-claims`：退出码 0，1 file、6 candidates、4 likely、2 possible、0 diagnostics。
- demo `metricproof link --non-interactive --json`：退出码 0，schema `1`、4 active、1 ignored、1 unlinked、`write_performed=false`；四个输入哈希不变。
- demo `metricproof check`：预期退出码 1，6 current Claims、3 diagnostics。
- demo `metricproof check --json`：连续两次均预期退出码 1；schema `1`，依次为 `STALE_VALUE`、`WRONG_DELTA`、`MISSING_PROVENANCE`，JSON 字节稳定，四个输入哈希不变。
- 交互 CLI 自动测试实际覆盖首次 DirectLink/DerivedLink/Ignore 写入、单次原子保存、再次运行不重复、取消不写、前插迁移和输入文件不变。
- 演示副本前插文本回归：5 条持久决定全部 `migrated`，仍为 4 active、1 ignored、1 unlinked，无 ambiguous/missing link diagnostic。
- 生成式/规模测试累计覆盖 1,000 个数值词法、200 组注释遮罩、5,000 个表格候选、200 个普通前插迁移、200 个 Registry 条目和 200 个唯一 metric 匹配，超过 1,000 个有意义生成案例。
- 安全/边界扫描未发现 domain 反向依赖、`eval`、`exec`、`shell=True`、联网客户端、HTML/SARIF/GitHub Actions 或两条后续规则实现；测试只验证后续 rule code 被 CLI 拒绝。
- 沙箱内 pytest/build 无法创建系统临时目录；获准在同一 Python 3.13.9 环境沙箱外完成真实执行，不属于代码缺陷。
- `git diff --check`：退出码 0；仅报告 Git 的 LF→CRLF 工作树提示，无空白错误。
### 阶段 4B1 历史测试证据

在 Python 3.13.9 下，阶段 4B1 自动验证结果：

- `python --version`：Python 3.13.9。
- `python -m pytest`：220 passed，2 skipped。
- `python -m pytest --cov=metricproof --cov-report=term-missing`：220 passed，2 skipped，90.07% coverage。
- 两个跳过项仅为当前 Windows 账户无法创建测试符号链接；路径逃逸拒绝逻辑仍有其他边界测试覆盖。
- `python -m ruff check .`：通过。
- `python -m ruff format --check .`：42 files already formatted。
- `pyright` strict：0 errors、0 warnings、0 informations。
- `python -m compileall -q src`：通过。
- `python -m build`：成功生成 sdist 与 wheel。
- `metricproof --help`：退出码 0，显示 `doctor`、`scan` 与 `experiments`。
- `metricproof doctor`：4 PASS、1 WARN，退出码 0；WARN 为仓库根目录没有 `.metricproof`。
- `metricproof experiments validate`：验收项目 1 run、1 observation、0 diagnostic，退出码 0。
- `metricproof scan --help` 与 `python -m metricproof scan --help`：退出码 0。
- 一次性阶段 4B1 验收项目 `metricproof scan`：3 个 LaTeX 文件、14 个原始候选、5 张表（2 parsed、3 degraded）、3 个 limitation/warning、退出码 0。
- 同一项目 `metricproof scan --show-tables`：显示 caption/label、行/逻辑列、候选格式，以及 multirow、列数不匹配、未闭合 tabular 的明确原因，退出码 0。
- 同一项目 `metricproof scan --json`：schema `2`、`paper_scan`、稳定纯 JSON，表格与候选关联可解析，退出码 0。
- 同一项目 `metricproof experiments validate`：1 run、1 observation、0 diagnostic，退出码 0。
- Windows 真实目录联接逃逸验收：只保留入口文件中的 1 个候选，报告 `MPE_LATEX_PATH_ESCAPE`，退出码 3；验收后仅移除本次创建的联接，外部目标文件保持存在。
- `git diff --check`：通过。
- 生成式测试覆盖 1,000 个数值词法和 200 组注释转义奇偶。
- 阶段 4A 合成性能测试覆盖约 5,000 个候选并约束线性扩展趋势。
- 阶段 4B1 生成式测试覆盖 50 张表、1,000 行、5,000 个单元格；5,000 个表格候选均复用既有对象，测试用例约 0.60 秒。
- 安全扫描未发现 `eval`、`exec`、`shell=True`、TeX 执行、联网或远程资源操作。

阶段 4B1 验收项目包含基础 table/tabular、独立 tabular、caption/label、textbf、underline、
multicolumn、multirow limitation、booktabs、列数不匹配、未闭合 tabular 和 include 文件内表格。

## 当前尚未实现

- 表头角色、指标/模型/数据集推断、higher/lower-is-better、粗体最优值和下划线次优值判断。
- `WRONG_BEST_MARK`、`UNFAIR_COMPARISON`。
- HTML 报告、Git evidence chain、GitHub Actions、SARIF。
- `init` / `report` 命令、PDF/Word/Overleaf、远程资源、数据库、Web、插件、AI/LLM 或自动论文修复。

## 下一阶段可依赖的稳定接口

阶段 1 接口继续稳定：

- `metricproof.__version__`
- `metricproof.cli.main:app`
- `ExitCode`、`MetricProofError`
- `DoctorProbe`、`run_doctor`
- `DoctorCheck`、`DoctorReport`、`GitInspection`、`LatexDiscovery`
- `LocalDoctorProbe`

阶段 3 稳定边界：

- `SourceLocation`、`NumericValue`、`MetricObservation`、`ExperimentRun`、`Evidence`、`InputDiagnostic`、`ExperimentCatalog`
- `ExperimentFormat`、`StructuredSourceOptions`、`CsvSourceOptions`、`ExperimentSource`、`ProjectConfiguration`
- `ConfigurationRepository`、`ExperimentSourceReader`、`SourceReadResult`
- `load_experiments`
- `YamlConfigurationRepository`、`LocalExperimentSourceReader`
- `metricproof experiments list`、`metricproof experiments validate`

阶段 4A/4B1 新增稳定边界：

- `NumericKind`、`NumericUnit`
- `LatexSyntacticContext`、`NumericCandidateKind`、`RawNumericCandidate`
- `LatexSourceDocument`、`LatexIncludeEdge`、`LatexSourceGraph`
- `LatexTableKind`、`LatexTableReliability`、`LatexFormattingKind`、`LatexTableStructureKind`
- `LatexTableText`、`LatexColumnSpec`、`LatexCellFormatting`、`LatexCellNumericReference`
- `LatexTableStructureMarker`、`LatexTableCell`、`LatexTableRow`、`LatexTable`
- `PaperScanStatistics`、`PaperScanResult`
- `PaperScanner`、`scan_paper`、`LocalLatexPaperScanner`
- `metricproof scan`

阶段 4B2a 新增稳定边界：

- `ClaimDisposition`、`ClaimKind`、`ClaimConfidence`、`EvidenceDirection`
- `ClaimEvidence`、`ClaimCandidateClassification`、`ClaimClassificationStatistics`、`ClaimClassificationResult`
- `classify_raw_candidates`、`classify_claim_candidates`
- 严格、排序后的 `ProjectConfiguration.metric_aliases`
- `metricproof scan --show-claims`、`metricproof scan --show-all`、paper scan JSON schema `3`

下一阶段继续消费这些分类和现有 PaperScanResult，不得重新读取论文或提前实现表头/最佳值语义。

阶段 5A 新增稳定边界：

- StableClaimId、ClaimContext、ClaimFingerprint、IdentifiedClaim
- ClaimIdentityCollision、ClaimIdentityResult、ClaimIdentitySnapshot
- ClaimMigrationStatus、ClaimMigrationMethod、ClaimMigrationResult
- identify_claims、migrate_claims、identified_claim_sort_key
- PreparedClaimIdentities、prepare_claim_identities

阶段 5B 新增稳定边界：

- `LinkScale`、`NumericTolerance`、`MetricReference`、`DirectLink`
- `DerivedOperation`、`DerivedOperand`、`DerivedLink`、`StandardDeviationMode`、`RoundingPolicy`
- `ClaimRegistryStatus`、`IgnoreReason`、`IgnoreRecord`、`RegistryMigrationRecord`
- `ClaimRegistryEntry`、`ClaimRegistry`
- `ClaimRegistryRepository`、`load_claim_registry`、`save_claim_registry`、`save_claim_registry_entry`
- `YamlClaimRegistryRepository`
- 严格的 `ProjectConfiguration.claim_registry_path`

阶段 5C 新增稳定边界：

- `MatchFeature`、`CandidateMatch`、`ClaimMatchResult`、`LinkSuggestionType`
- `suggest_claim_matches`、`suggest_all_claim_matches`
- `suggest_links_for_claim`、`suggest_links`
- `LinkReviewStatus`、`LinkReviewItem`、`LinkSession`、`build_link_session`
- `entry_from_candidate`、`entry_from_observation`、`ignored_entry`
- `metricproof link` 及 schema version `1` link suggestion JSON

阶段 5D 新增稳定边界：

- `RulePolicy`、严格 numeric tolerances 与 check policy
- `CheckDiagnosticKind`、`CheckDiagnostic`、`CheckSummary`、`CheckResult`
- `make_check_diagnostic`、`make_check_evidence`、`check_diagnostic_sort_key`
- `NumericComparison`、`DerivedCalculation`、`DerivedCalculationError`
- `check_stale_value`、`calculate_derived`、`check_wrong_delta`、`check_missing_provenance`
- `CORE_RULE_CODES`、`check_project`
- `metricproof check` 及 CheckResult JSON schema version `1`
