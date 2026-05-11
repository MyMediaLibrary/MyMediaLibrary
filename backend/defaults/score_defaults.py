"""Re-export the scoring default configuration under the canonical defaults name."""

try:
    from backend.scoring import DEFAULT_SCORE_CONFIG as DEFAULT_SCORE_CONFIGURATION
except Exception:
    from scoring import DEFAULT_SCORE_CONFIG as DEFAULT_SCORE_CONFIGURATION  # type: ignore

__all__ = ["DEFAULT_SCORE_CONFIGURATION"]
