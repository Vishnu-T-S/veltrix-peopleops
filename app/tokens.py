"""Token counting with tiktoken's cl100k_base, as the brief requires.

The encoding's vocabulary file is vendored in vendor/tiktoken/ so counting never needs
the network (tiktoken would otherwise download it on first use). tiktoken checks the
file's hash on load, so a corrupted copy is rejected rather than silently used.
"""
from __future__ import annotations

import logging
import math
import os
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger("veltrix.tokens")

_VENDOR_DIR = Path(__file__).resolve().parent.parent / "vendor" / "tiktoken"
_VENDOR_FILE = _VENDOR_DIR / "9b5ad71b2ce5302211f9c61530b329a4922fc6a4"  # sha1 of the vocab URL


@lru_cache(maxsize=1)
def _encoding():
    try:
        import tiktoken

        if _VENDOR_FILE.exists():
            os.environ["TIKTOKEN_CACHE_DIR"] = str(_VENDOR_DIR)
        return tiktoken.get_encoding("cl100k_base")
    except Exception as exc:  # pragma: no cover - only when vocab is missing AND offline
        logger.error(
            "tiktoken cl100k_base unavailable (%s). Falling back to a conservative "
            "estimate (characters / 3), which over-counts, so budgets stay safe.",
            type(exc).__name__,
        )
        return None


def count_tokens(text: str) -> int:
    """Number of cl100k_base tokens in `text`."""
    if not text:
        return 0
    encoding = _encoding()
    if encoding is None:
        return math.ceil(len(text) / 3)
    # disallowed_special=() so text that merely looks like a special token is counted, not rejected
    return len(encoding.encode(text, disallowed_special=()))


def using_exact_counts() -> bool:
    return _encoding() is not None
