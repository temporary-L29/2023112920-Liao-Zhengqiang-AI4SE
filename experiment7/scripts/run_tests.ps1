# Experiment 7 Test Script
# Run from experiment7 directory

Write-Host "Running experiment 7 tests..." -ForegroundColor Cyan

cd $PSScriptRoot\..

python -m pytest tests/test_schemas.py tests/test_risk_analyzer.py tests/test_extractors.py tests/test_history_store.py tests/test_api.py -v 2>&1 | Tee-Object -FilePath results/tests/pytest.txt

Write-Host "`nTest results saved to results/tests/pytest.txt" -ForegroundColor Green
