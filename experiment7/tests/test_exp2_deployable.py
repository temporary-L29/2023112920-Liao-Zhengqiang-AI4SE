"""Regression tests for the retrained Experiment 2 CLI models."""

from fastapi.testclient import TestClient

from src.deployable_features import DEPLOYABLE_FEATURE_NAMES, build_features_from_diff
from src.server import app


DIFF = """diff --git a/src/example.py b/src/example.py
index 1111111..2222222 100644
--- a/src/example.py
+++ b/src/example.py
@@ -1,2 +1,9 @@
+def calculate(values):
+    total = 0
+    for value in values:
+        if value < 0:
+            continue
+        total += value
+    return total
"""


def test_deployable_feature_vector_has_fixed_schema():
    vector = build_features_from_diff(DIFF, large_churn_threshold=100.0)
    assert vector.shape == (1, len(DEPLOYABLE_FEATURE_NAMES))
    assert vector[0, DEPLOYABLE_FEATURE_NAMES.index("ast_files_attempted")] == 1
    assert vector[0, DEPLOYABLE_FEATURE_NAMES.index("cfg_files_processed")] == 1


def test_deployable_rf_reviews_git_diff():
    client = TestClient(app)
    response = client.post("/v1/reviews", json={
        "request_id": "deployable-rf-001",
        "model_id": "exp2-rf-deployable",
        "source": {"kind": "git_diff", "repo_path": "/tmp/example"},
        "content": {"diff": DIFF, "files": [{"path": "src/example.py", "language": "python"}]},
    })
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["model"]["id"] == "exp2-rf-deployable"
    assert 0.0 <= payload["merge_probability"] <= 1.0
