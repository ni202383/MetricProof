# 阶段 4A 发现

## 现有实现

- `_RawConfig.paper_paths` 已存在，但 `YamlConfigurationRepository` 验证后丢弃；`ProjectConfiguration` 尚未保存。
- `SourceLocation` 已有行、列、结束位置和字符范围。
- `NumericValue` 目前保存 `raw_text` 与有限 `Decimal`。
- `Evidence`、`InputDiagnostic`、稳定诊断排序和退出码可直接复用。
- 固定资源限制集中于 `src/metricproof/adapters/limits.py`。
- `pylatexenc 2.10` 已安装，但精确屏蔽和恢复更适合本阶段的小型状态机。

## 计划模型

- `NumericKind`、`NumericUnit`
- `LatexSyntacticContext`、`NumericCandidateKind`
- `RawNumericCandidate`
- `LatexSourceDocument`、`LatexIncludeEdge`、`LatexSourceGraph`
- `PaperScanStatistics`、`PaperScanResult`
- `PaperScanner` 端口和 `scan_paper` 应用服务

## 扫描边界

- 精确支持 `\input{}`、`\include{}` 和省略 `.tex`。
- 屏蔽注释、verbatim、Verbatim、lstlisting、minted 和 `\verb`。
- 不展开自定义宏，不读取 minted 展示的代码文件。
- plain URL、文件名、版本号、命令名和十六进制颜色不生成普通候选。
- 候选保留入口集合、实际文件、规范 include 链、环境栈、最近命令和有限前后文。
