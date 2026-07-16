# MetricProof 设计发现

## 当前项目现状

- 项目根目录为 `D:\Programming\python\metricproof`。
- 初次检查时 `main.py` 为 0 字节，随后 PyCharm 生成了默认示例内容；该文件未被本设计任务修改。
- 当前目录不是 Git 仓库。
- 没有已有规格、架构、依赖配置或业务代码需要兼容。

## 设计重点

- MetricProof 的核心差异是把论文中的数值 Claim 与实验指标、实验配置和 Git 状态连接成可审计证据链。
- 首版应采用显式配置与用户确认，避免把模糊匹配误写成事实。
- `MISSING_PROVENANCE` 的适用范围必须限于被分类为实验结论且未被忽略的候选数字。
- `UNFAIR_COMPARISON` 只能检查用户声明为受控的配置字段，并使用风险措辞。
- `WRONG_BEST_MARK` 在缺少指标优化方向或表格结构不可靠时必须受控降级。
- LaTeX 首版需要支持常见正文数字、基础表格和相对 `\input`/`\include`，但不承诺完整 TeX 宏展开。

## 需要在正式文档中保持一致的术语

- Claim：论文源码中被识别为候选实验结论的数值表达。
- Observation：从实验结果文件归一化得到的一次指标观测。
- Link：Claim 与直接或派生实验来源之间的用户确认映射。
- Evidence：诊断所依据的可定位事实。
- Diagnostic：规则产生的可审计结果，不等于已确认学术错误。


## 2026-07-16 阶段 1 初始审计

- 目标文件已按 UTF-8 成功读取；本阶段只建设 Python 工程骨架、质量工具、基础 CLI 和只读 `doctor`。
- 当前 Git 状态不是干净工作树：`.idea/vcs.xml` 已暂存，`.gitignore` 未跟踪；这些视为用户已有改动，实施时保留。
- 仓库已是 Git 仓库并跟踪远程分支信息，但本任务禁止任何远程操作。
- 当前 shell 中的 Python 是 Anaconda 3.13.9，`VIRTUAL_ENV` 为空；`py -0p` 也只列出 Python 3.13。
- 当前仓库尚无 `src/`、`tests/`、`pyproject.toml`、README 或 LICENSE。
- 根目录 `main.py` 是完整的 PyCharm 默认示例，仓库其他文件无引用，可按目标要求删除。
- `.gitignore` 已包含 IDE、虚拟环境、Python 缓存、测试/静态检查缓存、构建产物和 egg-info；后续仅在确有缺项时补充。
- 正式文档确认退出码 0/1/2/3/4/5/130；阶段 1 仅实现实际需要的兼容子集。
- 架构文档中的完整目录是职责地图，不要求阶段 1 创建未来模块；本阶段只建立真实使用的包边界。
## 阶段 1 实现决策

- 版本号只定义在 `metricproof.__version__`，`pyproject.toml` 通过 setuptools dynamic attr 读取，CLI 复用同一来源。
- `doctor` 使用一个目的明确的 `DoctorProbe` Protocol；应用层生成结构化 `DoctorCheck`/`DoctorReport`，本地适配器执行只读探测，CLI 负责 Rich 展示和退出码。
- 非 Git 目录、缺少 `.metricproof`、未发现 `.tex` 都是 WARN；Python 不兼容、Git 不可用/超时或扫描错误是 FAIL，并映射退出码 4。
- LaTeX 发现仅按 `.tex` 后缀做有界枚举，不读取或解析内容；最大深度 6、最多 1000 个文件，并忽略常见 VCS、虚拟环境、缓存和构建目录。
- `pyproject.toml` 声明完整的阶段目标运行时依赖和独立 dev extra；阶段 1 代码只实际导入 Typer 和 Rich。
- 当前环境已有 Typer、Rich、Pydantic、PyYAML、Jinja2、pytest、Ruff；缺少 pylatexenc、pytest-cov、Pyright 和 build。
## 最终验证发现

- Python 3.12.13 可离线完成项目本体 editable 安装、统一版本元数据验证、compileall 和 setuptools wheel 构建。
- 完整 `.[dev]` 安装不能离线完成：本机无 Typer 等 Python 3.12 分发包缓存；不得联网下载。
- Python 3.13.9 隔离 venv 复用了本机已有 Typer/Rich，console script、模块入口、版本和 doctor 均实际通过。
- 最终测试为 33 passed；Ruff lint 与 format check 通过。
- 覆盖率、Pyright 和 `python -m build` 因对应工具未安装而没有成功结果；覆盖率数值不可声称。
- 最终范围审计未发现网络访问、`shell=True`、`eval`、`exec`、下一阶段业务实现或远程/破坏性 Git 操作。
## 2026-07-16 Python 3.13 收尾审计

- 用户明确将当前开发和最低支持版本改为 Python 3.13；这是新的正式产品/工程决策，需要同步 `AGENTS.md`、`SPEC.md`、`ARCHITECTURE.md`、`pyproject.toml`、README、doctor 和测试。
- 当前解释器为 Anaconda Python 3.13.9。
- 当前环境已安装全部声明依赖和质量工具：Typer、Rich、Pydantic、PyYAML、Jinja2、pylatexenc、pytest、pytest-cov、Ruff、Pyright、build。
- 用户已暂存删除 `.idea/` 中的五个文件；这些修改将保留。
- `.coverage.LAPTOP-3FVD5FN9.pid24152.Xu6j7Jrx.c` 是 coverage 并行数据文件；`wq` 内容是带 ANSI 转义的 Git diff 输出，二者均属于验证/终端临时产物。

## 2026-07-16 Python 3.13 最终验证

- 目标命令 `python -m pytest --cov=metricproof` 在配置中固化 branch coverage 后直接通过，34 tests passed，总覆盖率 95.86%。
- Pyright strict 在仓库标准 `.venv` 下通过：0 errors、0 warnings、0 informations。
- `metricproof --help`、`metricproof --version`、`metricproof doctor` 和 `python -m metricproof --help` 均通过。
- 标准隔离 `python -m build` 因禁网无法向临时环境安装 setuptools/wheel；使用相同构建后端的 `python -m build --no-isolation` 成功生成 sdist 与 wheel。
- `wq` 是误操作产生的已跟踪终端输出文件，已根据用户明确要求删除。
- 当前实现未越界进入实验结果读取、LaTeX 解析、Claim、规则或正式报告。
- 构建元数据已迁移到 SPDX `Apache-2.0` 表达式，并将 setuptools 构建基线调整为 `>=77`，最终构建不再输出许可证弃用警告。

## 2026-07-16 阶段 3 实现与验收发现

- 阶段 3 的安全边界需要在配置层和格式适配器层同时执行：配置解析拒绝越界路径，读取器再次验证解析后的真实路径。
- JSON 和 YAML 数字必须从词法文本构造 `Decimal`；任何经二进制 `float` 的中转都会破坏确定性精度。
- YAML 安全加载还不足以覆盖产品约束，因此另外拒绝重复 key、多文档、递归别名、非字符串 key 和超深结构。
- 结构化来源必须显式声明 metric、metadata 和 run selector；自动猜测只会造成不可审计的高置信度误绑定。
- CSV 使用标准库即可满足当前范围；显式列映射、严格行宽与行数上限比引入 pandas 更小、更可解释。
- 同一 run 的跨来源合并以稳定 source 顺序进行；重复 metric、metadata 和 config reference 冲突形成结构化阻断诊断，不静默覆盖。
- CLI 的机器输出与人类输出必须完全分离：`--json` 只向 stdout 写稳定 JSON，诊断写 stderr，配置错误和输入错误分别使用退出码 2 与 3。
- 自动测试最终为 121 passed、1 skipped，branch coverage 92.84%；跳过项仅因当前 Windows 账户无法创建符号链接。
- 真实 Windows 目录联接测试补充验证了链接逃逸：越界来源被拒绝，`experiments validate` 返回退出码 2。
- 三格式临时项目证明 JSON、YAML、CSV 可在一个 catalog 中确定性归一化为 4 个 run、4 个 observation、0 个 diagnostic。
- 阶段 3 没有进入 LaTeX、Claim、论文规则、正式报告、Git 证据、数据库、Web、插件或联网范围。
- 目标附件的 Python 3.12 文本已被仓库当前正式 Python 3.13 决策取代；本阶段在 Python 3.13.9 上完成验收。
