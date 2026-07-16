# MetricProof 项目状态

更新日期：2026-07-16

## 当前阶段

阶段 3：严格项目配置、实验领域模型，以及 JSON、YAML、CSV 实验结果读取。

状态：阶段 3 已完成实现、自动测试、命令级验收和完成标准审计。当前正式运行基线为 Python `>=3.13,<4.0`；目标附件中残留的 Python 3.12 描述已由后续用户决策和仓库正式文档更新为 3.13。

## 本阶段已实现

- 严格、安全读取项目根目录 `.metricproof/config.yml`，要求 `schema_version: "1"`。
- Pydantic 配置模型默认拒绝顶级和嵌套未知字段，YAML 使用安全 loader 并检测重复 key。
- `result_paths` 支持项目相对精确路径和 glob，稳定展开 JSON/YAML/CSV 来源。
- 所有配置路径检查绝对路径、`..`、不存在文件、重复路径别名和符号链接逃逸。
- JSON/YAML 通过 `structured.metrics` 与 `structured.metadata` 显式声明 selector。
- JSON/YAML 单 run 支持固定 `run_id` 或 `run_id_selector`；多 run 数组必须显式配置 `records_selector` 和 `run_id_selector`。
- CSV 必须声明 `run_id_column`、`metric_columns`、`metadata_columns`，使用标准库 `csv`。
- 建立 `SourceLocation`、`NumericValue`、`MetricObservation`、`ExperimentRun`、`Evidence`、`InputDiagnostic` 和 `ExperimentCatalog`。
- 指标使用有限 `Decimal`；JSON/YAML 保留数字词法文本，CSV 直接从字符串解析，不经过二进制 `float`。
- 布尔、空字符串、`NaN` 和 Infinity 均不会成为合法 Observation。
- JSON/YAML 检测重复 key、语法错误、selector 错误、非显式数组、递归结构和最大深度。
- CSV 检测缺失/重复表头、缺列、行宽、缺失/重复 run ID、空/非法数值和最大行数。
- 多来源按稳定顺序读取；同一 run 可合并不同指标，重复 metric、元数据和配置引用冲突形成阻断诊断。
- 实现 `ConfigurationRepository`、`ExperimentSourceReader`、`SourceReadResult` 和 `load_experiments` 应用边界。
- 增加 `metricproof experiments list` / `validate` 及 `--json`，机器输出稳定纯净。
- CLI 保持展示与应用/领域逻辑分离，输入错误不显示 traceback，也不修改输入文件。

## 集中资源限制

- 单文件最大 5,000,000 bytes。
- JSON/YAML 最大嵌套深度 64。
- 最大实验结果来源数 1,000。
- 单 CSV 最大数据行数 100,000。

这些是阶段 3 有文档的内置常量；配置中的未来 `limits` 字段当前不改变这些读取边界。

## 当前测试证据

在 Python 3.13.9 下，阶段 3 扩展后：

- `python --version`：Python 3.13.9。
- `python -m pytest`：121 passed，1 skipped。
- `python -m pytest --cov=metricproof --cov-report=term-missing`：121 passed，1 skipped，92.84% branch coverage。
- 跳过项仅为当前 Windows 账户无创建符号链接权限；另以真实 Windows 目录联接验证了链接逃逸被拒绝，CLI 返回配置错误退出码 2。
- `python -m ruff check .`：通过。
- `python -m ruff format --check .`：31 files already formatted。
- `pyright` strict：0 errors、0 warnings、0 informations。
- `python -m compileall -q src`：通过。
- `python -m build`：成功生成 sdist 与 wheel；首次受限沙箱临时目录失败后，同一命令在正常临时目录权限下通过。
- `metricproof --help`：通过，显示 `doctor` 与 `experiments`。
- `metricproof --version`：`MetricProof 0.1.0.dev0`。
- `metricproof doctor`：3 PASS、2 WARN，退出码 0。
- `metricproof experiments --help` 与 `python -m metricproof experiments --help`：通过。
- 临时 JSON/YAML/CSV 项目执行 `metricproof experiments list`：稳定列出 4 个 run。
- 同一项目执行 `metricproof experiments validate`：4 run、4 observation、0 diagnostic，退出码 0。
- 同一项目执行 `metricproof experiments list --json`：输出可解析、稳定且无附加日志的 JSON。
- `git diff --check`：通过。
- 安全扫描未发现代码中的 `eval`、`exec`、`shell=True`、pandas、联网或远程资源操作。

验证中的沙箱临时目录权限失败均已使用相同命令在正常临时目录权限下复验；它们不是产品断言失败。除账户权限导致的符号链接测试跳过外，没有未通过的项目级检查。

## 当前尚未实现

- LaTeX 文件内容解析、Claim 和表格提取。
- `metricproof scan`、Claim ID、Claim-to-Metric 链接和 `claims.yml`。
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

阶段 3 新增稳定边界：

- `SourceLocation`、`NumericValue`、`MetricObservation`、`ExperimentRun`、`Evidence`、`InputDiagnostic`、`ExperimentCatalog`
- `ExperimentFormat`、`StructuredSourceOptions`、`CsvSourceOptions`、`ExperimentSource`、`ProjectConfiguration`
- `ConfigurationRepository`、`ExperimentSourceReader`、`SourceReadResult`
- `load_experiments`
- `YamlConfigurationRepository`、`LocalExperimentSourceReader`
- `metricproof experiments list`、`metricproof experiments validate`

下一阶段必须消费这些领域对象和应用端口，不得让 LaTeX、Claim 或规则逻辑直接读取任意实验文件或进入 CLI。
