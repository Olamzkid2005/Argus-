"""
Infrastructure Security Analyzer — Terraform, Kubernetes, Docker analysis.
"""

from __future__ import annotations

import logging
from pathlib import Path

from tool_core.base import AbstractTool, ToolContext
from tool_core.finding_builder import FindingBuilder
from tool_core.result import ToolStatus, UnifiedToolResult

logger = logging.getLogger(__name__)


class InfrastructureSecurityAnalyzer(AbstractTool):
    """Analyzes infrastructure-as-code for security misconfigurations."""

    tool_name: str = "infrastructure_security_analyzer"

    def execute(self, ctx: ToolContext) -> UnifiedToolResult:
        result = UnifiedToolResult(tool_name=self.tool_name, target=ctx.target)
        builder = FindingBuilder(self.tool_name, engagement_id=ctx.engagement_id)

        target_path = Path(ctx.target)
        is_url = ctx.target.startswith(("http://", "https://"))

        if target_path.is_dir():
            self._scan_terraform(target_path, builder)
            self._scan_kubernetes(target_path, builder)
            self._scan_docker(target_path, builder)
        elif is_url:
            # URL target — check infrastructure via HTTP response headers
            self._scan_url_headers(ctx.target, builder)
        else:
            result.status = ToolStatus.SKIPPED
            result.error_message = f"Target is not a directory or URL: {ctx.target}"
            result.mark_finished()
            return result

        result.findings = builder.findings
        result.findings_count = len(builder.findings)
        result.status = ToolStatus.SUCCESS
        result.mark_finished()
        return result

    def _scan_url_headers(self, target: str, builder: FindingBuilder) -> None:
        """Scan a URL target for infrastructure-level security issues via HTTP response headers."""
        import ssl
        import urllib.request

        if not target.startswith(("http://", "https://")):
            target = "https://" + target

        try:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            req = urllib.request.Request(
                target,
                method="HEAD",
                headers={"User-Agent": "Argus/1.0 (Infrastructure Analyzer)"},
            )
            with urllib.request.urlopen(req, timeout=10, context=ctx) as resp:
                headers = {k.lower(): v for k, v in resp.headers.items()}
                server = headers.get("server", "")
                if server:
                    builder.info(
                        "INFRA_SERVER_HEADER",
                        target,
                        {"header": "Server", "value": server},
                    )
                via = headers.get("via", "")
                if via:
                    builder.info(
                        "INFRA_VIA_HEADER",
                        target,
                        {"header": "Via", "value": via},
                    )
                x_powered = headers.get("x-powered-by", "")
                if x_powered:
                    builder.vulnerability(
                        "INFRA_INFO_DISCLOSURE",
                        "LOW",
                        target,
                        {"header": "X-Powered-By", "value": x_powered},
                        confidence=0.6,
                    )
                if server.lower() in ("apache", "nginx", "iis", "cloudflare", "aws cloudfront"):
                    builder.info(
                        "INFRA_WEB_SERVER",
                        target,
                        {"server": server, "status_code": resp.status},
                    )
        except Exception as e:
            logger.debug("URL header scan failed for %s: %s", target, e)

    def _scan_terraform(self, path: Path, builder: FindingBuilder) -> None:
        for tf_file in path.glob("**/*.tf"):
            try:
                content = tf_file.read_text(encoding="utf-8", errors="replace").lower()
                if "acl" in content and ("public-read" in content or '"public"' in content):
                    builder.vulnerability("TF_PUBLIC_ACL", "MEDIUM", str(tf_file), {"description": "S3 bucket has public ACL"})
                if "0.0.0.0/0" in content and "ingress" in content:
                    builder.vulnerability("TF_OPEN_SG", "HIGH", str(tf_file), {"description": "Security group allows 0.0.0.0/0"})
            except Exception:
                pass

    def _scan_kubernetes(self, path: Path, builder: FindingBuilder) -> None:
        for ext in ("*.yaml", "*.yml"):
            for k8s_file in path.glob(f"**/{ext}"):
                try:
                    content = k8s_file.read_text(encoding="utf-8", errors="replace").lower()
                    if "kind:" not in content:
                        continue
                    if "privileged: true" in content:
                        builder.vulnerability("K8S_PRIVILEGED", "HIGH", str(k8s_file), {"description": "Container runs in privileged mode"})
                    if "hostnetwork: true" in content:
                        builder.vulnerability("K8S_HOST_NETWORK", "MEDIUM", str(k8s_file), {"description": "Pod uses host network namespace"})
                except Exception:
                    pass

    def _scan_docker(self, path: Path, builder: FindingBuilder) -> None:
        for dockerfile in path.glob("**/Dockerfile*"):
            try:
                for line in dockerfile.read_text(encoding="utf-8", errors="replace").splitlines():
                    stripped = line.strip()
                    if stripped.startswith("FROM") and ":latest" in stripped:
                        builder.vulnerability("DOCKER_LATEST_TAG", "LOW", str(dockerfile), {"description": "Using 'latest' tag"})
                    if stripped.upper().startswith("ENV") and any(kw in stripped.upper() for kw in ("SECRET", "PASSWORD", "TOKEN")):
                        builder.vulnerability("DOCKER_SECRETS_IN_ENV", "HIGH", str(dockerfile), {"description": "Secrets in environment variables"})
            except Exception:
                pass
