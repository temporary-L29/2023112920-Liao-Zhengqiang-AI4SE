# 实验七：命令行智能代码审查工具

命令行前端（CLI）+ 本地 Python HTTP 模型服务的智能代码审查工具。
经教师同意，以 CLI 等价替代指导书中的 VSCode 插件要求。

## 架构

```
开发者终端 → reviewctl CLI → HTTP JSON → FastAPI 本地服务
                                            ├── Rule-based 离线规则分析器（兜底）
                                            ├── 实验六 LLM 适配器（需 API Key）
                                            └── 实验二 ML 适配器（条件启用）
```

## 环境要求

- Python 3.10+
- Git（用于 diff 审查模式）
- Windows / Linux / macOS

## 安装

```powershell
cd E:\latex\projects\experiments\experiment7
pip install -r requirements.txt
```

## 环境变量（可选）

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `LLM_API_KEY` | （空） | DeepSeek API Key；不设置则 LLM 不可用 |
| `LLM_BASE_URL` | `https://api.deepseek.com` | API 地址 |
| `LLM_MODEL` | `deepseek-v4-flash` | 模型名称 |
| `REVIEW_HOST` | `127.0.0.1` | 服务监听地址 |
| `REVIEW_PORT` | `8765` | 服务监听端口 |

**安全提醒：** 不要将 API Key 提交到 Git。使用环境变量或 `.env` 文件（已在 `.gitignore` 中忽略）。

## 快速开始

### 1. 启动服务

```powershell
python -m src.cli serve
```

### 2. 新终端 — 查看状态

```powershell
python -m src.cli status
```

### 3. 审查文件

```powershell
python -m src.cli review --file .\tests\fixtures\risky_example.py --model rule-based
```

### 4. 审查 Git 工作区

```powershell
python -m src.cli review --repo <your-git-repo> --model rule-based
```

### 5. 查看历史

```powershell
python -m src.cli history --limit 10
python -m src.cli history --id <history-id>
```

## 模型说明

| 模型 ID | 类型 | 状态 | 说明 |
|---------|------|------|------|
| `rule-based` | 离线规则 | 始终可用 | 基于启发式规则的兜底模型 |
| `exp6-llm` | LLM | 需 API Key | 实验六 P8 策略，DeepSeek API |
| `exp2-rf` / `exp2-svm` | 原始实验二模型 | 不兼容 CLI | 61 维 PR 级模型，保留用于实验二结果，不接受本地输入 |
| `exp2-rf-deployable` | 随机森林 | 训练后可用 | 实验二数据集重训练的 45 维 Git diff 模型 |
| `exp2-svm-deployable` | SVM | 训练后可用 | 实验二数据集重训练的 45 维 Git diff 模型 |

训练部署兼容模型：

```powershell
python -m src.train_exp2_deployable
```

它会将模型、预处理器、特征顺序和测试集指标写入
`results/models/exp2_deployable/`，不修改 `experiment2/results/models/`。
部署模型仅支持 `--repo` Git diff 模式：

```powershell
python -m src.cli review --repo <your-git-repo> --model exp2-rf-deployable
```

`--model auto` 选择顺序：ready LLM → ready deployable RF → ready deployable SVM → rule-based

## 运行测试

```powershell
cd E:\latex\projects\experiments\experiment7
pytest -q
```

## 运行 ML 兼容性检查

```powershell
python -m src.ml_compatibility_check
```

## 项目结构

```
experiment7/
├── README.md
├── requirements.txt
├── src/
│   ├── config.py                  # 路径、端口、环境变量
│   ├── schemas.py                 # Pydantic 请求/响应 schema
│   ├── server.py                  # FastAPI 路由
│   ├── cli.py                     # CLI 客户端（纯 HTTP）
│   ├── review_service.py          # 审查编排
│   ├── input_extractors.py        # 文件/Git diff 提取
│   ├── risk_analyzer.py           # 离线规则引擎
│   ├── history_store.py           # JSONL 历史存储
│   ├── model_registry.py          # 模型注册与选择
│   ├── ml_compatibility_check.py  # 实验二特征契约预检
│   └── adapters/
│       ├── base.py                # 抽象接口
│       ├── rule_based.py          # 规则适配器
│       ├── exp6_llm.py            # LLM 适配器
│       └── exp2_ml.py             # ML 适配器
├── tests/
│   ├── fixtures/                  # 测试用源文件
│   ├── test_schemas.py
│   ├── test_extractors.py
│   ├── test_risk_analyzer.py
│   ├── test_history_store.py
│   ├── test_api.py
│   └── test_cli.py
├── results/                       # 运行时输出
├── figures/                       # 截图和图表
├── scripts/                       # 演示和基准脚本
├── docs/                          # LaTeX 报告源文件
└── report/                        # 编译后的 PDF
```

## 退出码

| 码 | 含义 |
|----|------|
| 0 | 成功 |
| 2 | 命令参数或输入错误 |
| 3 | 服务不可达 |
| 4 | 指定模型不可用 |
| 5 | 模型执行或响应解析失败 |

## 许可证

教学用途，无许可证。
