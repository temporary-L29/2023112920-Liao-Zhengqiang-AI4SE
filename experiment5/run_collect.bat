@echo off
REM 实验五 - 增强数据采集启动脚本
REM 多线程采集 AI 生成代码 PR（目标 300 条）

cd /d "%~dp0"
echo ============================================================
echo  实验五: Enhanced 数据采集
echo  目标: 300 条 AI 生成代码 PR
echo  多线程: 8 workers
echo ============================================================
echo.

python src\run_all.py --collect-ai --max-samples 300

echo.
echo 采集完成，按任意键继续...
pause >nul
