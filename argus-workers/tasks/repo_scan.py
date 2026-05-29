"""
Celery tasks for repository scanning phase

Scans GitHub/GitLab repositories for code vulnerabilities using Semgrep
with custom rules based on vibe-security-ultra framework.

Requirements: 4.2, 4.4, 20.1, 20.2, 20.3
"""

import json
import logging
import os
import re
import subprocess
import tempfile
import uuid
from datetime import UTC, datetime

from celery_app import app

logger = logging.getLogger(__name__)

# Common open source licenses
LICENSE_PATTERNS = {
    "GPL-2.0": [r"GNU General Public License.*version 2", r"GPLv2", r"GPL-2\.0"],
    "GPL-3.0": [r"GNU General Public License.*version 3", r"GPLv3", r"GPL-3\.0"],
    "MIT": [r"MIT License", r"The MIT License"],
    "Apache-2.0": [r"Apache License[\s\S]*?version 2", r"Apache-2\.0"],
    "BSD-3-Clause": [r"BSD 3-Clause", r"New BSD License"],
    "BSD-2-Clause": [r"BSD 2-Clause", r"Simplified BSD License"],
    "LGPL": [r"GNU Lesser General Public License", r"LGPL"],
    "ISC": [r"ISC License"],
    "MPL-2.0": [r"Mozilla Public License.*2\.0"],
}

# Common secret patterns for git history scanning
SECRET_PATTERNS = {
    "aws_access_key": r"AKIA[0-9A-Z]{16}",
    "aws_secret_key": r"(?<![A-Za-z0-9/+])[A-Za-z0-9/+]{40}(?![A-Za-z0-9/+=])",
    "github_token": r"ghp_[a-zA-Z0-9]{36}",
    "github_oauth": r"gho_[a-zA-Z0-9]{36}",
    "slack_token": r"xox[bap]-[0-9]{12}-[0-9]{12}-[0-9]{12}-[a-z0-9]{32}",
    "api_key": r'api[_-]?key[_-]?[=:]+\s*["\']?[a-zA-Z0-9]{32,45}["\']?',
    "private_key": r"-----BEGIN [A-Z]+ PRIVATE KEY-----",
    "password": r'password[_-]?[=:]+\s*["\']?[^\s"\']{8,}["\']?',
}

# Default license policy configuration
_DEFAULT_LICENSE_POLICY = {
    "allowed": ["MIT", "Apache-2.0", "BSD-3-Clause", "BSD-2-Clause", "ISC"],
    "warn": ["LGPL", "MPL-2.0"],
    "blocked": ["GPL-2.0", "GPL-3.0"],
}


def _load_license_policy():
    """Load license policy from environment variables with defaults."""
    policy = _DEFAULT_LICENSE_POLICY.copy()
    blocked_env = os.environ.get("ARGUS_LICENSE_POLICY_BLOCKED")
    warn_env = os.environ.get("ARGUS_LICENSE_POLICY_WARN")
    allowed_env = os.environ.get("ARGUS_LICENSE_POLICY_ALLOWED")
    if blocked_env:
        policy["blocked"] = [x.strip() for x in blocked_env.split(",") if x.strip()]
    if warn_env:
        policy["warn"] = [x.strip() for x in warn_env.split(",") if x.strip()]
    if allowed_env:
        policy["allowed"] = [x.strip() for x in allowed_env.split(",") if x.strip()]
    return policy


LICENSE_POLICY = _load_license_policy()


@app.task(
    bind=True,
    name="tasks.repo_scan.run_repo_scan",
    soft_time_limit=2400,
    time_limit=3600,
)
def run_repo_scan(
    self,
    engagement_id: str,
    repo_url: str,
    budget: dict,
    trace_id: str = None,
    custom_rules_path: str = None,
):
    """
    Execute repository scanning phase for an engagement

    Args:
        engagement_id: Engagement ID
        repo_url: GitHub/GitLab repository URL
        budget: Budget configuration
        trace_id: Optional trace_id for distributed tracing (generated if not provided)
        custom_rules_path: Optional path to additional Semgrep/custom rules
    """
    from tasks.base import task_context
    from utils.logging_utils import ScanLogger
    slog = ScanLogger("repo_scan", engagement_id=engagement_id)

    job_extra = {
        "type": "repo_scan",
        "repo_url": repo_url,
        "budget": budget,
        "custom_rules_path": custom_rules_path,
    }

    with task_context(self, engagement_id, "repo_scan",
                      job_extra=job_extra,
                      trace_id=trace_id) as ctx:
        ctx.state.transition("recon", "Starting repository scan")

        result = ctx.orchestrator.run_repo_scan(ctx.job)

        # Generate SBOMs after dependency scanning
        if result and isinstance(result, dict):
            result.setdefault("sbom_paths", {})
            dependencies = result.get("dependencies", [])
            repo_path = result.get(
                "repo_path",
                os.path.join(
                    os.getenv("ARTIFACTS_DIR", os.path.join(tempfile.gettempdir(), "argus_artifacts")),
                    engagement_id,
                ),
            )
            os.makedirs(repo_path, exist_ok=True)

            if dependencies:
                try:
                    cyclonedx_sbom = generate_cyclonedx_sbom(repo_path, dependencies)
                    cyclonedx_path = save_sbom(cyclonedx_sbom, repo_path, format="cyclonedx")

                    spdx_sbom = generate_spdx_sbom(repo_path, dependencies)
                    spdx_path = save_sbom(spdx_sbom, repo_path, format="spdx")

                    result["sbom_paths"] = {
                        "cyclonedx": cyclonedx_path,
                        "spdx": spdx_path,
                    }
                    logger.info("SBOMs generated for engagement %s", engagement_id)
                except Exception as e:
                    logger.error("Failed to generate SBOMs: %s", e)
            else:
                logger.info(
                    "SBOM generation skipped for engagement %s: no dependency data available",
                    engagement_id,
                )

        # Auto-push web scan job
        from tasks.utils import fetch_engagement_scan_options
        opts = fetch_engagement_scan_options(engagement_id)
        try:
            app.send_task(
                "tasks.scan.run_scan",
                args=[
                    engagement_id,
                    [repo_url],
                    budget,
                    ctx.trace_id,
                    opts["agent_mode"],
                    opts["scan_mode"],
                    opts["aggressiveness"],
                    opts["bug_bounty_mode"],
                ],
            )
        except Exception as e:
            logger.error("Failed to enqueue scan for engagement %s: %s", engagement_id, e)
            ctx.state.safe_transition("failed", f"Failed to dispatch scan: {e}")
            return {"phase": "repo_scan", "status": "failed", "reason": "scan_dispatch_failed"}

        return result


@app.task(bind=True, name="tasks.repo_scan.expand_repo_scan")
def expand_repo_scan(
    self,
    engagement_id: str,
    repo_url: str,
    additional_rules_path: str,
    budget: dict,
    trace_id: str = None,
):
    """
    Expand repository scan with additional custom rules

    Args:
        engagement_id: Engagement ID
        repo_url: Repository URL
        additional_rules_path: Path to additional Semgrep rules
        budget: Budget configuration
        trace_id: Optional trace_id for distributed tracing
    """
    from tasks.base import task_context

    job_extra = {
        "type": "repo_scan_expand",
        "repo_url": repo_url,
        "additional_rules_path": additional_rules_path,
        "budget": budget,
    }

    with task_context(self, engagement_id, "repo_scan_expand",
                      job_extra=job_extra,
                      trace_id=trace_id) as ctx:
        return ctx.orchestrator.run_repo_scan(ctx.job)


def get_blame_for_finding(repo_path, finding):
    """
    Run git blame on the file/line associated with a finding.
    Returns blame info: author, commit, date, etc.
    """
    if "file_path" not in finding or "line_number" not in finding:
        return None

    file_path = finding["file_path"]
    line_number = finding.get("line_number", 1)

    try:
        result = subprocess.run(  # noqa: S603 — safe: args are hardcoded/validated, repo_path is controlled
            [  # noqa: S607
                "git",
                "blame",
                "-L",
                f"{line_number},{line_number}",
                "--porcelain",
                "--",
                file_path,
            ],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode == 0:
            blame_info = {}
            for line in result.stdout.split("\n"):
                if line.startswith("author "):
                    blame_info["author"] = line.split(" ", 1)[1]
                elif line.startswith("author-time "):
                    blame_info["author_time"] = line.split(" ")[1]
                elif line.startswith("committer-time "):
                    blame_info["committer_time"] = line.split(" ")[1]
                elif line.startswith("commit "):
                    blame_info["commit_hash"] = line.split(" ")[1]
                elif line.startswith("summary "):
                    blame_info["summary"] = line.split(" ", 1)[1]

            return blame_info

    except Exception as e:
        logger.error(f"Git blame failed: {e}")

    return None


def enrich_findings_with_blame(repo_path, findings):
    """
    Add blame information to all findings that have file/line info.
    """
    for finding in findings:
        if finding.get("type") in ["COMMITTED_SECRET", "STATIC_ANALYSIS_FINDING"]:
            blame = get_blame_for_finding(repo_path, finding)
            if blame:
                finding["blame"] = blame
                finding["introduced_by"] = blame.get("author", "unknown")
                finding["introduced_at"] = blame.get("author_time", "")
                finding["introduced_in_commit"] = blame.get("commit_hash", "")

    return findings



def generate_cyclonedx_sbom(repo_path, dependencies):
    """
    Generate CycloneDX SBOM for the repository.
    """
    sbom = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.4",
        "version": 1,
        "serialNumber": f"urn:uuid:{uuid.uuid4()}",
        "creationInfo": {
            "timestamp": datetime.now(UTC).isoformat() + "Z",
            "tools": [
                {"vendor": "Argus", "name": "Security Platform", "version": "1.0"}
            ],
        },
        "components": [],
        "dependencies": [],
    }

    for dep in dependencies:
        component = {
            "type": "library",
            "bom-ref": f"pkg:{dep.get('ecosystem', 'generic')}/{dep.get('name', 'unknown')}@{dep.get('version', 'unknown')}",
            "name": dep.get("name", "unknown"),
            "version": dep.get("version", "unknown"),
            "purl": f"pkg:{dep.get('ecosystem', 'generic')}/{dep.get('name', 'unknown')}@{dep.get('version', 'unknown')}",
            "externalReferences": [],
        }

        if dep.get("cve"):
            component["externalReferences"].append(
                {
                    "type": "advisory",
                    "url": f"https://nvd.nist.gov/vuln/detail/{dep['cve']}",
                }
            )

        sbom["components"].append(component)
        sbom["dependencies"].append({"ref": component["bom-ref"], "dependsOn": []})

    return sbom


def generate_spdx_sbom(repo_path, dependencies):
    """Generate SPDX SBOM for the repository."""
    sbom = {
        "spdxVersion": "SPDX-2.3",
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": f"SBOM-{os.path.basename(repo_path)}",
        "documentDescribes": [
            f"SPDXRef-{dep.get('name', 'unknown')}" for dep in dependencies
        ],
        "packages": [],
        "relationships": [],
    }

    for dep in dependencies:
        package = {
            "SPDXID": f"SPDXRef-{dep.get('name', 'unknown')}",
            "name": dep.get("name", "unknown"),
            "versionInfo": dep.get("version", "unknown"),
            "downloadLocation": "NOASSERTION",
            "filesAnalyzed": False,
        }

        if dep.get("cve"):
            package["externalRefs"] = [
                {
                    "referenceCategory": "SECURITY",
                    "referenceType": "cpe23Type",
                    "referenceLocator": dep["cve"],
                }
            ]

        sbom["packages"].append(package)

    return sbom


def save_sbom(sbom, repo_path, format="cyclonedx"):
    """Save SBOM to file in the engagement artifacts directory."""
    if format == "cyclonedx":
        filename = os.path.join(repo_path, "sbom-cyclonedx.json")
        with open(filename, "w") as f:
            json.dump(sbom, f, indent=2)
    elif format == "spdx":
        filename = os.path.join(repo_path, "sbom-spdx.json")
        with open(filename, "w") as f:
            json.dump(sbom, f, indent=2)
    else:
        raise ValueError(f"Unsupported SBOM format: {format}")

    logger.info(f"SBOM saved to {filename}")
    return filename


# ========== Section 3.1: Dependency Scanning (SCA) ==========





# ========== Section 3.2: Git History Secret Scan ==========


def scan_git_history_for_secrets(repo_path):
    """Scan git history for committed secrets."""
    max_git_output_bytes = 100 * 1024 * 1024  # 100MB
    MAX_PATCH_LINES = 100000  # Prevent unbounded memory accumulation (issue 3.14)
    findings = []

    process = None
    try:
        process = subprocess.Popen(
            [  # noqa: S607
                "git",
                "log",
                "--all",
                "--patch",
                "--pretty=format:COMMIT:%H|AUTHOR:%an|DATE:%ai",
            ],
            cwd=repo_path,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        current_commit = None
        current_author = None
        current_date = None
        patch_lines = []
        total_bytes = 0

        for line in process.stdout:
            line_bytes = len(line.encode("utf-8"))
            total_bytes += line_bytes
            if total_bytes > max_git_output_bytes:
                logger.warning(
                    f"Git history scan: exceeded {max_git_output_bytes} bytes ({total_bytes}), truncating"
                )
                process.kill()
                break

            line = line.rstrip("\n\r")

            if line.startswith("COMMIT:"):
                if current_commit and patch_lines:
                    _check_patch_for_secrets(
                        patch_lines,
                        current_commit,
                        current_author,
                        current_date,
                        repo_path,
                        findings,
                    )
                    patch_lines = []

                parts = line.split("|")
                current_commit = parts[0].split(":")[1] if len(parts) > 0 else "unknown"
                current_author = parts[1].split(":")[1] if len(parts) > 1 else "unknown"
                current_date = parts[2].split(":")[1] if len(parts) > 2 else "unknown"
            elif line.startswith("diff ") or line.startswith("commit "):
                continue
            else:
                # Limit patch_lines to prevent OOM (issue 3.14)
                if len(patch_lines) >= MAX_PATCH_LINES:
                    logger.warning(
                        f"Patch too large (> {MAX_PATCH_LINES} lines), checking first batch for commit {current_commit}"
                    )
                    if current_commit:
                        _check_patch_for_secrets(
                            patch_lines,
                            current_commit,
                            current_author,
                            current_date,
                            repo_path,
                            findings,
                        )
                    patch_lines = []
                patch_lines.append(line)

        process.wait(timeout=600)

        # Close pipes AFTER wait to avoid SIGPIPE (issue 3.32)
        if process.stdout:
            process.stdout.close()
        if process.stderr:
            stderr_output = process.stderr.read()
            process.stderr.close()
        else:
            stderr_output = ""

        if process.returncode not in [0, 1]:
            logger.warning(
                f"Git log failed (exit {process.returncode}): {stderr_output}"
            )

        if current_commit and patch_lines:
            _check_patch_for_secrets(
                patch_lines,
                current_commit,
                current_author,
                current_date,
                repo_path,
                findings,
            )

    except subprocess.TimeoutExpired:
        logger.error("Git history scan timed out")
        if process:
            process.kill()
            process.wait()
    except OSError as e:
        logger.error(f"Git history scan failed: {e}")
        if process:
            process.kill()
            process.wait()

    return findings


def _check_patch_for_secrets(lines, commit, author, date, repo_path, findings):
    """Check patch lines for secret patterns."""
    full_text = "\n".join(lines)

    for secret_type, pattern in SECRET_PATTERNS.items():
        matches = re.finditer(pattern, full_text, re.MULTILINE)
        for match in matches:
            start_pos = match.start()
            line_num = full_text[:start_pos].count("\n") + 1

            findings.append(
                {
                    "type": "COMMITTED_SECRET",
                    "severity": "HIGH",
                    "title": f"Secret found in git history: {secret_type}",
                    "commit_hash": commit,
                    "author": author,
                    "date": date,
                    "line_number": line_num,
                    "matched_text": match.group()[:50] + "..."
                    if len(match.group()) > 50
                    else match.group(),
                    "file_path": _extract_file_path(lines, line_num),
                }
            )


def _extract_file_path(lines, line_num):
    """Extract file path from surrounding context."""
    start = max(0, line_num - 10)
    for line in lines[start:line_num]:
        if line.startswith("diff --git a/"):
            return line.replace("diff --git a/", "").strip()
    return "unknown"


# ========== Section 3.5: License Compliance ==========


def detect_license(file_path):
    """Detect license from license file content."""
    license_files = ["LICENSE", "LICENSE.txt", "LICENSE.md", "COPYING"]

    for lic_file in license_files:
        full_path = os.path.join(file_path, lic_file)
        if os.path.exists(full_path):
            with open(full_path, errors="ignore") as f:
                content = f.read()
                return _match_license(content)

    # Check package.json for license field
    package_json = os.path.join(file_path, "package.json")
    if os.path.exists(package_json):
        try:
            with open(package_json) as f:
                data = json.load(f)
                if "license" in data:
                    return data["license"]
        except Exception:
            logger.warning(
                "Failed to parse license from package.json", exc_info=True
            )

    return "UNKNOWN"


def _match_license(content):
    """Match license patterns against content."""
    for license_name, patterns in LICENSE_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, content, re.IGNORECASE):
                return license_name
    return "UNKNOWN"


def check_license_compliance(repo_path, policy=None):
    """Check license compliance for the project and its dependencies."""
    if policy is None:
        policy = LICENSE_POLICY

    findings = []

    # Detect project license
    project_license = detect_license(repo_path)

    if project_license != "UNKNOWN":
        severity = "LOW"
        if project_license in policy["blocked"]:
            severity = "HIGH"
        elif project_license in policy["warn"]:
            severity = "MEDIUM"

        findings.append(
            {
                "type": "LICENSE_COMPLIANCE",
                "severity": severity,
                "title": f"Project license: {project_license}",
                "license": project_license,
                "file_path": "LICENSE",
                "compliance_status": "blocked"
                if project_license in policy["blocked"]
                else "warn"
                if project_license in policy["warn"]
                else "allowed",
            }
        )

    # Check dependency licenses from package-lock.json (npm)
    lock_path = os.path.join(repo_path, "package-lock.json")
    if os.path.exists(lock_path):
        try:
            with open(lock_path) as f:
                lock = json.load(f)
            for dep_name, dep_info in lock.get("packages", {}).items():
                if dep_name:  # skip root package (key "")
                    dep_license = dep_info.get("license", "UNKNOWN")
                    if dep_license in policy["blocked"]:
                        findings.append(
                            {
                                "type": "LICENSE_COMPLIANCE",
                                "severity": "HIGH",
                                "title": f'Dependency "{dep_name}" has blocked license: {dep_license}',
                                "license": dep_license,
                                "file_path": f"package-lock.json:{dep_name}",
                                "compliance_status": "blocked",
                            }
                        )
                    elif dep_license in policy["warn"]:
                        findings.append(
                            {
                                "type": "LICENSE_COMPLIANCE",
                                "severity": "MEDIUM",
                                "title": f'Dependency "{dep_name}" has restricted license: {dep_license}',
                                "license": dep_license,
                                "file_path": f"package-lock.json:{dep_name}",
                                "compliance_status": "warn",
                            }
                        )
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to parse package-lock.json for license check: %s", e)

    return findings


# ========== Section 3.6: More SAST Tools ==========


def run_bandit(repo_path):
    """Run Bandit for Python security issues."""
    try:
        result = subprocess.run(  # noqa: S603 — safe: list form, no shell=True
            ["bandit", "-r", repo_path, "-f", "json", "-o", "-"],  # noqa: S607
            capture_output=True,
            text=True,
            timeout=300,
        )

        if result.returncode in [0, 1]:
            data = json.loads(result.stdout)
            findings = []

            for issue in data.get("results", []):
                findings.append(
                    {
                        "type": "STATIC_ANALYSIS_FINDING",
                        "severity": _map_bandit_severity(
                            issue.get("severity", "MEDIUM")
                        ),
                        "title": issue.get("issue_text", "Python Security Issue"),
                        "file_path": issue.get("filename", ""),
                        "line_number": issue.get("line_number", 0),
                        "code_snippet": issue.get("code", ""),
                        "tool": "bandit",
                        "cwe": issue.get("cwe", ""),
                        "confidence": issue.get("confidence", "medium"),
                    }
                )

            return findings
    except Exception as e:
        logger.error(f"Bandit failed: {e}")
    return []


def _map_bandit_severity(severity):
    mapping = {"LOW": "LOW", "MEDIUM": "MEDIUM", "HIGH": "HIGH"}
    return mapping.get(severity, "MEDIUM")


def run_eslint_security(repo_path):
    """Run ESLint with security plugins."""
    try:
        # Protect against argument injection via repo_path
        if repo_path.startswith("-"):
            logger.warning(
                "Suspicious repo_path starting with '-', skipping eslint: %s", repo_path
            )
            return []
        result = subprocess.run(  # noqa: S603 — safe: list form, no shell=True, -- separator prevents arg injection
            [  # noqa: S607
                "npx",
                "eslint",
                "--ext",
                ".js,.jsx,.ts,.tsx",
                "--format",
                "json",
                "--",
                repo_path,
            ],
            capture_output=True,
            text=True,
            timeout=300,
        )

        if result.returncode in [0, 1]:
            data = json.loads(result.stdout)
            findings = []

            for issue in data:
                if issue.get("ruleId", "").startswith("security/"):
                    findings.append(
                        {
                            "type": "STATIC_ANALYSIS_FINDING",
                            "severity": _map_eslint_severity(issue.get("severity", 1)),
                            "title": issue.get("message", "JS Security Issue"),
                            "file_path": issue.get("filePath", ""),
                            "line_number": issue.get("line", 0),
                            "code_snippet": issue.get("source", ""),
                            "tool": "eslint",
                            "rule_id": issue.get("ruleId", ""),
                        }
                    )

            return findings
    except Exception as e:
        logger.error(f"ESLint failed: {e}")
    return []


def _map_eslint_severity(severity):
    if severity == 1:
        return "LOW"
    if severity == 2:
        return "MEDIUM"
    return "INFO"


def run_gosec(repo_path):
    """Run gosec for Go security issues."""
    try:
        # Use -- to prevent argument injection via repo_path (issue 3.22)
        result = subprocess.run(  # noqa: S603 — safe: list form, no shell=True, -- separator prevents arg injection
            ["gosec", "-fmt=json", "--", repo_path],  # noqa: S607
            capture_output=True,
            text=True,
            timeout=300,
        )

        if result.returncode in [0, 1]:
            data = json.loads(result.stdout)
            findings = []

            for issue in data.get("Issues", []):
                findings.append(
                    {
                        "type": "STATIC_ANALYSIS_FINDING",
                        "severity": issue.get("severity", "MEDIUM").upper(),
                        "title": issue.get("details", "Go Security Issue"),
                        "file_path": issue.get("file", ""),
                        "line_number": issue.get("line", 0),
                        "code_snippet": issue.get("code", ""),
                        "tool": "gosec",
                        "rule_id": issue.get("rule_id", ""),
                        "cwe": issue.get("cwe", {}).get("id", ""),
                    }
                )

            return findings
    except Exception as e:
        logger.error(f"gosec failed: {e}")
    return []
