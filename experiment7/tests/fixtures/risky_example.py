"""
Risky example file for testing the rule-based analyzer.

This file intentionally contains several code-review issues:
  - Missing tests (no test file alongside)
  - TODO markers
  - Debug prints
  - Public API without documentation
"""

import os
import sys


def calculate_risk_score(probability: float, impact: float) -> float:
    """
    Calculate a risk score from probability and impact.

    TODO: Add validation for negative inputs
    """
    print(f"DEBUG: calculate_risk_score called with p={probability}, i={impact}")
    if probability < 0 or impact < 0:
        # FIXME: This should raise an error, not silently clamp
        probability = max(0, probability)
        impact = max(0, impact)

    result = probability * impact
    print(f"DEBUG: result = {result}")
    return result


class RiskAnalyzer:
    """Public API class for risk analysis."""

    def __init__(self, threshold: float = 0.5):
        self.threshold = threshold
        print(f"Created RiskAnalyzer with threshold={threshold}")

    def analyze(self, data: list) -> dict:
        """Analyze risk data and return summary. HACK: quick implementation."""
        if not data:
            return {"status": "empty", "count": 0}

        total = sum(data)
        avg = total / len(data)
        high_risk = [x for x in data if x > self.threshold]

        return {
            "status": "analyzed",
            "count": len(data),
            "total": total,
            "average": avg,
            "high_risk_count": len(high_risk),
            "high_risk_items": high_risk,
        }


def main():
    """Main entry point. TODO: add CLI argument parsing."""
    analyzer = RiskAnalyzer(threshold=0.7)
    sample_data = [0.1, 0.3, 0.8, 0.9, 0.2, 0.95]
    result = analyzer.analyze(sample_data)
    print("Analysis result:", result)
    # XXX: Need to handle empty input properly
    return result


if __name__ == "__main__":
    main()
