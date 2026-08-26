"""Structural provider policy."""

from __future__ import annotations


class PolicyViolation(RuntimeError):
    pass


def require_openai_remote_provider(provider: str) -> str:
    normalized = provider.strip().lower()
    if normalized != "openai":
        raise PolicyViolation(
            "QSOL-IBAE permits OpenAI as the only remote proprietary model provider"
        )
    return normalized
