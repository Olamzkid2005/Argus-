"""Regression tests from the first CONTAINED run (www.hisdayspringfamily.org).

The run produced three HIGH "exposed sensitive file" findings — for
``robots.txt``, ``sitemap.xml`` and ``/.well-known/security.txt`` — none of
which is a vulnerability, and a MEDIUM prototype-pollution finding for a page
whose payload response was byte-identical to the baseline it came from.

The bodies below are what that site served and what it returned for the
pollution payloads; the assertions are on the scanner's decisions.
"""

import hashlib
from unittest.mock import Mock, patch

import pytest

from tools.web_scanner import WebScanner
from tools.web_scanner_checks import detection_check

ROBOTS_TXT = """User-agent: *
Disallow: /api/
User-agent: GPTBot
Disallow: /
User-agent: CCBot
Disallow: /
Sitemap: https://www.hisdayspringfamily.org/sitemap.xml
"""

SITEMAP_XML = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://www.hisdayspringfamily.org/</loc></url>
  <url><loc>https://www.hisdayspringfamily.org/prayer</loc></url>
</urlset>
"""

SECURITY_TXT = """Contact: mailto:hello@hisdayspring.org
Expires: 2027-01-01T00:00:00.000Z
Preferred-Languages: en
Canonical: https://www.hisdayspringfamily.org/.well-known/security.txt
"""

#: The site's home page: an ordinary page that happens to contain the word
#: "true" many times. That is all the old check required.
HOME_PAGE = (
    "<!doctype html><html><head><title>Day Spring Family</title></head>"
    "<body><script>window.isLive=true;window.showBanner=true;</script>"
    "<p>Our service is true to the word.</p></body></html>"
)


def _mock_response(status_code=200, headers=None, text="", url=""):
    resp = Mock(status_code=status_code)
    resp.headers = headers or {}
    resp.text = text
    resp.url = url
    resp.json.return_value = {}
    resp.raw = Mock()
    resp.raw.headers = Mock()
    resp.raw.headers.getlist = Mock(return_value=[])
    return resp


def _only(mapping):
    """Fake ``_safe_request`` that answers only the paths in ``mapping``."""

    def _fake(method, url, **kwargs):
        for suffix, response in mapping.items():
            if url.endswith(suffix):
                return response
        return None

    return _fake


class TestPublishedFilesAreNotSensitive:
    """robots.txt, sitemap.xml and security.txt are published on purpose."""

    @pytest.mark.parametrize(
        ("path", "body"),
        [
            ("robots.txt", ROBOTS_TXT),
            ("sitemap.xml", SITEMAP_XML),
            (".well-known/security.txt", SECURITY_TXT),
        ],
    )
    def test_published_file_is_not_reported(self, path, body):
        scanner = WebScanner()
        scanner.target_url = "https://www.hisdayspringfamily.org/"
        response = _mock_response(text=body, url=f"https://www.hisdayspringfamily.org/{path}")

        with patch.object(scanner, "_safe_request", side_effect=_only({path: response})):
            scanner.check_sensitive_files()

        findings = scanner._builder.findings if scanner._builder else []
        exposed = [f for f in findings if f["type"] == "EXPOSED_SENSITIVE_FILE"]
        assert exposed == [], (
            f"{path} is meant to be fetched by anyone, but was reported as "
            f"an exposed sensitive file: {exposed}"
        )

    def test_env_file_is_still_reported(self):
        """.env is not published, and the check must still catch it."""
        scanner = WebScanner()
        scanner.target_url = "https://www.hisdayspringfamily.org/"
        response = _mock_response(
            text="DATABASE_URL=postgres://user:pass@localhost:5432/app\nSECRET_KEY=abc123",
            url="https://www.hisdayspringfamily.org/.env",
        )

        with patch.object(scanner, "_safe_request", side_effect=_only({".env": response})):
            scanner.check_sensitive_files()

        exposed = [
            f
            for f in scanner._builder.findings
            if f["type"] == "EXPOSED_SENSITIVE_FILE"
        ]
        assert len(exposed) == 1
        assert exposed[0]["severity"] == "HIGH"
        assert exposed[0]["evidence"]["file"] == ".env"


class TestSensitiveFileListsStayInSync:
    """The list is duplicated in two modules; drifting copies caused the bug."""

    def test_lists_are_identical(self):
        assert WebScanner.SENSITIVE_FILES == detection_check.SENSITIVE_FILES

    def test_published_files_are_absent(self):
        for path in ("robots.txt", "sitemap.xml", ".well-known/security.txt"):
            assert path not in WebScanner.SENSITIVE_FILES


class TestPrototypePollutionBaselineDiff:
    """A page containing "true" is not prototype pollution."""

    def test_identical_payload_response_is_not_a_finding(self):
        """The real case: payload body == baseline body, word "true" present."""
        scanner = WebScanner()
        scanner.target_url = "https://www.hisdayspringfamily.org/"
        baseline = _mock_response(
            text=HOME_PAGE, url="https://www.hisdayspringfamily.org/"
        )
        payload = _mock_response(
            text=HOME_PAGE,
            url="https://www.hisdayspringfamily.org/?__proto__[isAdmin]=true",
        )

        def _fake(method, url, **kwargs):
            return payload if "__proto__" in url else baseline

        with patch.object(scanner, "_safe_request", side_effect=_fake):
            scanner.check_prototype_pollution()

        assert scanner._builder is None or scanner._builder.findings == []

    def test_new_marker_is_a_finding(self):
        """A merged property that only the payload response shows is real."""
        scanner = WebScanner()
        scanner.target_url = "https://www.hisdayspringfamily.org/"
        baseline = _mock_response(
            text=HOME_PAGE, url="https://www.hisdayspringfamily.org/"
        )
        payload = _mock_response(
            text=HOME_PAGE.replace("<p>", '<p>{"isAdmin":true}', 1),
            url="https://www.hisdayspringfamily.org/?__proto__[isAdmin]=true",
        )

        def _fake(method, url, **kwargs):
            return payload if "__proto__" in url else baseline

        with patch.object(scanner, "_safe_request", side_effect=_fake):
            scanner.check_prototype_pollution()

        findings = scanner._builder.findings
        assert len(findings) == 1
        finding = findings[0]
        assert finding["type"] == "PROTOTYPE_POLLUTION"
        assert finding["severity"] == "MEDIUM"
        # Evidence is HTML-escaped before storage (utils.sanitization); the
        # marker is still identifiable as the merged property.
        assert finding["evidence"]["markers"] == ["&quot;isadmin&quot;:true"]
        assert (
            finding["evidence"]["baseline_body_sha256"]
            != finding["evidence"]["payload_body_sha256"]
        )

    def test_marker_already_in_baseline_is_not_a_finding(self):
        """A site that always renders isAdmin=true says nothing about merging."""
        scanner = WebScanner()
        scanner.target_url = "https://example.com/"
        page = '<html>{"isAdmin":true}</html>'
        response = _mock_response(text=page, url="https://example.com/")

        with patch.object(scanner, "_safe_request", return_value=response):
            scanner.check_prototype_pollution()

        assert scanner._builder is None or scanner._builder.findings == []


class TestMediumFindingsCarryResponseEvidence:
    """MEDIUM and above must carry the response they were derived from."""

    def test_missing_csp_carries_the_observed_response(self):
        scanner = WebScanner()
        scanner.target_url = "https://www.hisdayspringfamily.org/"
        body = HOME_PAGE
        response = _mock_response(
            headers={"server": "Caddy", "x-frame-options": "DENY"},
            text=body,
            url="https://www.hisdayspringfamily.org/",
        )

        with patch.object(scanner, "_safe_request", return_value=response):
            scanner.check_csp()

        finding = scanner._builder.findings[0]
        observed = finding["evidence"]["http_response"]
        assert observed["status_code"] == 200
        assert observed["url"] == "https://www.hisdayspringfamily.org/"
        assert observed["headers"]["server"] == "Caddy"
        assert observed["body_bytes"] == len(body.encode("utf-8"))
        assert observed["body_sha256"] == hashlib.sha256(body.encode("utf-8")).hexdigest()
        # The preview is escaped on storage like every other evidence string.
        assert observed["body_preview"].startswith("&lt;!doctype html&gt;")

    def test_headers_finding_carries_the_observed_response(self):
        scanner = WebScanner()
        scanner.target_url = "https://example.com/"
        response = _mock_response(
            headers={"strict-transport-security": "max-age=31536000"},
            text="hello",
            url="https://example.com/",
        )

        with patch.object(scanner, "_safe_request", return_value=response):
            scanner.check_security_headers()

        finding = scanner._builder.findings[0]
        assert finding["severity"] == "MEDIUM"
        assert finding["evidence"]["http_response"]["status_code"] == 200
        assert finding["evidence"]["http_response"]["body_bytes"] == 5

    def test_info_findings_carry_no_response_block(self):
        """The rule is for MEDIUM+; INFO stays lightweight."""
        scanner = WebScanner()
        scanner.target_url = "https://example.com/"
        response = _mock_response(text="hello", url="https://example.com/")
        scanner._request_state.last_response = response

        scanner._add_finding(
            finding_type="PARAMETER_DISCOVERY",
            severity="INFO",
            endpoint="https://example.com/",
            evidence={"parameter": "q"},
        )

        assert "http_response" not in scanner._builder.findings[0]["evidence"]

    def test_response_block_is_omitted_when_nothing_was_observed(self):
        """No response (e.g. a TLS-only finding) must not invent one."""
        scanner = WebScanner()
        scanner._add_finding(
            finding_type="EXPIRED_SSL_CERTIFICATE",
            severity="HIGH",
            endpoint="https://example.com/",
            evidence={"reason": "certificate expired"},
        )

        assert "http_response" not in scanner._builder.findings[0]["evidence"]
