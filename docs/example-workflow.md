# MetricProof 示例工作流

本文件描述首版目标体验。当前设计阶段尚无可运行实现，所有命令输出均为预期接口示例，不代表测试已经执行。

## 1. 示例项目

```text
demo-project/
├── paper/
│   ├── main.tex
│   └── tables/
│       └── results.tex
├── runs/
│   ├── baseline.json
│   ├── proposed.json
│   └── seeds.csv
├── configs/
│   ├── baseline.yml
│   └── proposed.yml
└── .metricproof/
    ├── config.yml
    └── claims.yml
```

论文中包含：

```latex
Our method improves accuracy from 84.1\% to 87.6\%,
an improvement of 3.5 percentage points.

\begin{tabular}{lcc}
Method & Accuracy $\uparrow$ & Latency $\downarrow$ \\
Baseline & 84.1 & \textbf{20.0} \\
Proposed & \textbf{87.6} & \underline{18.0} \\
\end{tabular}
```

当前实验记录实际给出 proposed accuracy `0.872`，且 proposed 使用了不同的数据 split。

## 2. 初始化

用户在项目根目录执行：

```text
metricproof init
```

预期行为：

- 创建最小 `.metricproof/config.yml` 和 `.metricproof/claims.yml`。
- 已存在时默认拒绝覆盖。
- 不创建 Git 仓库、远程仓库或网络资源。

用户随后编辑配置，声明论文入口、实验结果、指标方向和受控字段。

## 3. 验证实验输入

辅助工作流可以提供：

```text
metricproof experiments validate
metricproof experiments list
```

预期摘要：

```text
Loaded 2 runs and 6 metric observations.
No blocking experiment input errors.
```

若 CSV 缺列或 YAML 含非法数值，命令应指出文件和结构位置并使用退出码 3，不返回空结果伪装成功。

## 4. 扫描论文

```text
metricproof scan
```

预期摘要：

```text
Scanned 2 LaTeX files.
Found 8 experimental claims, 3 uncertain numeric candidates, and 1 table.
```

`--show-all` 可以展示被排除的年份、引用编号和不确定候选及其分类证据。

扫描不修改论文，也不自动建立永久链接。

## 5. 建立链接

```text
metricproof link
```

对于论文中的 `87.6\%`，候选可能显示为：

```text
Claim paper/main.tex:12:45  "87.6\%"

1. proposed / accuracy / runs/proposed.json
   normalized value: 87.2%
   score: 0.91
   evidence: metric alias "accuracy", run name "proposed", table header match
   uncertainty: current value differs from the displayed claim

2. baseline / accuracy / runs/baseline.json
   normalized value: 84.1%
   score: 0.62
   evidence: metric alias "accuracy"
   uncertainty: run context does not match
```

用户确认第一个候选后，工具把 DirectLink 原子写入 `claims.yml`。数值不同不阻止链接，因为链接建立后正需要由 `STALE_VALUE` 报告过期值。

对于出版年份，用户可选择“非实验数字”，生成带理由的 IgnoreRecord。

非交互模式：

```text
metricproof link --non-interactive --json
```

只输出建议，不写入确认链接。

## 6. 执行检查

```text
metricproof check --fail-on error
```

预期诊断示例：

```text
ERROR STALE_VALUE paper/main.tex:12
The linked experimental value no longer matches the displayed claim.
Observed in paper: 87.6%
Current linked value: 87.2%
Source: runs/proposed.json → metrics.accuracy

ERROR WRONG_DELTA paper/main.tex:13
The displayed percentage-point change does not match the linked operands.
Displayed: 3.5 points
Recomputed: 3.1 points
Formula: (0.872 - 0.841) × 100

WARNING WRONG_BEST_MARK paper/tables/results.tex:4
The bold latency value is not in the configured lower-is-better set.

WARNING UNFAIR_COMPARISON configs/proposed.yml
Controlled comparison settings differ and require review.
dataset.split: baseline="test-v1", candidate="test-v2"
```

如果另一个实验 Claim 没有链接或 ignore，则产生 `MISSING_PROVENANCE`。

该命令完成了分析，但存在 error 级规则诊断，因此退出码为 1，而不是输入失败。

## 7. 机器可读检查

```text
metricproof check --json
```

stdout 只包含版本化 JSON，Rich 提示不得混入。输入错误可以写入 JSON 的 `errors`，同时通过 stderr 提供简短人类提示。

## 8. 生成报告

```text
metricproof report --format html --output metricproof-report.html
metricproof report --format json --output metricproof-report.json
```

HTML 预期包含：

- 规则和严重程度摘要。
- 文件与位置过滤。
- 每条诊断的 observed、expected 和 remediation。
- Claim → Link → Observation → Result Source → Config → Git 的证据链。
- unavailable/broken 节点的明确标记。

报告完全离线，不引用 CDN，不启动服务器。

## 9. 修改并复查

用户可以选择：

- 更新论文数字。
- 重新运行或选择正确实验来源。
- 修正 DerivedLink 的 operation/unit。
- 修正表格格式。
- 统一实验配置或在 `allowed_differences` 中说明合法差异。
- 为非实验数字建立 IgnoreRecord。

再次运行：

```text
metricproof check
```

当命令完成且没有达到失败阈值时退出码为 0。MetricProof 不自动修改任何来源文件。

## 10. 未来 CI 使用

本地 MVP 成熟并公开后，可以在 GitHub Actions 中执行同一 CLI：

```text
metricproof check --fail-on error
metricproof report --format html --output metricproof-report.html
```

CI 只是本地确定性工作流的调用者，不引入云端 AI、secret 或不同规则语义。

