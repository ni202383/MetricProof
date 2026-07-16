# MetricProof 阶段 4A 实现计划

## 目标

在 Python 3.13 基线上实现受控 LaTeX 文件依赖图、源码屏蔽、Decimal 原始数值候选与基础语法上下文，并提供安全稳定的 `metricproof scan` / `scan --json`。完成测试、性能验证和直接相关文档后停止，不进入表格语义、PaperClaim、Claim ID、实验链接或五条规则。

## 当前阶段

阶段 7：完成标准审计。

## 阶段与验证门

| 阶段 | 状态 | 验证门 |
|---|---|---|
| 1. 修改前基线 | complete | Python 3.13.9；121 passed、1 skipped；Ruff、格式、Pyright、compileall、build、git diff check 通过 |
| 2. 配置、领域模型、端口与资源限制 | complete | 兼容现有构造器和接口；58 passed、1 skipped；Ruff、格式、Pyright 通过 |
| 3. LaTeX 文件图与源码屏蔽 | complete | include 图、安全边界、注释、代码环境、位置和恢复测试通过 |
| 4. 数值词法与上下文 | complete | Decimal、百分数、mean±std、边界、上下文和生成式验证通过 |
| 5. 应用服务与 scan CLI | complete | 人类/JSON、--file、--show-all、stdout/stderr、退出码测试通过 |
| 6. 性能、文档与全量验收 | complete | 合成性能测试通过；186 passed、2 skipped、90.82% coverage；构建和目标命令实测通过 |
| 7. 完成标准审计 | complete | 14 条完成标准逐项满足，无越界实现 |

## 关键设计决策

- 使用小型确定性状态机扫描原始源码，不执行 TeX 或宏。
- LaTeX adapter 负责文件、解析和位置；application 只编排；domain 不依赖文件系统或第三方 AST。
- 扩展现有 `NumericValue` 时保持原有两个位置参数兼容。
- 原始候选单独建模，不命名为 PaperClaim，不生成 Claim ID。
- `--show-all` 的真实语义是额外显示低上下文的 `COMMAND_ARGUMENT` / `UNKNOWN` 候选。
- `--file` 只过滤已构建配置图中的实际文件，不能读取图外路径。

## 禁止边界

- 不删除或覆盖无关文件。
- 不执行 TeX、用户宏、用户脚本或任意表达式。
- 不实现表格行列/表头语义、PaperClaim、Claim ID、claims.yml、链接或规则。
- 不联网、不 commit、不 push、不创建远程资源。

## 错误记录

| 问题 | 处理 |
|---|---|
| 早期 Windows restricted-token 沙箱阻止 apply_patch、pytest 和 build | 权限恢复后重新跑完整基线，全部通过 |
| 早期写权限探针留下未跟踪文件 | 仅删除代理自己创建的探针，不清理任何无关文件 |
