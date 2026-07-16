"""File size benchmark — rule-based adapter, direct call (no server)."""
import time, statistics, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.adapters.rule_based import RuleBasedAdapter
from src.schemas import ReviewRequest, SourceInfo, ContentBlock, FileEntry, SourceKind
import asyncio

adapter = RuleBasedAdapter()
sizes = [100, 500, 1000, 3000]
repeats = 5

TEMPLATE = [
    "def func_{i}(x):",
    "    \"\"\"Function {i}.\"\"\"",
    "    if x < 0:",
    "        raise ValueError(f\"Negative: {{x}}\")",
    "    result = x * {i}",
    "    for j in range(10):",
    "        result += j * 0.1",
    "    return result",
    "",
]

def make_content(n_lines):
    blocks = []
    i = 0
    while len(blocks) < n_lines:
        for line in TEMPLATE:
            blocks.append(line.format(i=i))
            if len(blocks) >= n_lines:
                break
        i += 1
    return "\n".join(blocks[:n_lines])

async def bench(n_lines, n_runs):
    content = make_content(n_lines)
    req = ReviewRequest(
        request_id="bench", model_id="rule-based",
        source=SourceInfo(kind=SourceKind.file, files=["bench.py"]),
        content=ContentBlock(files=[FileEntry(path="bench.py", language="python", content=content)]),
    )
    timings = []
    for _ in range(n_runs):
        t0 = time.perf_counter()
        await adapter.review(req)
        timings.append((time.perf_counter() - t0) * 1000)

    warm = sorted(timings[1:])  # drop cold
    return {
        "lines": n_lines, "bytes": len(content.encode("utf-8")),
        "median_ms": round(warm[len(warm)//2], 1),
        "p95_ms": round(warm[min(int(len(warm)*0.95), len(warm)-1)], 1),
        "mean_ms": round(statistics.mean(warm), 1),
        "runs": len(warm),
    }

print("File Size Benchmark (rule-based adapter)\n")
results = []
for sz in sizes:
    r = asyncio.run(bench(sz, repeats))
    results.append(r)
    print(f"  {r['lines']:>5} lines  |  median={r['median_ms']:>8.1f}ms  P95={r['p95_ms']:>8.1f}ms  mean={r['mean_ms']:>8.1f}ms")

# Save
out = os.path.join(os.path.dirname(__file__), "..", "results", "performance", "file_size_benchmark.csv")
os.makedirs(os.path.dirname(out), exist_ok=True)
with open(out, "w") as f:
    f.write("Lines,Bytes,Repeats,Median_ms,P95_ms,Mean_ms\n")
    for r in results:
        f.write(f"{r['lines']},{r['bytes']},{r['runs']},{r['median_ms']},{r['p95_ms']},{r['mean_ms']}\n")
print(f"\nSaved: {out}")
