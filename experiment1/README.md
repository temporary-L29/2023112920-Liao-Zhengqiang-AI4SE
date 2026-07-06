# 实验一：代码审查数据集构建

## 项目介绍

本实验是"智能软件工程"课程系列实验（共 7 个实验）的第一步，核心任务是构建一个**包含丰富信息的代码审查数据集**，该数据集将作为后续所有实验（Merge Prediction、Review Comment Generation 等）的唯一数据来源。

### 数据来源

通过 GitHub REST API v3 从 5 个大型开源项目采集 Pull Request 数据：

| 项目 | 领域 | 采集数 |
|------|------|--------|
| [Kubernetes](https://github.com/kubernetes/kubernetes) | 容器编排 | 300 |
| [PyTorch](https://github.com/pytorch/pytorch) | 深度学习框架 | 300 |
| [VS Code](https://github.com/microsoft/vscode) | 代码编辑器 | 300 |
| [TensorFlow](https://github.com/tensorflow/tensorflow) | 科学计算 | 300 |
| [React](https://github.com/facebook/react) | 前端框架 | 300 |

**总计：1500 条 PR，每条包含 26 个字段。**

### 采集字段

| 类别 | 字段 |
|------|------|
| PR 基本信息 | pr_id, pr_number, repo, title, body, pr_length, author, created_at |
| 合并信息 | is_merged, merge_status |
| 代码修改 | num_changed_files, total_additions, total_deletions, modified_functions, num_commits, commit_messages, changed_files_list |
| 审查信息 | num_reviewers, review_decision, num_review_comments, num_inline_comments, review_comments_text |
| 元标签 | num_labels, label_names, has_ai_reviewer, has_ai_generated_code |

### 产出物

| 文件 | 说明 |
|------|------|
| `results/processed/dataset.csv` | 结构化数据集（1500 × 26） |
| `results/processed/dataset.json` | JSON 格式完整数据 |
| `results/processed/dataset_stats.txt` | 统计报告 |
| `figures/*.png` | 6 张分析图表（300 DPI） |
| `report/main.pdf` | LaTeX 实验报告 |

---

## 运行说明

### 环境要求

- Python 3.10+
- 依赖库：`requests`, `pandas`, `matplotlib`, `seaborn`, `numpy`

### 运行

进入项目目录：

```bash
cd experiments/experiment1
```

**完整流水线（采集 → 特征提取 → 分析 → 可视化）：**

```bash
python src/run_all.py
```

**分步执行：**

```bash
python src/run_all.py --collect      # 仅采集数据（约 15 分钟）
python src/run_all.py --from-extract # 跳过采集，从特征提取开始
python src/run_all.py --analyze      # 仅统计分析
python src/run_all.py --visualize    # 仅可视化
```

### 采集策略

- 只采集 `state=closed` 的 PR（确保合并状态明确）
- 按创建时间降序排列，每仓库 300 条
- 不强制 merged/unmerged 比例，反映仓库自然分布
- 3 线程并行采集，支持断点续传

---

## 项目结构

```
experiments/experiment1/
├── src/                      # Python 源码
│   ├── config.py             # 集中配置
│   ├── utils.py              # 工具库（限速、请求、分页）
│   ├── collector.py          # 数据采集引擎
│   ├── feature_extractor.py  # 特征提取
│   ├── analyzer.py           # 统计分析
│   ├── visualizer.py         # 可视化
│   └── run_all.py            # 流水线编排
├── results/
│   ├── processed/            # 数据集 CSV/JSON + 统计报告
│   ├── raw/                  # 原始 API 数据（不纳入版本控制）
│   └── checkpoints/          # 断点续传状态
├── figures/                  # 图表输出
├── docs/                     # LaTeX 模板
│   ├── experimentreport.cls
│   └── listing_style.tex
└── report/
    ├── main.tex              # 实验报告 LaTeX 源文件
    └── main.pdf              # 编译后的 PDF
```
