# 实验四：基于大语言模型的人类编写代码代码审查

## 概述

本实验模拟 **Pull Request 刚提交时** 的真实应用场景：根据 PR 提交时可获得的信息，
使用大语言模型（DeepSeek）预测该 PR 是否会被 merge，并生成初步代码审查意见。

### 实验设计

- **4 种 Prompt × 4 种上下文 × 50 条测试 PR = 800 次 API 调用**
- 数据来源：实验二的 test split
- LLM 后端：DeepSeek API（OpenAI 兼容接口）
- 每次调用同时完成两个任务：
  - **Merge Prediction**：预测 PR 是否可能被 merge
  - **Review Comment Generation**：生成初步代码审查意见

### 核心约束

**PR 刚提交时可用的信息**（可以进入 prompt）：
- PR title、body
- Commit messages
- Changed files list、diff/patch
- 即时计算的 AST/CFG/复杂度摘要
- 仓库名、文件类型、语言类型

**当前目标 PR 不可使用的信息**（严禁进入 prompt）：
- `is_merged`、`merge_status`、`review_decision`
- `num_reviewers`、`num_review_comments`、review comments
- `approved`、`lgtm`、`changes requested` 等审查后标签

## 项目结构

```
experiment4/
├── README.md
├── src/
│   ├── config.py            # 集中配置
│   ├── utils.py             # 工具函数
│   ├── sampler.py           # 数据抽样
│   ├── context_builder.py   # 上下文构建（C1-C4）
│   ├── prompt_templates.py  # Prompt 模板（P1-P4）
│   ├── api_caller.py        # API 调用框架
│   ├── evaluator.py         # 评估指标计算
│   ├── visualizer.py        # 图表生成
│   └── run_all.py           # 主入口脚本
├── prompts/                 # Prompt 模板文件
├── results/
│   ├── processed/           # 抽样结果、few-shot 示例
│   ├── responses/           # API 响应缓存
│   └── evaluation/          # 评估指标
├── figures/                 # 生成的图表
├── docs/                    # 文档
└── report/                  # LaTeX 报告
```

## 使用方法

### 1. 安装依赖

```bash
pip install pandas numpy scikit-learn matplotlib openai
# 可选：BLEU 计算
pip install nltk
```

### 2. 设置 API Key

```bash
export LLM_API_KEY="your-deepseek-api-key"
# 可选：自定义模型
export LLM_MODEL="deepseek-chat"
export LLM_BASE_URL="https://api.deepseek.com"
```

### 3. 运行实验

```bash
# Step 1: 数据准备（抽样 + 上下文构建）
python src/run_all.py --prepare

# Step 2: Dry-run 检查（验证数据质量，不调用 API）
python src/run_all.py --dry-run

# Step 3: Smoke test（只调用 3 次 API 验证流程）
python src/run_all.py --run-llm --limit 3

# Step 4: 完整 API 调用（800 次，支持断点续跑）
python src/run_all.py --run-llm

# Step 5: 计算评估指标
python src/run_all.py --evaluate

# Step 6: 生成图表
python src/run_all.py --visualize

# Step 7: 生成报告
python src/run_all.py --report
```

### 4. 一键运行

```bash
python src/run_all.py --all    # 运行除 API 调用外的所有步骤
```

## 上下文设计

| 类型 | 名称 | 包含内容 |
|------|------|---------|
| C1 | Diff Only | 文件路径 + unified diff |
| C2 | Diff + PR Description | C1 + PR title + PR body |
| C3 | Diff + PR Description + Commit | C2 + commit messages |
| C4 | Full Early Context | C3 + AST/CFG 摘要 + 规模统计 + 文件类型 |

## Prompt 设计

| 类型 | 名称 | 特点 |
|------|------|------|
| P1 | Zero-shot | 直接要求预测 |
| P2 | Few-shot | 4 个 validation split 示例 |
| P3 | Role-based | 设定资深 maintainer 角色 |
| P4 | Chain-of-Thought | 结构化分析流程 |

## 输出格式

所有 prompt 统一要求 JSON 输出：

```json
{
  "merge_prediction": "merged 或 not_merged",
  "merge_probability": 0.0,
  "confidence": "low/medium/high",
  "evidence_summary": "一句话说明预测依据",
  "review_comments": [
    {
      "file": "path or unknown",
      "line": null,
      "severity": "nit/minor/major/blocker",
      "comment": "review text"
    }
  ]
}
```

## 评价指标

### Merge Prediction
- Accuracy、Precision、Recall、F1-score
- ROC-AUC
- Confusion Matrix
- 平均推理时间
- JSON 解析失败率

### Review Comment Generation
- BLEU、ROUGE-1、ROUGE-2、ROUGE-L
- 平均生成评论数
- Severity 分布
- 最佳生成样例
- 无真实评论样本上模型是否仍生成评论

说明：真实 `review_comments_text` 只作为生成任务评价 reference，不进入目标 PR 的 prompt。

## 关键输出文件

- `results/processed/llm_sample_50.csv` — 50 条抽样 PR
- `results/processed/few_shot_examples.json` — Few-shot 示例
- `results/responses/raw_responses.jsonl` — API 响应缓存（断点续跑）
- `results/responses/parsed_predictions.csv` — 解析后的预测结果
- `results/evaluation/metrics_by_prompt_context.json` — Merge 预测指标
- `results/evaluation/comment_generation_metrics.json` — 评论生成指标
