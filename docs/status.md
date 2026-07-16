# MetricProof 项目状态

更新日期：2026-07-16

## 当前阶段

阶段 1：Python 工程骨架、质量工具和基础 CLI。

状态：工程实现已完成；可用的本地验证已通过。由于当前环境禁止联网且未缓存 `pytest-cov`、`pyright`、`build` 和完整运行时依赖，覆盖率、Pyright 和 `python -m build` 尚未实际通过，阶段 1 完成标准因此不能标记为“全部满足”。

## 本阶段已完成

- 建立 Python `>=3.12,<4.0` 的 `src` layout 和最小包边界：`domain`、`application`、`adapters`、`cli`。
- 建立 `pyproject.toml`，区分运行时依赖与 `dev` extra，并配置 pytest、coverage、Ruff、Pyright 和 setuptools build backend。
- 建立单一版本来源 `metricproof.__version__ = "0.1.0.dev0"`；包元数据和 `metricproof --version` 复用该值。
- 提供 console script `metricproof = metricproof.cli.main:app` 和 `python -m metricproof` 入口。
- 提供 `--help`、`--version` 和 `doctor`。
- `doctor` 通过应用端口接收只读环境探测，结构化返回 PASS/WARN/FAIL、code、位置、证据和消息。
- `doctor` 检查 Python 版本、Git 状态、项目根目录、`.metricproof` 目录和有界 `.tex` 文件发现。
- Git 使用参数列表、只读命令和 3 秒超时；不使用 `shell=True`。
- `.tex` 发现最大深度为 6、最多 1000 个文件，默认忽略 `.git`、`.venv`、`build`、`dist`、`__pycache__` 等目录，不解析或读取 LaTeX 内容。
- 建立与 SPEC 兼容的退出码枚举和最小用户可见异常边界；预期错误与内部错误不向用户输出 traceback。
- 创建 README、Apache-2.0 LICENSE、`.gitignore` 和 33 项测试。
- 根目录 `main.py` 已确认是未引用的 PyCharm 默认模板，并按阶段目标删除；最终 CLI 不依赖该文件。

## 当前可运行命令

在安装了项目依赖的环境中：

```text
metricproof --help
metricproof --version
metricproof doctor
python -m metricproof --help
python -m pytest
python -m pytest --cov=metricproof
python -m ruff check .
python -m ruff format --check .
pyright
python -m build
```

开发安装命令：

```text
python -m pip install -e ".[dev]"
```

## 实际验证状态

| 命令或检查 | 结果 | 环境/说明 |
|---|---|---|
| Python 3.12 解释器检查 | PASS | Codex bundled Python 3.12.13 |
| `python -m pip install -e ".[dev]"` | ENVIRONMENT BLOCKED | 强制离线；构建隔离无法获取 setuptools，关闭隔离后确认缺少 Typer 等本地分发包 |
| `python -m pip install --no-build-isolation --no-deps -e .` | PASS | Python 3.12.13；验证 editable 包和统一版本元数据 |
| `python -m compileall -q src` | PASS | Python 3.12.13 |
| `python -m pytest` | PASS | Python 3.13.9；33 passed in 0.64s |
| `python -m pytest --cov=metricproof` | ENVIRONMENT BLOCKED | 当前解释器未安装 `pytest-cov`，`--cov` 无法识别 |
| `python -m ruff check .` | PASS | Ruff 0.12.0 |
| `python -m ruff format --check .` | PASS | 14 files already formatted |
| `pyright` | ENVIRONMENT BLOCKED | 本机未安装 Pyright，npm 离线缓存也不存在 |
| `metricproof --help` | PASS | Python 3.13.9 隔离 venv + 本机已有 Typer/Rich |
| `metricproof --version` | PASS | 输出 `MetricProof 0.1.0.dev0` |
| `metricproof doctor` | PASS | 当前仓库 3 PASS、2 WARN、退出码 0；未执行写操作 |
| `python -m metricproof --help` | PASS | Python 3.13.9 隔离 venv |
| `python -m build` | ENVIRONMENT BLOCKED | Python 3.12 环境未安装 `build` 模块 |
| `python -m pip wheel --no-build-isolation --no-deps .` | PASS | Python 3.12.13；生成 `metricproof-0.1.0.dev0-py3-none-any.whl` |
| `git diff --check` | PASS | 仅有 Git 行尾提示，无空白错误 |

## 尚未实现

- `.metricproof` 配置创建与读取。
- JSON、YAML、CSV 实验结果读取。
- LaTeX 文件图、内容解析、Claim 和表格提取。
- Claim 链接、迁移和持久化。
- 五条一致性规则。
- `CheckResult`、正式 JSON/HTML 报告和完整 Console 报告。
- Git 证据链、GitHub Actions 和端到端示例。

## 已知限制

- 当前本机没有可离线安装的完整依赖集合，无法完成 `.[dev]` 全量安装。
- 覆盖率数值未生成，不能声称达到配置的 90% 阈值。
- Pyright 严格配置已建立，但尚未由 Pyright 实际验证。
- 标准 `python -m build` 未运行成功；仅验证了同一 setuptools backend 的离线 wheel 构建。
- 当前可完整运行 CLI 的隔离验证环境是 Python 3.13.9；Python 3.12 已验证包安装、版本和编译，但因缺少 Typer/Rich 未运行 CLI。
- `doctor` 只做浅层环境诊断；不创建 `.metricproof`，不解析 LaTeX，不读取实验结果。

## 下一阶段可依赖的稳定接口

- `metricproof.__version__`：单一版本来源。
- `metricproof.cli.main:app`：console script 与模块入口共享的 Typer 应用。
- `metricproof.application.errors.ExitCode`：与 SPEC 兼容的退出码基础。
- `metricproof.application.doctor.DoctorProbe`：只读 doctor 环境端口。
- `metricproof.application.doctor.run_doctor`：不依赖 Rich 的应用服务。
- `DoctorCheck`、`DoctorReport`、`GitInspection`、`LatexDiscovery`：阶段 1 的最小结构化环境检查模型。
- `metricproof.adapters.doctor.LocalDoctorProbe`：受边界限制的本地文件系统/Git 适配器。

下一阶段不得绕过这些边界把配置、实验读取、LaTeX 解析或规则逻辑直接写入 CLI。