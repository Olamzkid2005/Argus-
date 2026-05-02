"""
Web scanner check module.

Extracted from tools/web_scanner.py for modularity and testability.
Currently a stub — logic will be migrated from the main WebScanner class.
"""


class CheckResult:
    """Result of a single security check."""
    def __init__(self, finding_type: str, severity: str, endpoint: str,
                 evidence: dict | None = None, confidence: float = 0.7):
        self.type = finding_type
        self.severity = severity
        self.endpoint = endpoint
        self.evidence = evidence or {}
        self.confidence = confidence


def run_check(target_url: str, session, findings: list) -> list[dict]:
    """
    Run security checks against the target.

    Args:
        target_url: Target URL to scan
        session: requests.Session for HTTP calls
        findings: List to append findings to

    Returns:
        Updated findings list
    """
    # Stub — will be populated with logic from WebScanner.check_* methods
    return findings


class UgraphqlCheck:
    """Check for graphql security issues."""
    def __init__(self):
        self.name = "graphql"

    def check(self, target_url: str, session, findings: list) -> list[dict]:
        """Run graphql checks against target."""
        return findings

