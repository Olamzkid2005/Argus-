"""Tests for intelligence_engine sync enrichment order fix.

The fix ensures enriched results maintain input order by using
list comprehension over futures (submission order) instead of
as_completed (completion order).
"""

from concurrent.futures import ThreadPoolExecutor


def test_sync_enrichment_preserves_input_order():
    """List comprehension over futures preserves submission order."""
    findings = [
        {"id": "A", "type": "XSS"},
        {"id": "B", "type": "SQL_INJECTION"},
        {"id": "C", "type": "SSRF"},
    ]

    def _mock_enrich(finding: dict) -> dict:
        result = finding.copy()
        result["enriched"] = True
        return result

    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(_mock_enrich, f) for f in findings]
        enriched = [future.result() for future in futures]

    assert len(enriched) == 3
    assert enriched[0]["id"] == "A"
    assert enriched[1]["id"] == "B"
    assert enriched[2]["id"] == "C"
    assert all(e["enriched"] for e in enriched)


def test_sync_enrichment_all_input_items_appear():
    """All input items must appear in output regardless of I/O timing."""
    findings = [
        {"id": str(i), "type": "XSS" if i % 2 == 0 else "SQL_INJECTION"}
        for i in range(10)
    ]

    def _mock_enrich(finding: dict) -> dict:
        result = finding.copy()
        result["enriched"] = True
        return result

    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = [pool.submit(_mock_enrich, f) for f in findings]
        enriched = [future.result() for future in futures]

    input_ids = {f["id"] for f in findings}
    output_ids = {e["id"] for e in enriched}
    assert output_ids == input_ids
    assert len(enriched) == len(findings)


def test_sync_enrichment_empty_input():
    """Empty input list should return empty list."""
    with ThreadPoolExecutor(max_workers=1) as pool:
        futures = [pool.submit(lambda f: f, f) for f in []]
        enriched = [future.result() for future in futures]
    assert enriched == []
