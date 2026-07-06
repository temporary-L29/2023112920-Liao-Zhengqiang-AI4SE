# 实验二：基于机器学习的人类编写代码代码审查

## 概述

实验二在实验一构建的 1500 条 GitHub Pull Request 数据集基础上，采用传统机器学习方法完成 Merge Prediction（预测 PR 是否会被合并）。

### 核心结果

| 实验 | 模型 | Accuracy | F1 | ROC-AUC |
|------|------|----------|-----|---------|
| 主实验 (无审查信息) | SVM | 0.7238 | 0.7786 | 0.7788 |
| 主实验 (无审查信息) | **Random Forest** | **0.7429** | **0.8200** | **0.8062** |
| 上界实验 (含审查信息) | SVM | 0.8619 | 0.8945 | 0.9111 |
| 上界实验 (含审查信息) | Random Forest | 0.9000 | 0.9213 | 0.9546 |

- 主实验明显超过 Dummy baseline (Acc=0.64)
- 上界实验显著更高，验证了审查过程特征的后验信息泄漏
- 文本特征（PR 描述长度、Commit Message 长度）是最重要的预测因子
- AST/CFG 结构特征有正向贡献但提升有限（符合 patch 片段局限性的预期）

---

## 运行说明

### 环境要求

```bash
pip install pandas numpy scikit-learn matplotlib seaborn joblib tree-sitter tree-sitter-python tree-sitter-javascript tree-sitter-typescript tree-sitter-go
```

### 完整运行

```bash
cd experiments/experiment2
python src/run_all.py
```

### 分步运行

```bash
python src/run_all.py --step filter     # 仅数据筛选
python src/run_all.py --step split      # 仅数据划分
python src/run_all.py --step patch      # 仅 Patch 索引
python src/run_all.py --step ast        # 仅 AST 提取
python src/run_all.py --step cfg        # 仅 CFG 构建
python src/run_all.py --step features   # 仅特征工程
python src/run_all.py --step train      # 仅模型训练
python src/run_all.py --step eval       # 仅模型评估
python src/run_all.py --step visualize  # 仅可视化

# 恢复运行
python src/run_all.py --from-features   # 从特征工程开始
python src/run_all.py --train-only      # 仅训练
python src/run_all.py --eval-only       # 仅评估与可视化
```

### 预计耗时

| 步骤 | 时间 |
|------|------|
| 数据筛选 + 划分 + Patch 索引 | ~15s |
| AST 提取 | ~16s |
| CFG 构建 | ~5s |
| 特征工程 | ~2s |
| 模型训练 (GridSearch) | ~30s |
| 评估 + 可视化 | ~10s |
| **总计** | **~80s** |

---

## 项目结构

```
experiment2/
├── README.md
├── 计划书.md
├── src/
│   ├── config.py               # 集中配置
│   ├── utils.py                # 工具函数
│   ├── data_filter.py          # 步骤一：数据筛选
│   ├── split_dataset.py        # 步骤二：数据划分
│   ├── patch_indexer.py        # 步骤三：Patch 索引
│   ├── ast_extractor.py        # 步骤四：AST 提取
│   ├── cfg_extractor.py        # 步骤五：CFG 构建
│   ├── feature_extractor.py    # 步骤六：特征工程
│   ├── model_trainer.py        # 步骤七：模型训练
│   ├── model_evaluator.py      # 步骤八：模型评估
│   ├── visualizer.py           # 步骤九：可视化
│   └── run_all.py              # 全流程编排
├── results/
│   ├── processed/              # 处理后数据
│   ├── models/                 # 训练好的模型
│   └── evaluation/             # 评估结果
├── figures/                    # 10 张图表
├── docs/                       # LaTeX 报告源文件
└── report/                     # 编译后的 PDF
```

---

## 关键设计决策

1. **防止信息泄漏**：主实验不使用审查结论、审阅者数量、标签等后验信息
2. **Patch 级简化 AST/CFG**：因 PR patch 只有局部代码行，构建的是近似结构特征
3. **统一数据划分**：train/val/test = 70/15/15，按 repo+is_merged 分层，供后续实验复用
4. **主实验 + 上界实验**：两套特征矩阵，分别对应"提交时可获得的信息"和"审查过程可见的信息"
