# Experiment 7 Demo Script
# Run from experiment7 directory

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Experiment 7: Code Review Tool Demo"
Write-Host "========================================" -ForegroundColor Cyan

# 1. Check Python and dependencies
Write-Host "`n[1/6] Checking environment..." -ForegroundColor Yellow
python --version
python -c "import fastapi, pydantic, rich; print('Dependencies OK')"

# 2. Start server in background
Write-Host "`n[2/6] Starting review server..." -ForegroundColor Yellow
Start-Process -NoNewWindow python -ArgumentList "-m", "src.server" -WorkingDirectory $PSScriptRoot\..
Start-Sleep -Seconds 3

# 3. Check status
Write-Host "`n[3/6] Checking service status..." -ForegroundColor Yellow
python -m src.cli status --no-color

# 4. Review a file
Write-Host "`n[4/6] Reviewing a Python file..." -ForegroundColor Yellow
python -m src.cli review --file .\tests\fixtures\risky_example.py --model rule-based --no-color

# 5. Review a clean file
Write-Host "`n[5/6] Reviewing a clean Python file..." -ForegroundColor Yellow
python -m src.cli review --file .\tests\fixtures\clean_example.py --model rule-based --no-color

# 6. View history
Write-Host "`n[6/6] Viewing review history..." -ForegroundColor Yellow
python -m src.cli history --limit 5 --no-color

Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host "  Demo Complete"
Write-Host "========================================" -ForegroundColor Cyan
