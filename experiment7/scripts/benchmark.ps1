# Experiment 7 Performance Benchmark Script
# Creates generated test files of various sizes and benchmarks rule-based model

param(
    [int]$Repeats = 5
)

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectDir = Split-Path -Parent $ScriptDir
$GenDir = Join-Path $ProjectDir "tests\fixtures\generated"
$ResultsFile = Join-Path $ProjectDir "results\performance\file_size_benchmark.csv"
$ServerUrl = "http://127.0.0.1:8765"

# Ensure generated directory exists
New-Item -ItemType Directory -Force -Path $GenDir | Out-Null

# Sizes to test (lines)
$Sizes = @(100, 500, 1000, 3000)
$Seed = 42

Write-Host "Generating test files..." -ForegroundColor Cyan

# Create files with deterministic content
# Uses @@ as placeholder to avoid PowerShell -f clash with Python {} / {x}
$PythonLines = @(
    "def func_@@(x):",
    "    '''Compute value for input x.'''",
    "    if x < 0:",
    "        raise ValueError(f'Negative input: {x}')",
    "    result = x * @@ + @@",
    "    # Processing step",
    "    for i in range(10):",
    "        result += i * 0.1",
    "    # Validation",
    "    if result > 1000:",
    "        result = 1000",
    "    return result",
    "",
    "",
    "class Processor_@@:",
    "    def __init__(self, factor=@@):",
    "        self.factor = factor",
    "        self.cache = {}",
    "",
    "    def process(self, data):",
    "        if not data:",
    "            return []",
    "        results = []",
    "        for item in data:",
    "            key = hash(item) % 1000",
    "            if key in self.cache:",
    "                results.append(self.cache[key])",
    "            else:",
    "                val = item * self.factor",
    "                self.cache[key] = val",
    "                results.append(val)",
    "        return results",
    "",
    "",
    "def test_processor_@@():",
    "    p = Processor_@@(factor=2)",
    "    assert p.process([1, 2, 3]) == [2, 4, 6]",
    "    assert p.process([]) == []",
    "",
    "",
    "if __name__ == '__main__':",
    "    import sys",
    "    p = Processor_@@(factor=int(sys.argv[1]) if len(sys.argv) > 1 else 1)",
    "    print(p.process([1, 2, 3, 4, 5]))",
    ""
)

foreach ($size in $Sizes) {
    $content = "# Generated test file - ${size} lines`n# Seed: $Seed`n`n"
    $blocks = [Math]::Ceiling($size / $PythonLines.Count)
    for ($b = 0; $b -lt $blocks; $b++) {
        foreach ($line in $PythonLines) {
            $content += $line.Replace('@@', $b) + "`n"
        }
    }
    # Trim to exact line count
    $lines = $content -split "`n"
    $content = ($lines[0..($size-1)] -join "`n") + "`n"

    $filePath = Join-Path $GenDir "bench_${size}lines.py"
    $content | Out-File -FilePath $filePath -Encoding utf8
    Write-Host "  Created: $filePath ($((Get-Item $filePath).Length) bytes)" -ForegroundColor Gray
}

Write-Host "`nRunning benchmarks ($Repeats repeats each)..." -ForegroundColor Cyan

# Check server
try {
    $null = Invoke-RestMethod -Uri "$ServerUrl/health" -TimeoutSec 3
} catch {
    Write-Host "ERROR: Server not running at $ServerUrl" -ForegroundColor Red
    Write-Host "Start with: python -m src.cli serve" -ForegroundColor Yellow
    exit 1
}

$Results = @()

foreach ($size in $Sizes) {
    $filePath = Join-Path $GenDir "bench_${size}lines.py"
    Write-Host "  Benchmarking ${size}-line file..." -ForegroundColor Yellow

    $timings = @()
    for ($i = 1; $i -le $Repeats; $i++) {
        $out = python -m src.cli review --file $filePath --model rule-based --format json --no-color 2>&1
        try {
            $data = $out | ConvertFrom-Json
            $totalMs = $data.timing.total_ms
            $timings += $totalMs
            Write-Host "    Run $i : $totalMs ms" -ForegroundColor Gray
        } catch {
            Write-Host "    Run $i : FAILED - $out" -ForegroundColor Red
        }
    }

    if ($timings.Count -ge 2) {
        # Drop first (cold start)
        $warm = $timings[1..($timings.Count - 1)]
        $sorted = $warm | Sort-Object
        $median = $sorted[[Math]::Floor($sorted.Count / 2)]
        $p95Index = [Math]::Floor($sorted.Count * 0.95)
        if ($p95Index -ge $sorted.Count) { $p95Index = $sorted.Count - 1 }
        $p95 = $sorted[$p95Index]
        $mean = ($warm | Measure-Object -Average).Average

        $Results += [PSCustomObject]@{
            Lines = $size
            Bytes = (Get-Item $filePath).Length
            Repeats = $warm.Count
            Median_ms = [Math]::Round($median, 2)
            P95_ms = [Math]::Round($p95, 2)
            Mean_ms = [Math]::Round($mean, 2)
        }

        Write-Host "    Results: median=$([Math]::Round($median,1))ms, P95=$([Math]::Round($p95,1))ms" -ForegroundColor Green
    }
}

# Save results
$Results | Export-Csv -Path $ResultsFile -NoTypeInformation -Encoding UTF8
Write-Host "`nBenchmark results saved to: $ResultsFile" -ForegroundColor Green
$Results | Format-Table -AutoSize
