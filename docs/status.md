# MetricProof 项目状态

更新日期：2026-07-18

## 当前阶段

阶段 6：五条本地规则、统一 CheckResult、单文件离线 HTML、完整虚构 Demo 与 README 展示已实现。

MetricProof 仍是开源、本地优先的 Python 3.13 CLI。诊断只表示可复核的一致性问题或启发式风险，不裁定论文正确性、科研不端或科学结论。

## 已实现事实

### 五条规则

- `STALE_VALUE`：active DirectLink 按显式 scale、Decimal 容差和显示精度区间复核当前 observation。
- `WRONG_DELTA`：重算受控单层 subtraction、relative_change、mean、sample/population standard_deviation，严格区分比例、百分比和百分点。
- `MISSING_PROVENANCE`：报告当前可定位、未 active/ignored 的实验 Claim；possible 是否包含由严格 policy 控制。
- `WRONG_BEST_MARK`：消费一次扫描得到的 parsed `LatexTable` 与显式 `table_checks`；按 higher/lower、Decimal tie tolerance、best 格式与可选 second-best 格式逐单元格诊断。
- `UNFAIR_COMPARISON`：只比较 comparison 声明的 run 和 `controlled_keys`；类型/值严格，数值容差显式，允许差异必须带非空理由。

规则只消费已准备领域对象，不读取文件、实例化适配器或渲染报告。规则消息保持审慎，不宣称科学错误或已证明比较不公平。

### 安全配置快照

- `ExperimentConfigReader` 端口隔离应用层与本地 JSON/YAML 适配器。
- 只加载 comparisons 实际需要的 run 与 dot-path key，不把整份配置传入规则。
- JSON/YAML 使用严格、安全、单文档解析；拒绝重复 key、非有限数、危险 tag、多文档、非字符串 mapping key、递归结构、超深/超大输入。
- 数值保持 lexical `Decimal`；null、boolean、number、string、list、mapping 使用显式不可变 `ConfigValue`。
- 缺 run/config、双方缺 key、一侧缺 key与类型差异都形成结构化、可定位证据。

### CheckResult、终端与报告

- CheckResult schema version `2` 是终端、JSON 和 HTML 的唯一事实来源。
- `RuleExecutionSummary` 对每条规则保存 executed/skipped、skip reason、info/warning/error 和 limitation 数。
- Terminal 首屏显示五规则执行摘要；JSON/HTML 使用相同摘要与诊断。
- Diagnostic 稳定 ID 纳入 subject；排序不依赖当前时间、随机 UUID 或遍历偶然顺序。
- `metricproof report --format html|json --output PATH [--no-timestamp]` 已实现。
- HTML 是单文件 UTF-8、内联 CSS、无 JavaScript、无外部资源；所有用户文本转义。
- 输出路径必须保持在项目根目录内；写入使用同目录临时文件、flush/fsync 与原子替换。
- 合法报告先写入，再按同一 rule threshold 返回 0/1；blocking input 返回 3，配置/路径错误返回 2。
- `--no-timestamp` 对未变输入产生字节稳定输出。

### Demo 与 README

- `examples/mvp-demo` 有 3 runs、12 observations、12 current Claims、10 active、1 ignored、1 unlinked。
- 五条规则均有稳定正例：1 STALE_VALUE、1 WRONG_DELTA、1 MISSING_PROVENANCE、2 WRONG_BEST_MARK、2 UNFAIR_COMPARISON。
- 一致 direct/derived link、正确 best mark、带理由的 method.name allowed difference、fraction/percent scale 与 ignore 决策保持安静。
- `.metricproof/config.yml` 显式声明 metric direction、table check、comparison、controlled keys 和 allowed reason。
- `run-demo.ps1` / `run-demo.sh` 只调用公开 CLI，验证预期退出码 1，继续生成报告，最后保留 1；不修改输入。
- README 已重写为项目首页，包含真实 Demo CheckResult 生成的视觉图、五分钟复现、五规则表、配置示例、安全边界与非目标。

## 受控降级与非目标

`WRONG_BEST_MARK` 不猜测表头、指标方向、行范围或格式约定。缺失值跳过；mean ± std 使用主值；未知宏、多值/spanning cell、multirow、degraded/unsupported 结构形成 limitation。`UNFAIR_COMPARISON` 不推断哪些字段应该受控，也无法发现未记录环境差异；配置相同不证明比较科学公平。

Git evidence chain、GitHub Actions、SARIF、PDF/Word/Overleaf、远程资源、Web UI、数据库、插件、AI/LLM、实验执行、TeX 编译和自动论文修复仍未实现，也不属于本阶段。

## 当前验证证据

环境：Windows，Python 3.13.9。

- 修改前基线：`python -m pytest` 372 passed、2 skipped；分支覆盖率 90.22%；Ruff、format、Pyright strict 与 build 通过。
- 最终 `python -m pytest --cov=metricproof --cov-report=term-missing`：退出码 0；410 passed、2 skipped；90.41% branch coverage。
- 两个 skip 均为当前 Windows 账户无法创建测试符号链接；路径逃逸另有非 symlink 边界测试。
- Stage 6 定向：38 passed；`stage6` + `experiment_configs` 模块定向合计 96.17%。
- `python -m ruff check .`：退出码 0；`python -m ruff format --check .`：退出码 0，79 files。
- `pyright` strict：退出码 0，0 errors / warnings / informations。
- `python -m compileall -q src`：退出码 0。
- `python -m build`：退出码 0，成功生成 `metricproof-0.1.0.dev0.tar.gz` 与 `metricproof-0.1.0.dev0-py3-none-any.whl`。
- 最终 CLI 清单实跑：help/doctor/validate/scan/link 为 0；full check/JSON/HTML report/JSON report 为预期 1；两条 warning-only 单规则命令为 0。
- terminal/JSON/HTML 均为 7 diagnostics、五类 code；报告无 script/外部资源，JSON 可解析，输入哈希 0 变化，README 经 `git ls-files` 确认为 tracked。
- HTML 自动化覆盖恶意文本转义、clear result、limitation、missing evidence、nested output、路径逃逸、原子替换、稳定输出和 JSON 一致性。
- `run-demo.ps1` 实跑并生成报告后返回预期 1；`run-demo.sh` 在本 Windows 环境只检查了脚本语义。
- 合成规则规模：50 tables + 50 comparisons，生成 300 table 与 50 comparison diagnostics，pytest call 约 0.02s，并强制小于 2s。
- 合成报告：500 diagnostics 当前约 0.0105s、509,191 bytes；仅证明本地样例无明显退化，不作通用性能承诺。

## Chrome 视觉验收边界

Chrome 连接器已启动并读取安全、API、Playwright 与截图指南，但 URL policy 拒绝本地 `file://` 报告并禁止间接浏览器绕过。因此本轮不把“Chrome 视觉验收”声明为已通过。README 视觉图来自真实 Demo JSON 的本地确定性渲染，不是伪造的 HTML 浏览器截图。

## 稳定接口

- `MetricDirection`、`TableMetricSpec`、`TableCheckSpec`、`ConfigValueKind`、`ConfigValue`、`ExperimentConfigSnapshot`、`ComparisonSpec`。
- `check_wrong_best_mark`、`check_unfair_comparison`。
- `ExperimentConfigReader`、`ConfigSnapshotReadResult`、`load_comparison_snapshots`、`LocalExperimentConfigReader`。
- `RuleExecutionSummary`、CheckResult/JSON schema version `2` 与五规则 `CORE_RULE_CODES`。
- `render_html_report`、`render_json_report`、`write_report`。
- `metricproof check`、`metricproof report`、`python -m metricproof report`。

没有执行 commit、push、远程仓库创建或发布。下一阶段不得把 Git/CI/SARIF 或其他产品范围提前塞入当前实现。