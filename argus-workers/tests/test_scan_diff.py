"""Tests for the ScanDiffEngine."""

from scan_diff_engine import ScanDiffEngine


class TestFingerprinting:
    def test_same_finding_same_fingerprint(self):
        f1 = ScanDiffEngine._fingerprint({
            "type": "XSS",
            "endpoint": "http://ex.com/search",
            "evidence": {"payload": "<script>alert(1)</script>"},
        })
        f2 = ScanDiffEngine._fingerprint({
            "type": "XSS",
            "endpoint": "http://ex.com/search",
            "evidence": {"payload": "<script>alert(1)</script>"},
        })
        assert f1 == f2

    def test_different_payload_different_fingerprint(self):
        f1 = ScanDiffEngine._fingerprint({
            "type": "XSS",
            "endpoint": "http://ex.com/search",
            "evidence": {"payload": "<script>alert(1)</script>"},
        })
        f2 = ScanDiffEngine._fingerprint({
            "type": "XSS",
            "endpoint": "http://ex.com/search",
            "evidence": {"payload": "<script>alert(2)</script>"},
        })
        assert f1 != f2

    def test_no_evidence_falls_back_to_type_endpoint(self):
        f1 = ScanDiffEngine._fingerprint({
            "type": "XSS",
            "endpoint": "http://ex.com/search",
        })
        f2 = ScanDiffEngine._fingerprint({
            "type": "XSS",
            "endpoint": "http://ex.com/search",
        })
        assert f1 == f2

    def test_consistency_16_chars(self):
        fp = ScanDiffEngine._fingerprint({
            "type": "XSS",
            "endpoint": "http://ex.com/search",
        })
        assert len(fp) == 16
        assert isinstance(fp, str)
