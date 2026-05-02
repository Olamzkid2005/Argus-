"""
Security Audit Script

Performs basic security self-assessment of the Argus platform.
Checks for common misconfigurations and vulnerabilities.
"""

import logging
import os
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class SecurityFinding:
    """A security audit finding"""
    severity: str  # critical, high, medium, low, info
    category: str  # config, dependency, secret, network, auth
    title: str
    description: str
    remediation: str
    check_id: str


class SecurityAudit:
    """
    Performs security self-assessment of the Argus platform.
    """

    def __init__(self):
        self.findings: list[SecurityFinding] = []

    def run_all_checks(self) -> list[SecurityFinding]:
        """Run all security checks"""
        self.check_environment_variables()
        self.check_database_security()
        self.check_celery_security()
        self.check_file_permissions()
        self.check_dependencies()
        self.check_ssl_tls()
        self.check_rate_limiting()
        return self.findings

    def check_environment_variables(self):
        """Check for exposed secrets in environment"""
        # Check for hardcoded secrets
        sensitive_vars = [
            "DATABASE_URL", "REDIS_URL", "SECRET_KEY", "NEXTAUTH_SECRET",
            "VAULT_TOKEN", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"
        ]

        for var in sensitive_vars:
            value = os.getenv(var)
            if value:
                # Check if using default/weak values
                if any(weak in value.lower() for weak in ["password", "secret", "localhost", "default"]):
                    if "localhost" not in value.lower():
                        self.findings.append(SecurityFinding(
                            severity="medium",
                            category="config",
                            title=f"Potentially weak {var}",
                            description=f"{var} may contain a default or weak value",
                            remediation="Use strong, randomly generated secrets",
                            check_id="ENV-001"
                        ))

        # Check for missing required secrets
        required = ["NEXTAUTH_SECRET", "DATABASE_URL"]
        for var in required:
            if not os.getenv(var):
                self.findings.append(SecurityFinding(
                    severity="critical",
                    category="config",
                    title=f"Missing required environment variable: {var}",
                    description=f"{var} is not set, which may cause security issues",
                    remediation=f"Set {var} in your environment or secrets manager",
                    check_id="ENV-002"
                ))

    def check_database_security(self):
        """Check database security configuration"""
        db_url = os.getenv("DATABASE_URL", "")

        if "sslmode=disable" in db_url:
            self.findings.append(SecurityFinding(
                severity="high",
                category="network",
                title="Database SSL disabled",
                description="DATABASE_URL has sslmode=disable",
                remediation="Enable SSL with sslmode=require or sslmode=verify-full",
                check_id="DB-001"
            ))

        if "postgres://postgres:" in db_url:
            self.findings.append(SecurityFinding(
                severity="medium",
                category="auth",
                title="Default database user detected",
                description="Using default 'postgres' user",
                remediation="Create a dedicated application user with minimal privileges",
                check_id="DB-002"
            ))

    def check_celery_security(self):
        """Check Celery security settings"""
        redis_url = os.getenv("REDIS_URL", "")

        if redis_url.startswith("redis://") and not redis_url.startswith("rediss://"):
            self.findings.append(SecurityFinding(
                severity="medium",
                category="network",
                title="Redis connection not encrypted",
                description="Redis URL uses unencrypted redis:// protocol",
                remediation="Use rediss:// for encrypted Redis connections in production",
                check_id="CELERY-001"
            ))

        if os.getenv("CELERY_RESULT_BACKEND") == os.getenv("CELERY_BROKER_URL"):
            self.findings.append(SecurityFinding(
                severity="low",
                category="config",
                title="Celery broker and backend share same Redis DB",
                description="Using same Redis database for broker and results",
                remediation="Use separate Redis databases (e.g., /0 and /1)",
                check_id="CELERY-002"
            ))

    def check_file_permissions(self):
        """Check for overly permissive files"""
        sensitive_exact_names = {".env", ".env.local", ".env.production", "id_rsa"}
        sensitive_extensions = {".pem", ".key", ".env"}

        for root, dirs, files in os.walk("."):
            # Skip node_modules and venv
            dirs[:] = [d for d in dirs if d not in ("node_modules", "venv", ".git", "__pycache__")]

            for file in files:
                if file in sensitive_exact_names or any(file.endswith(ext) for ext in sensitive_extensions):
                    filepath = os.path.join(root, file)
                    try:
                        stat = os.stat(filepath)
                        mode = stat.st_mode
                        # Check if world-readable
                        if mode & 0o004:
                            self.findings.append(SecurityFinding(
                                severity="low",
                                category="config",
                                title=f"World-readable sensitive file: {filepath}",
                                description=f"{filepath} is readable by all users",
                                remediation="Set permissions to 600: chmod 600 {filepath}",
                                check_id="FILE-001"
                            ))
                    except Exception:
                        pass

    def check_dependencies(self):
        """Check for known vulnerable dependencies (basic check)"""
        # Check for requirements.txt or package.json
        req_file = "requirements.txt"
        if os.path.exists(req_file):
            with open(req_file) as f:
                content = f.read()
                if "==" in content:
                    # Pinning is good, but we can't check for CVEs without a scanner
                    self.findings.append(SecurityFinding(
                        severity="info",
                        category="dependency",
                        title="Dependency versions pinned",
                        description="requirements.txt has pinned versions",
                        remediation="Regularly run pip-audit or safety to check for CVEs",
                        check_id="DEP-001"
                    ))

    def check_ssl_tls(self):
        """Check SSL/TLS configuration"""
        if not os.getenv("SSL_CERT_PATH") and not os.getenv("TLS_ENABLED"):
            env = os.getenv("NODE_ENV", "development")
            if env == "production":
                self.findings.append(SecurityFinding(
                    severity="high",
                    category="network",
                    title="TLS not explicitly enabled in production",
                    description="No SSL_CERT_PATH or TLS_ENABLED set",
                    remediation="Configure TLS certificates for production deployment",
                    check_id="TLS-001"
                ))

    def check_rate_limiting(self):
        """Check rate limiting configuration"""
        if not os.getenv("UPSTASH_REDIS_REST_URL"):
            self.findings.append(SecurityFinding(
                severity="medium",
                category="config",
                title="Rate limiting not configured",
                description="UPSTASH_REDIS_REST_URL not set - API rate limiting disabled",
                remediation="Configure Redis-based rate limiting for API endpoints",
                check_id="RATE-001"
            ))

    def generate_report(self) -> dict[str, Any]:
        """Generate structured security audit report"""
        findings = self.run_all_checks()

        severity_counts = {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0}
        for finding in findings:
            severity_counts[finding.severity] = severity_counts.get(finding.severity, 0) + 1

        return {
            "timestamp": datetime.now(UTC).isoformat(),
            "summary": {
                "total_findings": len(findings),
                "critical": severity_counts["critical"],
                "high": severity_counts["high"],
                "medium": severity_counts["medium"],
                "low": severity_counts["low"],
                "info": severity_counts["info"],
            },
            "findings": [asdict(f) for f in findings]
        }

    def print_report(self):
        """Print human-readable report"""
        report = self.generate_report()

        print("=" * 60)
        print("ARGUS SECURITY AUDIT REPORT")
        print("=" * 60)
        print(f"Timestamp: {report['timestamp']}")
        print(f"Total Findings: {report['summary']['total_findings']}")
        print(f"  Critical: {report['summary']['critical']}")
        print(f"  High:     {report['summary']['high']}")
        print(f"  Medium:   {report['summary']['medium']}")
        print(f"  Low:      {report['summary']['low']}")
        print(f"  Info:     {report['summary']['info']}")
        print("-" * 60)

        for finding in report["findings"]:
            print(f"\n[{finding['severity'].upper()}] {finding['title']} ({finding['check_id']})")
            print(f"  Category: {finding['category']}")
            print(f"  Description: {finding['description']}")
            print(f"  Remediation: {finding['remediation']}")

        print("=" * 60)


def main():
    """CLI entry point"""
    logging.basicConfig(level=logging.INFO)

    audit = SecurityAudit()
    audit.print_report()

    # Exit with error code if critical findings
    report = audit.generate_report()
    if report["summary"]["critical"] > 0 or report["summary"]["high"] > 0:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
