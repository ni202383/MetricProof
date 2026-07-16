# 阶段 4A 进度

## 2026-07-16

### 阶段 1：修改前基线

- 状态：complete
- Python 3.13.9。
- `python -m pytest`：121 passed，1 skipped。
- Ruff lint、Ruff format check、Pyright strict、compileall、build 和 `git diff --check` 全部通过。
- 跳过项仅是当前 Windows 账户不能创建测试符号链接。

### 阶段 2：配置、领域模型、端口与资源限制

- 状态：complete
- `ProjectConfiguration` 现在保存严格、去重、排序后的 `.tex` `paper_paths`，并允许 scan-only 配置。
- 新增 raw candidate、LaTeX graph、统计和 scan result 领域模型，以及 `PaperScanner` 端口和 `scan_paper` 服务。
- 扩展 `NumericValue` 时保留原有两个位置参数兼容。
- 阶段验证：58 passed、1 skipped；Ruff、格式和 Pyright strict 通过。

### 阶段 3：LaTeX 文件图与源码屏蔽

- 状态：complete
- 静态 `\input` / `\include` 图、循环与缺失恢复、路径边界、文件身份去重和 provenance 已实现。
- 注释、`\verb` 与四类代码环境屏蔽测试通过。
- 扫描器测试：24 passed，1 skipped。

### 阶段 4：数值词法与上下文

- 状态：complete
- 整数、小数、科学计数法、百分数和 `mean ± std` 使用精确 `Decimal`。
- 正文、数学、命令参数、表格、caption 与 unknown 上下文已覆盖。
- 1,000 个生成数值词法、200 组注释转义奇偶测试通过。

### 阶段 5：应用服务与 scan CLI

- 状态：complete
- `scan_paper`、`metricproof scan`、`--json`、`--show-all`、`--file` 已实现。
- CLI 正常、错误、JSON 纯净输出、退出码、只读和异常隐藏测试：11 passed。

### 阶段 6：性能、文档与全量验收

- 状态：complete
- 合成约 5,000 候选的性能与扩展比例测试通过。
- 全量测试：186 passed，2 skipped。
- 覆盖率：90.82%，达到 90% 门槛。
- Ruff、格式、Pyright strict、compileall、build 与 `git diff --check` 已通过。
- 干净验收项目：3 个文件、6 个候选、0 诊断，human/JSON 退出码均为 0。
- 诊断验收项目：3 个文件、4 个候选、缺失 include 与循环 2 个诊断，JSON 退出码 3。
- Windows 目录联接逃逸验收：1 个保留候选、`MPE_LATEX_PATH_ESCAPE`，退出码 3；目标文件未删除。
- 实验验收：1 run、1 observation、0 diagnostic，退出码 0。

### 阶段 7：完成标准审计

- 状态：complete
- 14 条完成标准均满足。
- 未实现表格行列/表头语义、Claim 分类、PaperClaim、Claim ID、链接、五条规则或 HTML 报告。
- 未执行 TeX、用户宏、联网、远程资源、commit 或 push。
- 未删除或覆盖任何无关文件。
