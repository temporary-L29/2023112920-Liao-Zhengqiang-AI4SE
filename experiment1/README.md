# 实验一：代码审查数据集构建

## 项目介绍

"智能软件工程"课程系列实验（共 7 个）的第一步，构建代码审查数据集，作为后续所有实验（Merge Prediction、Review Comment Generation 等）的数据来源。

### 数据来源

通过 GitHub REST API v3 从 5 个大型开源项目随机采集已关闭（closed）的 Pull Request：

| 项目 | 领域 | 采集数 | 合并率 |
|------|------|--------|--------|
| [Kubernetes](https://github.com/kubernetes/kubernetes) | 容器编排 | 300 | 66.0% |
| [VS Code](https://github.com/microsoft/vscode) | 代码编辑器 | 300 | 87.3% |
| [React](https://github.com/facebook/react) | 前端框架 | 300 | 48.7% |
| [Transformers](https://github.com/huggingface/transformers) | 自然语言处理 | 300 | 55.3% |
| [Pandas](https://github.com/pandas-dev/pandas) | 数据分析 | 300 | 66.7% |

**总计：1500 条 PR，总体合并率 64.8%，每条 26 个字段。**

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
| `../raw/*.json` | 各仓库原始 API 响应（5 个 + merged_raw.json） |
| `results/processed/dataset.csv` | 结构化数据集（1500 × 26） |
| `results/processed/dataset.json` | JSON 格式完整数据 |
| `results/processed/dataset_stats.txt` | 统计报告 |
| `figures/*.png` | 6 张分析图表（300 DPI） |
| `docs/main.pdf` | LaTeX 实验报告 |

---

## 运行说明

### 环境要求

- Python 3.10+
- 依赖库：`requests`, `pandas`, `matplotlib`, `seaborn`, `numpy`

```bash
pip install requests pandas matplotlib seaborn numpy
```

### GitHub Token

GitHub API 匿名限制 60 次/小时，本实验约需 7500 次调用，需 Personal Access Token。

1. 访问 https://github.com/settings/tokens 生成 token（无需权限）
2. 放到 `experiment1/.token` 文件或 `GITHUB_TOKEN` 环境变量

### 运行

```bash
cd experiments/experiment1
python src/run_all.py              # 完整流水线
python src/run_all.py --collect    # 仅采集（~15 分钟）
python src/run_all.py --from-extract  # 跳过采集
```

### 采集策略

- 只采集 `state=closed`，确保合并结局明确
- 从大池中随机采样 300 条/仓库，避免时间集群效应
- 不强制 merged/unmerged 比例，反映仓库自然分布
- 每条 PR 并行拉取 5 个端点（详情 + reviews + comments + files + commits）
- 支持断点续传

---

## 项目结构

```
experiments/
├── raw/                          # 原始 API 数据（5 个仓库 + merged）
└── experiment1/
    ├── src/                      # Python 源码
    │   ├── config.py             # 集中配置
    │   ├── utils.py              # 工具库（限速、请求、分页）
    │   ├── collector.py          # 数据采集引擎
    │   ├── feature_extractor.py  # 特征提取
    │   ├── analyzer.py           # 统计分析
    │   ├── visualizer.py         # 可视化
    │   └── run_all.py            # 流水线编排
    ├── results/
    │   ├── processed/            # 数据集 + 统计报告
    │   └── checkpoints/          # 断点续传
    ├── figures/                  # 图表输出（6 张 PNG）
    └── docs/                     # LaTeX 报告
        ├── experimentreport.cls
        ├── listing_style.tex
        └── main.tex / main.pdf
```
