@echo off
cd /d "%~dp0"

REM 设置 DeepSeek API Key
set LLM_API_KEY=sk-d7c5756a2c0e45b89287b606be77b4cd

echo ============================================================
echo  实验五 Part 2: 全部实验
echo ============================================================

echo.
echo [1/4] 评估 ML 结果 + 对比人类代码...
python src\run_all.py --evaluate
if errorlevel 1 echo 评估出错，继续...

echo.
echo [2/4] 生成图表 (8张)...
python src\run_all.py --visualize
if errorlevel 1 echo 图表出错，继续...

echo.
echo [3/4] LLM dry run (检查任务列表)...
python src\run_all.py --run-llm --dry-run-llm
if errorlevel 1 echo dry run出错，继续...

echo.
echo [4/4] LLM 实验 (P2_C3 + P2_C4, 多线程8workers)...
echo 预计调用次数: 343 PRs x 2 contexts = 686 次
echo 支持断点续传，可随时 Ctrl+C 中断后继续
echo.
python src\run_all.py --run-llm

echo.
echo ============================================================
echo  实验完成！再次运行 evaluate + visualize 更新图表:
echo  python src\run_all.py --evaluate --visualize
echo ============================================================
pause
