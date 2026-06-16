"""Semantic deduplication of findings using similarity scoring."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence


def _normalize(text: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text)


def _token_set(text: str) -> set[str]:
    return set(_normalize(text).split())


def _jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 1.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def _finding_fingerprint(finding: dict) -> str:
    """Create a deterministic fingerprint for exact dedup."""
    parts = [
        str(finding.get("type", "")),
        str(finding.get("endpoint", "")),
        str(finding.get("severity", "")),
    ]
    raw = "|".join(parts)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def deduplicate(
    findings: Sequence[dict],
    similarity_threshold: float = 0.75,
) -> tuple[list[dict], int]:
    """Deduplicate findings using both exact fingerprint and semantic similarity.

    Returns (unique_findings, duplicates_removed).
    """
    if not findings:
        return [], 0

    seen_fingerprints: dict[str, dict] = {}
    unique: list[dict] = []
    duplicates_removed = 0

    for finding in findings:
        fp = _finding_fingerprint(finding)

        if fp in seen_fingerprints:
            duplicates_removed += 1
            continue

        title_tokens = _token_set(finding.get("title", "") or finding.get("type", ""))
        desc_tokens = _token_set(finding.get("description", ""))
        combined_tokens = title_tokens | desc_tokens

        is_dup = False
        for existing in unique:
            ex_title = _token_set(existing.get("title", "") or existing.get("type", ""))
            ex_desc = _token_set(existing.get("description", ""))
            ex_combined = ex_title | ex_desc

            if _jaccard(combined_tokens, ex_combined) >= similarity_threshold:
                is_dup = True
                break

        if not is_dup:
            seen_fingerprints[fp] = finding
            unique.append(finding)
        else:
            duplicates_removed += 1

    return unique, duplicates_removed
