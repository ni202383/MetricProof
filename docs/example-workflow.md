# MetricProof 示例工作流

本文件描述当前已实现的阶段 4B1 工作流：严格读取实验结果，从受控 LaTeX 依赖图提取原始数值候选，并建立基础 tabular 行列、单元格、格式与可靠性事实。候选和表格事实都不是 Claim；表头/指标/最佳值语义、链接、论文规则与报告仍是后续阶段。

## 1. 当前可运行的实验项目

```text
demo-project/
├── paper/
│   ├── main.tex
│   └── sections/
│       └── results.tex
├── runs/
│   ├── baseline.json
│   ├── proposed.yml
│   └── seeds.csv
├── configs/
│   └── proposed.yml
└── .metricproof/
    └── config.yml
```

最小 `.metricproof/config.yml`：

```yaml
schema_version: "1"
paper_paths:
  - paper/main.tex

result_paths:
  - path: runs/baseline.json
    format: json
    run_id: baseline
    structured:
      metrics:
        accuracy: metrics.accuracy
      metadata:
        dataset: context.dataset
        split: context.split

  - path: runs/proposed.yml
    format: yaml
    run_id: proposed
    config_reference: configs/proposed.yml
    structured:
      metrics:
        accuracy: metrics.accuracy
      metadata:
        dataset: context.dataset
        split: context.split

  - path: runs/seeds.csv
    format: csv
    csv:
      run_id_column: run_id
      metric_columns: [accuracy]
      metadata_columns: [dataset, split, seed]

experiment_config_paths:
  - configs/*.yml
exclude_paths:
  - build/**
```

JSON、YAML 和 CSV 的指标都必须由配置显式声明。系统不会因为某个字段恰好是数值，就自动把它认定为实验指标。

`paper/main.tex` 可以使用静态相对 include：

```tex
\section{Results}
\input{sections/results}
```

`paper/sections/results.tex`：

```tex
Accuracy is 87.2\%, with $0.872 \pm 0.004$ across 5 runs.
% This commented value 99.9 is ignored.
\begin{table}
\caption{Main results}
\label{tab:main}
\begin{tabular}{lcc}
\toprule
Model & Accuracy & Runs \\
Baseline & 84.1 & 5 \\
Ours & \textbf{87.2} & \underline{5} \\
\multicolumn{3}{c}{Reported on the test split} \\
\bottomrule
\end{tabular}
\end{table}
\begin{verbatim}
fake = 123.4
\end{verbatim}
```

## 2. 扫描 LaTeX 原始数值候选

```text
metricproof scan
metricproof scan --show-all
metricproof scan --show-tables
metricproof scan --file paper/sections/results.tex
metricproof scan --json
```

默认输出文件、行列、原文、规范十进制值和语法上下文，并汇总 parsed/degraded/unsupported 表格数量。`--show-all` 额外显示命令参数与 unknown 等低上下文候选；`--show-tables` 展开 caption/label、行数、逻辑列、短单元格内容、数值引用、格式与 limitation；`--file` 只能选择配置依赖图中的文件，并同时过滤候选和表格。

扫描保留正文、数学、caption 和表格环境上下文，并解析基础 tabular 行列，但不判断数字是不是论文结论，不推断表头、指标、模型、方向或最优值。JSON 模式只向 stdout 写 schema version `2` 的稳定文档，包含精确表格/单元格范围和候选格式关联；诊断包含 code、位置、证据、严重程度和修复建议。

## 3. 验证实验输入

```text
metricproof experiments validate
metricproof experiments validate --json
```

成功时会输出已归一化的 run、observation 和 diagnostic 数量，退出码为 `0`。配置 schema 或路径错误使用退出码 `2`；JSON/YAML/CSV 解析、非法数值、重复 run/metric 等阻断输入问题使用退出码 `3`。

人类可读诊断写入 stderr，并包含 code、severity、文件、selector/行列、证据和最小修复建议。`--json` 只在 stdout 输出一个稳定 JSON 文档。

命令只读，不创建或修改配置、结果和实验配置文件。

## 4. 列出归一化结果

```text
metricproof experiments list
metricproof experiments list --json
```

默认表格显示：

- 稳定 `run_id`；
- 规范指标名和精确十进制值；
- 项目相对源文件；
- JSON/YAML 点路径或 CSV 行列 selector。

JSON/YAML 单 run 来源声明固定 `run_id`，或通过 `run_id_selector` 读取一个 run ID。多 run 来源必须显式声明 `records_selector` 和相对记录的 `run_id_selector`。CSV 每行对应一个 run。

多个来源可以为同一 run 提供不同指标；同一 run 的重复指标或冲突元数据不会静默覆盖，而会形成阻断诊断。

## 5. 当前安全边界

- 文件只接受 UTF-8 或 UTF-8 BOM。
- YAML 使用安全 loader，拒绝任意 Python 对象、多 document 和重复 key。
- JSON 拒绝重复 key 和 `NaN`/`Infinity`。
- CSV 只支持有表头的二维表格，使用标准库 `csv`，不猜测列角色。
- 指标最终使用 `Decimal`；JSON/YAML 小数不经过二进制 `float`。
- 布尔值、空字符串和非有限数值不是合法指标。
- 路径必须留在项目根目录；绝对路径、`..` 和符号链接逃逸均拒绝。
- LaTeX 只跟随静态相对 `\input{}` / `\include{}`；动态宏参数受控降级为 limitation。
- 注释、`\verb`、`verbatim`、`Verbatim`、`lstlisting` 与 `minted` 内容不扫描。
- 表格只支持 `table`/`table*` 容器和 `tabular`/`tabular*` 结构；`multirow` 降级，`longtable`/`tabularx`/`array`/`matrix`/`aligned` 标为 unsupported。
- 固定表格上限为 1,000 张表、单表 10,000 行、单行 1,000 个物理单元格、单表 100,000 个单元格、单元格 100,000 字符、嵌套深度 16、multicolumn span 1,000。
- 不执行实验文件、训练代码、TeX、Python 模块或表达式，也不联网。

## 6. 后续阶段（尚未实现）

以下命令和能力仍不可用：

```text
metricproof init
metricproof link
metricproof check
metricproof report
```

后续阶段将依次实现 Claim 分类与身份、表头/指标/最佳值语义、用户确认链接、五条一致性规则、统一检查结果和离线报告。阶段 4B1 不提前进入这些工作。
