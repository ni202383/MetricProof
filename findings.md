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

