# MetricProof 示例工作流

本文件区分当前已实现的阶段 3 工作流与后续首版目标。当前可以严格读取实验配置和 JSON/YAML/CSV 结果；LaTeX、Claim、论文规则与报告仍是后续阶段，本文不会把它们描述为可运行功能。

## 1. 当前可运行的实验项目

```text
demo-project/
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

## 2. 验证实验输入

```text
metricproof experiments validate
metricproof experiments validate --json
```

成功时会输出已归一化的 run、observation 和 diagnostic 数量，退出码为 `0`。配置 schema 或路径错误使用退出码 `2`；JSON/YAML/CSV 解析、非法数值、重复 run/metric 等阻断输入问题使用退出码 `3`。

人类可读诊断写入 stderr，并包含 code、severity、文件、selector/行列、证据和最小修复建议。`--json` 只在 stdout 输出一个稳定 JSON 文档。

命令只读，不创建或修改配置、结果和实验配置文件。

## 3. 列出归一化结果

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

## 4. 当前安全边界

- 文件只接受 UTF-8 或 UTF-8 BOM。
- YAML 使用安全 loader，拒绝任意 Python 对象、多 document 和重复 key。
- JSON 拒绝重复 key 和 `NaN`/`Infinity`。
- CSV 只支持有表头的二维表格，使用标准库 `csv`，不猜测列角色。
- 指标最终使用 `Decimal`；JSON/YAML 小数不经过二进制 `float`。
- 布尔值、空字符串和非有限数值不是合法指标。
- 路径必须留在项目根目录；绝对路径、`..` 和符号链接逃逸均拒绝。
- 不执行实验文件、训练代码、TeX、Python 模块或表达式，也不联网。

## 5. 后续阶段（尚未实现）

以下命令和能力仍不可用：

```text
metricproof init
metricproof scan
metricproof link
metricproof check
metricproof report
```

后续阶段将依次实现 LaTeX Claim/表格提取、用户确认链接、五条一致性规则、统一检查结果和离线报告。本阶段满足完成标准后停止，不提前进入这些工作。
