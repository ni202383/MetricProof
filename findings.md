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