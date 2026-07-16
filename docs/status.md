# MetricProof 项目状态

更新日期：2026-07-16

## 当前阶段

阶段 4B1：基础 LaTeX table/tabular 结构、单元格定位、候选关联与格式标记。

状态：实现、自动测试、命令级验收和完成标准审计均已完成。正式运行基线为 Python `>=3.13,<4.0`。

## 阶段 4A 与 4B1 已实现

- `paper_paths` 保存严格、排序后的精确 `.tex` 入口；不接受 glob，也允许只配置论文扫描的项目。
- 静态解析相对 `\input{}` / `\include{}`，支持省略 `.tex`，检测缺失文件、循环、动态参数和路径逃逸。
- 每个物理文件只扫描一次；候选保留所有可达入口和规范 include 链。
- 注释、`\verb`、`verbatim`、`Verbatim`、`lstlisting` 与 `minted` 内容不产生候选。
- 识别整数、小数、前导点小数、正负号、科学计数法、普通/转义百分数和基础 `mean ± std`。
- 数值直接解析为有限 `Decimal`，保存原文、规范值、单位、类型、显示精度和符号。
- 候选保存项目相对文件、行列、字符范围、有限前后文、环境栈、最近命令、语法上下文和入口 provenance。
- 语法上下文区分正文、数学、命令参数、表格环境、caption 和 unknown；基础表格结构在同一已读取源码和等长遮罩上继续解析。
- 新增 `PaperScanner` 端口、`scan_paper` 应用服务与 `LocalLatexPaperScanner` 适配器。
- `metricproof scan` 支持 `--json`、`--show-all`、`--show-tables` 和 `--file`；scan JSON 显式升级为 schema version `2`。
- `--file` 只能过滤已构建依赖图中的真实文件，不能读取图外任意路径。
- 缺失 include 等可恢复问题保留其他结果并形成结构化诊断；阻断输入退出码为 `3`。
- 扫描只读，不执行 TeX、宏、代码环境、用户脚本或表达式，不修改论文文件。
- 支持可选 `table` / `table*` 容器、独立 `tabular` / `tabular*`，以及同一容器中的多个 tabular。
- 表格状态机只把当前层级未转义 `&`、顶层 `\\` 与 `\tabularnewline` 作为分隔符；尊重花括号、数学、嵌套环境、注释、代码环境、空单元格和无终止符最后一行。
- 保存 caption/label、基础列规格与可用 expected column count、行/单元格精确范围、逻辑列起点/span、结构命令和受控规范文本。
- 基础 `\multicolumn{N}{FORMAT}{CONTENT}` 参与逻辑列计算；`multirow` 明确产生 limitation 并降级，不复制跨行内容。
- 单元格通过文件与字符范围直接引用既有 `RawNumericCandidate`；`\textbf` / `\underline` 精确关联到具体候选，可表达嵌套和同一单元格内不同格式。
- `parsed`、`degraded`、`unsupported` 可靠性和统计进入 `PaperScanResult`；`longtable`、`tabularx`、`array`、`matrix`、`aligned` 明确认定 unsupported。

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

- `PaperClaim`、Claim 分类、Claim ID、迁移、Claim-to-Metric 链接和 `claims.yml`。
- 表头角色、指标/模型/数据集推断、higher/lower-is-better、粗体最优值和下划线次优值判断。
- `STALE_VALUE`、`WRONG_DELTA`、`MISSING_PROVENANCE`、`WRONG_BEST_MARK`、`UNFAIR_COMPARISON`。
- 完整 `check`、正式检查结果 JSON 和 HTML 报告。
- Git 实验证据读取、GitHub Actions、远程资源、数据库、Web 或插件系统。

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

下一阶段必须消费这些原始候选、`PaperScanResult.tables` 和应用端口；不得让 Claim、表头/最佳值语义或规则逻辑直接读取任意文件或进入 CLI。
