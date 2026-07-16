"""
Clean example — a well-structured Python module with no obvious issues.

Used to verify that the rule-based analyzer does not produce
false-positive warnings on clean code.
"""

from typing import List, Optional, Dict
import logging

logger = logging.getLogger(__name__)


def fibonacci(n: int) -> List[int]:
    """
    Generate the first n Fibonacci numbers.

    Args:
        n: Number of Fibonacci numbers to generate.

    Returns:
        List of the first n Fibonacci numbers.

    Raises:
        ValueError: If n is negative.
    """
    if n < 0:
        raise ValueError("n must be non-negative")
    if n == 0:
        return []
    if n == 1:
        return [0]

    result = [0, 1]
    for _ in range(2, n):
        result.append(result[-1] + result[-2])
    return result


def is_prime(num: int) -> bool:
    """
    Check if a number is prime.

    Args:
        num: The number to check.

    Returns:
        True if the number is prime, False otherwise.
    """
    if num < 2:
        return False
    for i in range(2, int(num ** 0.5) + 1):
        if num % i == 0:
            return False
    return True


class MathUtils:
    """Utility class for common mathematical operations."""

    def __init__(self, precision: int = 6):
        self.precision = precision
        logger.info("MathUtils initialized with precision=%d", precision)

    def round_value(self, value: float) -> float:
        """Round a value to the configured precision."""
        return round(value, self.precision)

    def average(self, values: List[float]) -> Optional[float]:
        """Calculate the average of a list of values."""
        if not values:
            logger.warning("average() called with empty list")
            return None
        return sum(values) / len(values)
