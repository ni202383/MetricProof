# MetricProof 阶段 1 工程实现计划

## 2026-07-16 Python 3.13 收尾

用户已明确将当前开发与最低支持版本调整为 Python 3.13。继续工作时保留用户已暂存的 `.idea/` 删除，并完成以下收尾：

| 阶段 | 状态 | 成功标准 |
|---|---|---|
| A. 审计用户修改和 Python 3.13 环境 | complete | 确认工作树、依赖和新生成文件，不覆盖用户修改 |
| B. 同步 Python 3.13 基线 | in_progress | 更新正式文档、包元数据、Ruff、Pyright、doctor 和测试 |
| C. 清理验证产物 | pending | 仅删除确认属于 coverage/终端的临时产物并完善 gitignore |
| D. 完整质量验证 | pending | editable 安装、pytest、coverage、Ruff、Pyright、CLI、build 全部实际执行 |
| E. 状态文档与完成审计 | pending | 更新实际结果并确认阶段 1 完成标准 |

当前 Python 3.13.9 环境已具备全部声明的运行时与开发依赖，包括 `pytest-cov`、Pyright 和 `build`。
## 当前目标

在不扩大首版产品范围的前提下，建立可安装、可测试、可静态检查、可构建的 Python 3.13 `src` layout 工程，并提供 `metricproof` / `python -m metricproof`、`--help`、`--version` 和只读 `doctor` 命令。

## 当前阶段

| 阶段 | 状态 | 成功标准 |
|---|---|---|
| 1. 基线审计与约束确认 | complete | 阅读正式文档，核对 Git、文件、解释器、虚拟环境和现有 `main.py` |
| 2. 工程骨架与配置 | complete | 建立最小包结构、`pyproject.toml`、版本、README、LICENSE、gitignore |
| 3. 基础 CLI 与 doctor | complete | CLI 入口轻量；doctor 返回结构化 PASS/WARN/FAIL，路径与 Git 检查只读且受控 |
| 4. 测试与缺陷修复 | complete | 覆盖目标文件要求的正例、反例、边界和退出码 |
| 5. 全量验证与文档同步 | complete_with_environment_limits | 实际运行安装、测试、覆盖率、Ruff、Pyright、CLI、build，并更新 `docs/status.md` |
| 6. 完成标准审计 | complete_with_environment_limits | 核对范围、文件、验证结果、限制和稳定接口后停止 |

## 不可越界

- 不实现 LaTeX 解析、实验读取、Claim 链接、五条规则或正式 JSON/HTML 报告。
- 不联网，不调用 AI API，不创建远程资源，不提交、不推送、不发布。
- 不执行用户代码、TeX、脚本或任意表达式。
- 保留用户已有改动；当前已发现暂存的 `.idea/vcs.xml` 与未跟踪 `.gitignore`。
- 所有写操作仅限当前仓库，并使用最小、可解释的实现。

## 当前环境事实

- 仓库当前分支为 `main`，存在 `origin/main`。
- 当前解释器为 `D:\Programming\Anaconda3\python.exe`，版本 3.13.9，未激活虚拟环境。
- `py -0p` 仅列出 Python 3.13；后续找到 Codex bundled Python 3.12.13 用于离线包验证。
- 正式设计文档与上一阶段规划文件均已存在。
- 根目录 `main.py` 已确认是未被引用的 PyCharm 示例模板，并已按目标要求删除。

## 错误与异常记录

| 现象 | 尝试 | 处理 |
|---|---:|---|
| 首次读取目标文件出现乱码 | 1 | 明确指定 UTF-8 后成功读取 |
| `create_goal` 返回已有活动目标 | 1 | 保留当前活动目标并在其下继续执行阶段 1 |
| `apply_patch` 在 Windows sandbox wrapper 初始化失败 | 2 | 绝对和相对路径均失败；改用仓库内受限 PowerShell 文本写入并记录环境问题 |
| `pytest` 默认临时目录被 Windows 沙箱拒绝访问 | 1 | 记录为环境问题；修复代码后以获批的非沙箱测试运行重试 |
| `ruff format .` 完成格式化后扫描 pytest 锁定缓存目录失败 | 1 | 删除本次测试生成的锁定缓存目录；随后 `ruff check .` 与 format check 通过 |
| Python 3.12 离线 `.[dev]` 安装缺少本地分发包 | 2 | 明确区分构建隔离与依赖缺失；项目本体 `--no-deps` editable 安装通过 |
| coverage、Pyright、`build` 命令缺少对应工具 | 1 | 记录为环境限制；不伪造结果，补充 Python 3.12 wheel 构建验证 |
| `apply_patch` 在 Python 3.13 收尾时仍无法初始化 Windows sandbox wrapper | 1 | 使用仓库内受限的精确文本替换继续，并保留错误记录 |

---

## 历史：设计阶段计划
# MetricProof 设计阶段计划

## 目标

在不编写业务实现代码的前提下，完成 MetricProof 首版的产品规格、架构、领域模型、规则语义、用户工作流和仓库长期约束，并验证七份正式设计文档彼此一致。

## 阶段

| 阶段 | 状态 | 产出 |
|---|---|---|
| 1. 检查项目现状与既有约束 | complete | 当前目录清单、Git 状态、已有文件判断 |
| 2. 固定跨文档设计决策 | complete | 范围、分层、数据模型、配置格式、退出码与规则语义 |
| 3. 创建正式设计文档 | complete | SPEC.md、ARCHITECTURE.md、AGENTS.md、docs/* |
| 4. 跨文档一致性与范围审计 | complete | 术语、接口、规则、退出码、阶段依赖核对 |
| 5. 完成状态记录与交付 | complete | docs/status.md、progress.md 和最终摘要 |

## 核心约束

- 仅完成设计层工作，不编写业务实现代码。
- 不初始化、提交、推送或发布 Git 仓库。
- 不引入数据库、服务端、插件系统、外部 AI API 或在线依赖。
- 首版范围固定为 Python 3.12、本地 CLI、LaTeX、JSON/YAML/CSV 和本地 Git。
- 所有规则结论只能表示一致性问题或启发式风险。

## 已确定决策

- 使用 `src` layout 和端口/适配器分层。
- 规则引擎只接收已准备好的领域对象，不直接访问文件系统或 Git。
- 数值计算语义以十进制精确表示、显式缩放、容差和显示精度为基础。
- 自动匹配只提供候选；持久化链接需要用户确认。
- Claim ID 使用内容与结构上下文指纹，不使用绝对行号作为唯一身份。

## 错误与异常记录

| 现象 | 处理 |
|---|---|
| 当前目录不是 Git 仓库 | 记录为项目现状和后续前置条件；本阶段不执行 `git init` |
| 规划文件更新补丁三次被 Windows 沙箱包装器拒绝 | 正式文档不受影响；经授权仅对规划状态和现状描述做精确文本更新 |

