# 实验五：针对大模型生成代码的代码审查

## 概述

实验五测试实验二（传统机器学习）和实验四（DeepSeek LLM）在 **AI 生成代码 PR** 上的零样本泛化能力。模型不做任何修改，直接用于预测 AI 代码 PR 的合并结果。

> **状态**：全部实验已完成 ✓。包括 2.6.1 低成本默认组合（P2_C3/P2_C4 on full-343）和 2.6.2 4×4 Prompt×Context 全组合基线（16 combos on 50-sample）。

### 核心问题

> 人类代码上训练的模型，能直接用于 AI 代码审查吗？

### 核心结果

#### 传统 ML + 默认 LLM（343 条全集）

| 模型 | Accuracy | F1 | ROC-AUC | 关键问题 |
|------|----------|-----|---------|---------|
| SVM | 0.6851 | 0.7923 | 0.7014 | Recall 0.92，偏向合并 |
| Random Forest | 0.6560 | 0.7923 | 0.6838 | Recall **1.00**，全预测 merged |
| DeepSeek P2_C3 | 0.7041 | 0.8127 | 0.5813 | Recall 0.98，FP=96 |
| DeepSeek P2_C4 | 0.6932 | 0.8067 | 0.6324 | Recall 0.97，FP=98 |

#### 4×4 Prompt×Context 全组合（50 条样本，§2.6.2）

| Top-5 | 组合 | F1 | Acc | AUC | 特点 |
|-------|------|-----|-----|-----|------|
| 1 | **B14** P4_C2 (CoT + PR Desc) | **0.7059** | 0.60 | 0.588 | 最佳 F1 |
| 2 | B15 P4_C3 (CoT + Commit) | 0.6957 | 0.58 | 0.633 | 最佳 AUC |
| 3 | B04 P1_C4 (Zero-shot Full) | 0.6857 | 0.56 | 0.635 | Zero-shot 基线 |
| 4 | B02 P1_C2 (Zero-shot + PR) | 0.6857 | 0.56 | 0.570 | 简单有效 |
| 5 | B06 P2_C2 (Few-shot + PR) | 0.6857 | 0.56 | 0.521 | Few-shot 无额外收益 |

**关键发现**：
- P4 (Chain-of-Thought) 在 AI 代码上表现最佳
- C2 (+PR Description) 是最关键的上下文信息
- P2 (Few-shot) 因示例来自人类代码，在 AI 代码上无明显优势
- 所有组合 Recall ≥ 0.80，模型系统性偏向预测 "merged"

**表面指标平稳，深层能力下降**——F1 不低是因为模型一律预测 merged，而 AI PR 合并率 65.6%。AUC 下降（RF −12pp）和 Specificity 极低（0.14）才反映真实问题。

### 数据集

- **343 条 AI 生成代码 PR**（97 seed + 增强采集 + 修复）
- 6 个仓库：pandas(84), transformers(82), vscode(60), kubernetes(54), react(52), langchain(11)
- 合并率 65.6%，评论覆盖率 56.3%

---

## 运行说明

### 环境要求

```bash
pip install pandas numpy scikit-learn matplotlib openai
```

### 完整运行

```bash
cd experiments/experiment5

# 第一部分：数据采集
python src/run_all.py --all-data

# 第二部分：具体实验
python src/run_all.py --build-features      # 特征构建
python src/run_all.py --run-ml              # 传统 ML
python src/run_all.py --run-llm             # DeepSeek P2_C3/P2_C4 (686 次调用)
python src/run_all.py --run-llm-4x4         # 4×4 全组合基线 (800 次调用, §2.6.2)
python src/run_all.py --evaluate            # 评估
python src/run_all.py --visualize           # 生成图表 (含 4×4 热力图)
```

### DeepSeek API 调用

```bash
# 设置 API Key
export DEEPSEEK_API_KEY="your-key"

# 2.6.1 默认组合 (P2_C3/P2_C4 × 343 PR)
python src/run_all.py --dry-run-llm         # 生成任务列表
python src/run_all.py --run-llm --limit-llm 4   # Smoke test
python src/run_all.py --run-llm                  # 完整运行 686 次

# 2.6.2 4×4 全组合 (4 Prompt × 4 Context × 50 PR)
python src/run_all.py --dry-run-llm-4x4          # 生成任务列表 (800 任务)
python src/run_all.py --run-llm-4x4 --limit-llm-4x4 8  # Smoke test
python src/run_all.py --run-llm-4x4              # 完整运行 800 次 (~17 min)
```

---

## 项目结构

```
experiment5/
├── README.md
├── 计划书.md
├── src/
│   ├── config.py                   # 集中配置
│   ├── ai_data_collector.py        # AI PR 数据采集
│   ├── ai_dataset_builder.py       # 数据集构建
│   ├── ai_detection.py             # AI 痕迹检测
│   ├── feature_builder.py          # 特征工程
│   ├── llm_runner.py               # DeepSeek API 调用 (2.6.1)
│   ├── llm_4x4_runner.py           # 4×4 全组合实验 (2.6.2)
│   ├── traditional_ml_runner.py    # 传统 ML 预测
│   ├── evaluator.py                # 评估指标 (含 4×4)
│   ├── visualizer.py               # 图表生成 (含 4×4 热力图)
│   ├── merge_ai_datasets.py        # 数据集合并
│   ├── repair_dataset.py           # 数据集修复
│   └── run_all.py                  # 全流程编排
├── results/
│   ├── raw/                        # 原始 API 响应
│   ├── processed/                  # 数据集 + 特征 + 上下文
│   │   ├── ai_llm_sample_50.csv        # 4×4 抽样 50 条
│   │   └── ai_llm_4x4_task_list.json   # 4×4 任务清单
│   ├── predictions/                # LLM/ML 预测结果
│   │   ├── llm_4x4_raw_responses.jsonl     # 800 条原始响应
│   │   └── llm_4x4_parsed_predictions.csv  # 800 条解析预测
│   └── evaluation/                 # 评估指标 JSON
│       └── llm_4x4_metrics.json        # 16 组组合指标
├── figures/                        # 9 张图表
│   └── 09_llm_4x4_prompt_context_heatmap.png  # 4×4 热力图
├── docs/                           # LaTeX 报告源文件
└── report/                         # 编译后的 PDF
```

## 关键发现

1. **传统 ML 的 AUC 显著下降**（RF −12pp），人工特征对 AI 代码风格变化不够鲁棒
2. **DeepSeek 极度偏向预测 merged**，Recall 0.97+ 但 Specificity 仅 0.14
3. **P4 (Chain-of-Thought) 在 AI 代码上最优**，B14 (P4_C2) F1=0.706
4. **PR Description (C2) 是最关键的上下文**，在所有 Prompt 上一致优于 Diff Only
5. **Few-shot 对 AI 代码帮助有限**，人类代码示例与 AI 代码分布差异限制了迁移
6. **P3 (Role-based/维护者) 最保守**，Recall=0.80 但 Precision 更稳定
7. **为实验六指明方向**：需要更严格的风险识别 prompt + 上下文增强 + 针对 AI 代码的 few-shot 示例

## 性能变化原因分析

实验五相对实验四的性能下降不能简单归因于"AI 代码更难审查"，而是由以下因素共同造成：

### 1. 代码上下文信息量差异

AI PR 的 patch index 缺少 `added_lines` 和 AST/CFG 解析结果，导致 C1-C4 上下文显著薄于人类 PR：

| 上下文 | 人类 50-sample | AI 50-sample | 缩减 |
|--------|--------------|-------------|------|
| C1 (Diff Only) | ~2,750 chars | 551 chars | −80% |
| C4 (Full) | ~4,846 chars | 2,564 chars | −47% |

人类 C4 中 39/50 包含 AST/CFG 结构摘要，AI C4 完全不包含。模型在 AI PR 上实际可用的信息远少于人类 PR。

### 2. AI PR 特征分布偏移

| 特征 | 人类 50 | AI 50 |
|------|---------|-------|
| 平均修改文件数 | 4.68 | 6.24 |
| 平均新增行 | 177.8 | 321.8 |
| 平均删除行 | 32.9 | 140.9 |
| PR body 字符数 | 1,275 | 1,946 |
| 含测试文件 | 48% | 58% |

更重要的是特征含义发生了变化：AI 可以生成很完整的描述和测试，但 PR 仍可能因范围过大、维护成本或仓库政策被拒绝。"描述完整、包含测试"在 AI PR 上不再是可靠的合并信号。

### 3. 仓库对 AI 贡献的接受度差异

| 仓库 | AI PR 合并率 |
|------|------------|
| microsoft/vscode | 90.0% |
| pandas-dev/pandas | 79.8% |
| huggingface/transformers | 58.5% |
| kubernetes/kubernetes | 53.7% |
| facebook/react | 34.6% |

合并率差距达 55pp，而 C1-C4 上下文几乎不包含仓库政策信息，模型无法感知仓库对 AI 贡献的态度差异。

### 4. Few-shot 示例差异

实验五 P2 使用固定的 AI 工具相关示例（Copilot/GPT/Claude），与实验四使用的真实 validation PR 示例不同，可能使模型对 AI 关键词过度敏感而非学习代码质量判断。

### 小结

当前性能变化的最严谨解释是：在**代码上下文信息缩减**、**特征-标签关联偏移**、**仓库政策差异**和 **Few-shot 示例变化**共同形成的分布偏移下，实验四方法在 AI 代码上的 Accuracy/F1 下降。LLM 的 AUC 基本持平（−0.002），说明模型排序判别能力未显著退化；传统 ML 的 AUC 下降更明显（SVM −7.7pp, RF −12.2pp），反映人工特征对分布偏移更敏感。
