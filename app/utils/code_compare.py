"""Lightweight code comparison when LLM evaluation is unavailable."""

import re


def normalize_code(s: str) -> str:
    if not s:
        return ""
    # strip comments-ish lines loosely, then collapse whitespace
    lines = []
    for line in (s or "").splitlines():
        t = line.strip()
        if t.startswith("#") or t.startswith("//"):
            continue
        lines.append(t)
    joined = "\n".join(lines)
    return re.sub(r"\s+", "", joined)


def codes_equivalent(a: str, b: str) -> bool:
    """True if normalized bodies match (best-effort, not a real parser)."""
    if not (a or "").strip() or not (b or "").strip():
        return False
    return normalize_code(a) == normalize_code(b)
