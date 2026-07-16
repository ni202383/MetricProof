# MetricProof 阶段 3 实验读取实现计划

## 2026-07-16 阶段 3

目标：在当前 Python 3.13 基线和既有分层架构上，实现严格安全的项目配置、统一实验领域模型、JSON/YAML/CSV 实验结果读取、应用编排以及 `experiments list` / `experiments validate`，完成测试、文档和全量验证后停止，不进入 LaTeX、Claim 或论文规则阶段。

| 阶段 | 状态 | 成功标准 |
|---|---|---|
| 1. 恢复上下文与修改前基线 | complete | 已阅读指定文档和现有代码；确认 Git/Python；pytest、coverage、Ruff、Pyright 基线通过 |
| 2. 固化最小配置与领域设计 | complete | 配置格式、领域模型、诊断、资源限制和端口与文档一致 |
| 3. 实现安全配置与格式适配器 | complete | config、JSON、YAML、CSV 严格解析，Decimal 精度与路径边界受控 |
| 4. 实现应用服务与 CLI | complete | 多来源稳定归一化；list/validate 人类与 JSON 输出及退出码正确 |
| 5. 完成测试与缺陷修复 | complete | 正例、反例、安全边界和回归测试通过 |
| 6. 同步文档与临时项目验收 | complete | README/status/data-model/example-workflow 与真实实现一致；三种来源实际归一化 |
| 7. 全量验证与完成审计 | complete | 目标文件列出的命令全部实际运行并记录；逐项核对完成标准 |

### 阶段 3 边界

- 当前仓库和 `AGENTS.md` 已将支持基线更新为 Python 3.13；目标附件中的 Python 3.12 描述属于旧阶段背景，不回退当前正式决策。
- 保留当前工作树中 README、状态文档、工程配置、规划文件和 `wq` 删除等既有改动，不自动提交或覆盖。
- 不实现 LaTeX 解析、`scan`、Claim、五条论文规则、HTML 报告、GitHub Actions、数据库、Web、插件或任何联网/远程操作。
- 不使用 pandas，不执行用户文件、训练代码、TeX、Python 表达式或任意对象构造。

### 修改前基线

- Python 3.13.9 (`D:\Programming\Anaconda3\python.exe`)。
- `python -m pytest`：34 passed；受限沙箱首次因 pytest 临时目录权限失败，获批使用正常临时目录后通过。
- `python -m pytest --cov=metricproof --cov-report=term-missing`：34 passed，95.86% branch coverage。
- `python -m ruff check .`：通过。
- `python -m ruff format --check .`：14 files already formatted。
- `pyright`：0 errors、0 warnings、0 informations。

### 阶段 3 错误记录

| 现象 | 尝试 | 处理 |
|---|---:|---|
| 首次读取目标附件出现 UTF-8 中文乱码 | 1 | 使用 `PYTHONIOENCODING=utf-8` 重新读取成功 |
| `apply_patch` 无法初始化 Windows restricted-token sandbox | 3 | 改用可 dry-run 的标准 unified diff `patch` 工具，不使用任意字符串替换 |
| pytest 受限沙箱无法访问默认临时目录 | 1 | 以正常临时目录权限重新运行，同一测试套件 34 项全部通过 |
| 标准隔离构建首次无法创建受限临时环境 | 1 | 以正常临时目录权限运行同一 `python -m build`，成功生成 sdist 与 wheel |
| 临时三格式项目首次无法在受限临时目录创建 | 1 | 在已验证的 `C:\tmp` 子目录重跑，JSON/YAML/CSV 归一化与 CLI 均通过 |
| 当前账户无法创建测试符号链接 | 1 | 自动测试保留 1 个权限跳过项，并用真实 Windows 目录联接验证逃逸被拒绝且退出码为 2 |

---

## 历史：阶段 1 工程实现计划

## 2026-07-16 Python 3.13 收尾

用户已明确将当前开发与最低支持版本调整为 Python 3.13。用户此前的工程修改已经提交；误操作生成并被跟踪的 `wq` 已按用户要求删除。

| 阶段 | 状态 | 成功标准 |
|---|---|---|
| A. 审计用户修改和 Python 3.13 环境 | complete | 确认工作树、依赖和新生成文件，不覆盖用户修改 |
| B. 同步 Python 3.13 基线 | complete | 正式文档、包元数据、Ruff、Pyright、doctor 和测试统一为 Python 3.13 |
| C. 清理验证产物 | complete | 删除 `wq` 和临时 coverage 数据；生成物由 `.gitignore` 排除 |
| D. 完整质量验证 | complete | editable 安装、pytest、coverage、Ruff、Pyright、CLI 和本地 build 均实际验证 |
| E. 状态文档与完成审计 | complete | `docs/status.md` 已同步，阶段 1 项目级完成标准满足 |

当前 Python 3.13.9 环境具备全部声明的运行时与开发依赖。标准隔离安装/构建因禁网无法下载临时构建依赖；无隔离离线等价命令通过并已记录。

## 当前目标

在不扩大首版产品范围的前提下，建立可安装、可测试、可静态检查、可构建的 Python 3.13 `src` layout 工程，并提供 `metricproof` / `python -m metricproof`、`--help`、`--version` 和只读 `doctor` 命令。

## 当前阶段

| 阶段 | 状态 | 成功标准 |
|---|---|---|
| 1. 基线审计与约束确认 | complete | 阅读正式文档，核对 Git、文件、解释器、虚拟环境和原 `main.py` |
| 2. 工程骨架与配置 | complete | 建立最小包结构、`pyproject.toml`、版本、README、LICENSE、gitignore |
| 3. 基础 CLI 与 doctor | complete | CLI 入口轻量；doctor 返回结构化 PASS/WARN/FAIL，路径与 Git 检查只读且受控 |
| 4. 测试与缺陷修复 | complete | 覆盖目标文件要求的正例、反例、边界和退出码 |
| 5. 全量验证与文档同步 | complete | 实际运行安装、测试、覆盖率、Ruff、Pyright、CLI、本地 build，并更新 `docs/status.md` |
| 6. 完成标准审计 | complete | 核对范围、文件、验证结果、限制和稳定接口后停止 |

## 不可越界

- 不实现 LaTeX 解析、实验读取、Claim 链接、五条规则或正式 JSON/HTML 报告。
- 不联网，不调用 AI API，不创建远程资源，不提交、不推送、不发布。
- 不执行用户代码、TeX、脚本或任意表达式。
- 所有写操作仅限当前仓库，并使用最小、可解释的实现。

## 当前环境事实

- 仓库当前分支为 `main`，比 `origin/main` 超前 1 个本地提交。
- 当前解释器为 `D:\Programming\Anaconda3\python.exe`，版本 3.13.9。
- 全部声明的运行时和开发依赖已经安装。
- 仓库内 `.venv` 供 Pyright 使用并被 Git 忽略；机器特定依赖路径未写入受跟踪文件。
- 根目录 PyCharm 模板 `main.py` 和误生成的 `wq` 均已删除；CLI 不依赖它们。

## 最终验证摘要

- `python -m pytest`：34 passed。
- `python -m pytest --cov=metricproof`：34 passed，95.86% branch coverage。
- Ruff lint 与 format check：通过。
- Pyright strict：0 errors / 0 warnings / 0 informations。
- CLI 四项入口：通过；`doctor` 当前为 3 PASS / 2 WARN，退出码 0。
- `python -m build --no-isolation`：成功生成 sdist 和 wheel。

## 错误与异常记录

| 现象 | 处理 |
|---|---|
| `apply_patch` 无法初始化 Windows sandbox wrapper | 使用仓库内精确 PowerShell 文本写入；未扩大写入范围 |
| pytest 默认临时目录被 Windows 沙箱拒绝访问 | 获批后在正常临时目录权限下复验通过 |
| pytest-cov 主/子进程产生 statement/branch 数据冲突 | 将 `--cov-branch` 固化进 pytest 配置，目标原始覆盖率命令直接通过 |
| Pyright 未自动发现 Anaconda 全局依赖 | 使用 README 约定的仓库 `.venv`，Pyright strict 验证通过 |
| 标准隔离 build 在禁网环境无法下载构建依赖 | 同 setuptools 后端的 `--no-isolation` 离线构建成功；限制已写入状态文档 |

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
