"""
Model registry — tracks all available adapters and resolves auto-selection.

Selection order for --model auto:
  ready LLM  →  ready deployable RF  →  ready deployable SVM  →  rule-based
"""

from __future__ import annotations

from typing import Dict, List, Optional

from src.adapters.base import BaseAdapter
from src.adapters.rule_based import RuleBasedAdapter
from src.adapters.exp6_llm import Exp6LLMAdapter
from src.adapters.exp2_ml import Exp2MLAdapter
from src.schemas import ModelInfo, ModelStatus


class ModelRegistry:
    """Holds all adapters and resolves model selection."""

    def __init__(self):
        # Always-available adapters
        self._rule = RuleBasedAdapter()

        # Optional adapters
        self._llm = Exp6LLMAdapter()
        self._rf = Exp2MLAdapter("exp2-rf")
        self._svm = Exp2MLAdapter("exp2-svm")
        self._deployable_rf = Exp2MLAdapter("exp2-rf-deployable")
        self._deployable_svm = Exp2MLAdapter("exp2-svm-deployable")

        self._all: Dict[str, BaseAdapter] = {
            "rule-based": self._rule,
            "exp6-llm": self._llm,
            "exp2-rf": self._rf,
            "exp2-svm": self._svm,
            "exp2-rf-deployable": self._deployable_rf,
            "exp2-svm-deployable": self._deployable_svm,
        }

    # ── Lookup ─────────────────────────────────────────────────

    def get(self, model_id: str) -> Optional[BaseAdapter]:
        return self._all.get(model_id)

    def resolve(self, model_id: str) -> BaseAdapter:
        """
        Resolve a model ID (or 'auto') to an adapter.

        Raises ValueError if the model is unavailable or unknown.
        """
        if model_id == "auto":
            return self._resolve_auto()

        adapter = self._all.get(model_id)
        if adapter is None:
            raise ValueError(f"Unknown model: {model_id}")

        if adapter.model_info.status == ModelStatus.unavailable:
            raise ValueError(
                f"Model {model_id} is unavailable: {adapter.model_info.reason}"
            )
        if adapter.model_info.status == ModelStatus.incompatible:
            raise ValueError(
                f"Model {model_id} is incompatible: {adapter.model_info.reason}"
            )

        return adapter

    def _resolve_auto(self) -> BaseAdapter:
        """Auto-select the best available model."""
        for mid in ["exp6-llm", "exp2-rf-deployable", "exp2-svm-deployable", "rule-based"]:
            adapter = self._all[mid]
            if adapter.model_info.status == ModelStatus.ready:
                return adapter
        return self._rule  # ultimate fallback

    # ── Status ─────────────────────────────────────────────────

    def list_models(self) -> List[ModelInfo]:
        return [a.model_info for a in self._all.values()]

    def get_health(self) -> dict:
        models = []
        for mid, adapter in self._all.items():
            info = adapter.model_info
            models.append({
                "id": info.id,
                "kind": info.kind,
                "status": info.status.value,
                "reason": info.reason,
            })
        return {"models": models}
