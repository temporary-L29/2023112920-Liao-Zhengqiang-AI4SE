# 实验六：改进针对大模型生成代码的代码审查

## 概述

实验六承接实验五，在同一批 50 条平衡 AI 生成代码 PR 上，对比实验五原始方法 `B01-B16` 与实验六改进方法 `I01-I16`。不重新训练 DeepSeek，只通过增强 PR 上下文和优化审查 Prompt，降低模型“默认预测 merged”的过度乐观倾向。

统一应用场景是 PR 刚提交时的早期预测：输入只使用 title、body、commit、changed files、diff/patch 和可从历史记录获得的仓库背景；当前 PR 的 merge 结果、review decision、评论数和真实 review comment 均不作为输入。

## 主实验结果

| 目标 | 实验五最佳基线 | 实验六最佳组合 | 结果 |
|---|---|---|---|
| 综合分类 | B14: P4+C2，F1=0.7059 | **I14: P8+C6，F1=0.7547** | F1、Precision、Specificity 同时提升 |
| 概率排序 | B04: P1+C4，AUC=0.6352 | **I07: P6+C7，AUC=0.7358** | 相似历史案例提升排序能力 |
| 识别 unmerged | B12: P3+C4，Spec=0.3600 | **I16: P8+C8，Spec=0.6667** | FPR 从 0.6400 降至 0.3333 |

与实验五 F1 最佳基线 B14 相比：

| 指标 | B14 | I14 | I16 |
|---|---:|---:|---:|
| Accuracy | 0.6000 | **0.7234** | 0.6735 |
| F1 | 0.7059 | **0.7547** | 0.6800 |
| ROC-AUC | 0.5880 | 0.6927 | **0.7075** |
| Specificity | 0.2400 | 0.6364 | **0.6667** |
| FPR | 0.7600 | 0.3636 | **0.3333** |
| Balanced Accuracy | 0.6000 | **0.7182** | 0.6733 |

## 实验六做了什么

### 上下文增强

| Context | 新增信息 | 作用 |
|---|---|---|
| C5 Risk Checklist | 测试缺失、修改范围、配置/API/文档风险、AI 工具痕迹 | 将隐含风险转为显式审查证据 |
| C6 Repository Policy | 仓库 AI PR 历史合并率、常见未合并模式、审查政策与风格摘要 | 按仓库环境校准合并概率 |
| C7 Historical Similar PR | 3 条按仓库、规模、title 相似度检索的历史案例 | 为当前 PR 提供可类比的决策参考 |
| C8 Full Improved | C5+C6+C7 与当前 PR 变更信息 | 提高对未合并 PR 的风险覆盖 |

### Prompt 优化

| Prompt | 核心修改 | 观察到的效果 |
|---|---|---|
| P5 AI-Risk-Aware | 显式寻找 AI 代码风险，并输出 `risk_factors`、`unmerged_risk_score` | 平均 F1 最高，适合温和校准 |
| P6 Contrastive | 要求权衡 merge/reject 两侧证据 | P6+C7 的 AUC 最高 |
| P7 Self-Reflection | 初判后检查是否过度乐观并校准 | 能改善部分风险识别，但弱于硬规则 |
| P8 Strict Maintainer | 缺测试、核心/API 变更、描述不足和 blocker 风险会显著降低概率 | Specificity 平均值最高，打破 merged 偏置 |

## 为什么效果提升

实验五的最佳 F1 组合 B14 将 43/50 条 PR 预测为 merged，Specificity 仅为 0.24。实验六的改进来自两侧协同：

- C5-C8 向模型提供结构化风险、仓库历史背景和相似历史案例，补足“当前 PR 看起来合理”之外的合并决策证据。
- P8 重新定义判断标准，明确要求对缺测试、大范围修改、核心/API 风险和 blocker 降低 `merge_probability`，并强制输出 `risk_factors`。
- I14 将平均 merge probability 从 B14 的 0.8104 降至 0.6096，False Positive 从 19 降到 8。
- I16 的输出接近平衡，识别出 16 个真实 unmerged PR，说明完整风险上下文与严格 Prompt 能有效降低过度乐观。

评论生成也更面向实际审查：I14 的风险覆盖率为 1.000、可执行性为 0.930；I16 的 Blocker+Major 评论占比为 51.0%。

## 使用边界

仓库背景和相似历史 PR 只能使用目标 PR 提交前已完成的记录。生产环境必须按时间过滤历史数据，并由 maintainer 对模型输出进行最终判断。

## 运行

```bash
cd experiment6

# 构建 C5-C8 上下文与 I01-I16 任务
python src/run_all.py --prepare --build-contexts

# Smoke test
python src/run_all.py --run-llm --suite improved-4x4 --limit 4

# 主实验：16 个改进组合 × 50 条 PR = 800 次调用
python src/run_all.py --run-llm --suite improved-4x4
python src/run_all.py --evaluate --suite improved-4x4
python src/run_all.py --compare-baseline
python src/run_all.py --visualize --report
```

## 目录

```text
experiment6/
├── README.md
├── 计划书.md
├── src/
│   ├── enhanced_context_builder.py
│   ├── improved_prompt_templates.py
│   ├── llm_runner.py
│   ├── evaluator.py
│   └── run_all.py
├── results/
│   ├── processed/
│   ├── responses/
│   └── evaluation/
├── figures/
├── docs/
│   ├── main.tex
│   └── 实验六相对实验五性能提升原因分析.md
└── report/main.pdf
```
