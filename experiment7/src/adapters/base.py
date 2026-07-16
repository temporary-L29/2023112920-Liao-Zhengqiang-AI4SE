"""
Abstract adapter interface.

Every model adapter (rule-based, LLM, ML) must implement this protocol.
The review service only depends on this ABC — never on concrete adapters.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional

from src.schemas import ReviewRequest, ReviewResponse, ModelInfo


class BaseAdapter(ABC):
    """Abstract review-model adapter."""

    @property
    @abstractmethod
    def model_info(self) -> ModelInfo:
        """Return static metadata about this model."""
        ...

    @abstractmethod
    async def review(self, request: ReviewRequest) -> ReviewResponse:
        """
        Execute a review and return a fully populated ReviewResponse.

        Must NOT raise — on failure, return an ErrorResponse-compatible
        structure that the service layer can wrap.
        """
        ...

    async def health(self) -> Dict[str, Any]:
        """Optional health check.  Default: reports model_info.status."""
        return {
            "model_id": self.model_info.id,
            "status": self.model_info.status.value,
            "reason": self.model_info.reason,
        }
