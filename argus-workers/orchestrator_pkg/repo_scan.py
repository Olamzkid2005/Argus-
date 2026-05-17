"""
Repository scanning logic extracted from Orchestrator.
"""
import contextlib
import glob
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile

from config.constants import (
    DEFAULT_AGGRESSIVENESS,
    TOOL_TIMEOUT_DEFAULT,
    TOOL_TIMEOUT_LONG,
)
from utils.logging_utils import ScanLogger

logger = logging.getLogger(__name__)


def run_npm_audit(repo_path: str) -> list[dict]:
    """Run npm audit and parse results for dependency vulnerabilities."""
    findings = []
    try:
        result = subprocess.run(
            ['npm', 'audit', '--json'],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=TOOL_TIMEOUT_LONG
        )
        if result.returncode in [0, 1]:
            audit_data = json.loads(result.stdout)
            vulnerabilities = audit_data.get('vulnerabilities', {})
            for pkg_name, vuln_info in vulnerabilities.items():
                severity = vuln_info.get('severity', 'medium').upper()
                finding = {
                    'type': 'DEPENDENCY_VULNERABILITY',
                    'severity': severity if severity in ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW'] else 'MEDIUM',
                    'endpoint': f"npm:{pkg_name}",
                    'evidence': {
                        'package': pkg_name,
                        'version': vuln_info.get('version', 'unknown'),
                        'severity': vuln_info.get('severity', 'medium'),
                        'via': vuln_info.get('via', []),
                        'fix_available': vuln_info.get('fixAvailable', False),
                        'title': f"Vulnerability in {pkg_name}",
                    },
                    'confidence': 0.95,
                    'tool': 'npm_audit',
                }
                findings.append(finding)
    except json.JSONDecodeError as e:
        logger.warning(f"npm audit output parse failed: {e}")
    except Exception as e:
        logger.error(f"npm audit failed: {e}")
    return findings


def run_pip_audit(repo_path: str) -> list[dict]:
    """Run pip-audit for Python dependencies."""
    findings = []
    try:
        result = subprocess.run(
            ['pip-audit', '--format', 'json', '--quiet'],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=TOOL_TIMEOUT_LONG
        )
        if result.returncode in [0, 1] and result.stdout.strip():
            audit_data = json.loads(result.stdout)
            for vuln in audit_data:
                severity = vuln.get('severity', 'MEDIUM').upper()
                finding = {
                    'type': 'DEPENDENCY_VULNERABILITY',
                    'severity': severity if severity in ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW'] else 'MEDIUM',
                    'endpoint': f"pypi:{vuln.get('name', 'unknown')}",
                    'evidence': {
                        'package': vuln.get('name', ''),
                        'version': vuln.get('version', ''),
                        'fix_version': vuln.get('fix_version', ''),
                        'vulnerable_versions': vuln.get('vulnerable_versions', ''),
                        'vulnerability_id': vuln.get('vulnerability_id', ''),
                        'title': vuln.get('name', 'Unknown'),
                    },
                    'confidence': 0.95,
                    'tool': 'pip_audit',
                }
                findings.append(finding)
    except json.JSONDecodeError as e:
        logger.warning(f"pip-audit output parse failed: {e}")
    except Exception as e:
        logger.error(f"pip-audit failed: {e}")
    return findings


def run_govulncheck(repo_path: str) -> list[dict]:
    """Run govulncheck for Go vulnerabilities."""
    findings = []
    try:
        result = subprocess.run(
            ['govulncheck', './...', '-json'],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=TOOL_TIMEOUT_LONG
        )
        if result.stdout:
            for line in result.stdout.strip().split('\n'):
                if not line:
                    continue
                try:
                    vuln = json.loads(line)
                    severity = 'HIGH' if vuln.get('severity') == 'HIGH' else 'MEDIUM'
                    finding = {
                        'type': 'DEPENDENCY_VULNERABILITY',
                        'severity': severity,
                        'endpoint': f"go:{vuln.get('module', '')}",
                        'evidence': {
                            'module': vuln.get('module', ''),
                            'version': vuln.get('version', ''),
                            'fixed_version': vuln.get('fixed_version', ''),
                            'vulnerability': vuln.get('vulnerability', {}),
                            'title': vuln.get('vulnerability', {}).get('title', 'Go Vulnerability'),
                        },
                        'confidence': 0.95,
                        'tool': 'govulncheck',
                    }
                    findings.append(finding)
                except json.JSONDecodeError:
                    continue
    except Exception as e:
        logger.error(f"govulncheck failed: {e}")
    return findings


def check_maven_dependencies(repo_path: str) -> list[dict]:
    """Check Maven dependencies for known vulnerabilities using pom.xml parsing."""
    findings = []
    try:
        import xml.etree.ElementTree as ET

        pom_files = glob.glob(os.path.join(repo_path, '**/pom.xml'), recursive=True)
        for pom_file in pom_files:
            try:
                tree = ET.parse(pom_file)
                root = tree.getroot()

                ns = {'maven': 'http://maven.apache.org/POM/4.0.0'}

                deps = root.findall('.//maven:dependency', ns)
                for dep in deps:
                    group_id = dep.find('maven:groupId', ns)
                    artifact_id = dep.find('maven:artifactId', ns)
                    version = dep.find('maven:version', ns)

                    if group_id is not None and artifact_id is not None:
                        finding = {
                            'type': 'DEPENDENCY_LISTING',
                            'severity': 'INFO',
                            'endpoint': f"maven:{group_id.text}:{artifact_id.text}",
                            'evidence': {
                                'group_id': group_id.text,
                                'artifact_id': artifact_id.text,
                                'version': version.text if version is not None else 'unknown',
                                'pom_file': os.path.relpath(pom_file, repo_path),
                                'title': f"Maven dependency: {group_id.text}:{artifact_id.text}",
                            },
                            'confidence': 1.0,
                            'tool': 'maven_check',
                        }
                        findings.append(finding)
            except ET.ParseError as e:
                logger.warning(f"Failed to parse {pom_file}: {e}")
    except Exception as e:
        logger.error(f"Maven dependency check failed: {e}")
    return findings


def execute_repo_scan(orchestrator, repo_url: str, budget: dict, aggressiveness: str = DEFAULT_AGGRESSIVENESS, custom_rules_path: str = None) -> list[dict]:
    """
    Execute comprehensive repository scan using multiple SAST/DAST tools.

    Args:
        orchestrator: Orchestrator instance
        repo_url: GitHub/GitLab repo URL
        budget: Budget configuration
        aggressiveness: Scan aggressiveness level (default, high, extreme)
        custom_rules_path: Optional path to additional Semgrep/custom rules

    Returns:
        List of code vulnerability findings
    """
    slog = ScanLogger("repo_scan", engagement_id=orchestrator.engagement_id if hasattr(orchestrator, 'engagement_id') else "")
    slog.phase_header("EXECUTE REPO SCAN", repo=repo_url, aggressiveness=aggressiveness)
    all_findings = []
    agg = aggressiveness or DEFAULT_AGGRESSIVENESS

    # Get path to custom semgrep rules
    rules_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "semgrep_rules")

    temp_dir = tempfile.mkdtemp(prefix="argus_repo_scan_")
    try:
        # Aggressiveness config for repo scans
        clone_depth = ["--depth", "1"] if agg == "default" else ["--depth", "50"] if agg == "high" else []
        semgrep_timeout = TOOL_TIMEOUT_LONG if agg == "default" else 600 if agg == "high" else 1200
        custom_rule_limit = 3 if agg == "default" else 6 if agg == "high" else 999

        # Common exclude patterns for noise reduction
        exclude_args = [
            "--exclude", "node_modules",
            "--exclude", "vendor",
            "--exclude", ".git",
            "--exclude", "dist",
            "--exclude", "build",
            "--exclude", "*.min.js",
            "--exclude", "*.map",
            "--exclude", "coverage",
            "--exclude", ".next",
            "--exclude", ".nuxt",
        ]

        # Helper to deduplicate findings by endpoint + type. When two findings
        # share the same key, the one with higher severity wins (prevents a
        # LOW finding from suppressing a CRITICAL one from a different tool).
        _sev_rank = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1, "INFO": 0}
        seen: dict[str, int] = {}
        def add_finding(finding: dict):
            key = f"{finding.get('endpoint', '')}:{finding.get('type', '')}:{finding.get('evidence', {}).get('check_id', '') or finding.get('evidence', {}).get('cve_id', '')}"
            sev = finding.get('severity', 'INFO')
            rank = _sev_rank.get(sev, 0)
            if key not in seen:
                seen[key] = len(all_findings)
                all_findings.append(finding)
            else:
                idx = seen[key]
                existing_sev = all_findings[idx].get('severity', 'INFO')
                existing_rank = _sev_rank.get(existing_sev, 0)
                if rank > existing_rank:
                    all_findings[idx] = finding

        def _emit(tool: str, activity: str, status: str, items: int = None):
            orchestrator.ws_publisher.publish_scanner_activity(
                engagement_id=orchestrator.engagement_id,
                tool_name=tool,
                activity=activity,
                status=status,
                target=repo_url,
                items_found=items,
            )

        # ── Clone repository ──
        clone_cmd = ["git", "clone"] + clone_depth + ["--", repo_url, temp_dir]
        clone_timeout = 120 if agg in ("default", "high") else TOOL_TIMEOUT_LONG
        clone_result = subprocess.run(
            clone_cmd,
            capture_output=True,
            text=True,
            timeout=clone_timeout
        )

        if clone_result.returncode != 0:
            err_msg = clone_result.stderr[:500] if clone_result.stderr else "Unknown clone error"
            logger.warning(f"Failed to clone repo {repo_url}: {err_msg}")
            _emit("git", f"Clone failed: {err_msg[:200]}", "failed")
            raise RuntimeError(f"REPO_CLONE_FAILED:{repo_url}:{err_msg}")

        _emit("git", f"Cloned repository ({'shallow' if clone_depth else 'full'} clone)", "completed")

        # ── Detect dominant language for language-specific rules ──
        detected_langs = set()
        if os.path.exists(os.path.join(temp_dir, "package.json")) or \
           glob.glob(os.path.join(temp_dir, "**/*.js"), recursive=True) or \
           glob.glob(os.path.join(temp_dir, "**/*.ts"), recursive=True):
            detected_langs.add("javascript")
        if os.path.exists(os.path.join(temp_dir, "requirements.txt")) or \
           os.path.exists(os.path.join(temp_dir, "Pipfile")) or \
           os.path.exists(os.path.join(temp_dir, "setup.py")) or \
           glob.glob(os.path.join(temp_dir, "**/*.py"), recursive=True):
            detected_langs.add("python")
        if os.path.exists(os.path.join(temp_dir, "go.mod")) or \
           glob.glob(os.path.join(temp_dir, "**/*.go"), recursive=True):
            detected_langs.add("go")
        if os.path.exists(os.path.join(temp_dir, "Cargo.toml")) or \
           glob.glob(os.path.join(temp_dir, "**/*.rs"), recursive=True):
            detected_langs.add("rust")
        if os.path.exists(os.path.join(temp_dir, "Gemfile")) or \
           glob.glob(os.path.join(temp_dir, "**/*.rb"), recursive=True):
            detected_langs.add("ruby")
        if os.path.exists(os.path.join(temp_dir, "pom.xml")) or \
           os.path.exists(os.path.join(temp_dir, "build.gradle")) or \
           glob.glob(os.path.join(temp_dir, "**/*.java"), recursive=True):
            detected_langs.add("java")
        if glob.glob(os.path.join(temp_dir, "**/*.php"), recursive=True):
            detected_langs.add("php")

        # Map to semgrep registry configs
        lang_registry_map = {
            "javascript": ["p/javascript", "p/secrets"],
            "python":     ["p/python", "p/secrets"],
            "go":         ["p/golang", "p/secrets"],
            "rust":       ["p/rust", "p/secrets"],
            "ruby":       ["p/ruby", "p/secrets"],
            "java":       ["p/java", "p/secrets"],
            "php":        ["p/php", "p/secrets"],
        }

        # ── 1. Gitleaks: secret detection in git history ──
        slog.tool_start("gitleaks", [repo_url])
        _emit("gitleaks", "Scanning git history for leaked secrets", "started")
        try:
            gitleaks_cmd = [
                "gitleaks", "detect", "--source", temp_dir,
                "--verbose", "--json",
            ]
            if agg == "high":
                gitleaks_cmd.extend(["--max-target-megabytes", "50"])
            elif agg == "extreme":
                gitleaks_cmd.extend(["--follow-symlinks", "--max-target-megabytes", "100"])

            gitleaks_result = orchestrator.tool_runner.run(
                "gitleaks", gitleaks_cmd, timeout=TOOL_TIMEOUT_DEFAULT if agg == "default" else TOOL_TIMEOUT_LONG
            )
            if gitleaks_result.success:
                parsed = orchestrator.parser.parse("gitleaks", gitleaks_result.stdout)
                count = 0
                for p in parsed:
                    normalized = orchestrator._normalize_finding(p, "gitleaks")
                    if normalized:
                        add_finding(normalized)
                        count += 1
                _emit("gitleaks", f"Git history scan complete — found {count} secrets", "completed", items=count)
            else:
                _emit("gitleaks", "No secrets found in git history", "completed", items=0)
        except Exception as e:
            _emit("gitleaks", f"Secret scan failed: {str(e)}", "failed")
            logger.warning(f"Gitleaks failed: {e}")

        # ── 2. Trufflehog: parallel git history secret scanning ──
        slog.tool_start("trufflehog", [repo_url])
        _emit("trufflehog", "Scanning git history with trufflehog", "started")
        try:
            # Build trufflehog args — only include --since-commit for default mode
            trufflehog_args = [
                "git", temp_dir,
                "--json",
                "--no-update",
                "--fail",
                "--max-depth", "1" if agg == "default" else "5" if agg == "high" else "50",
            ]
            if agg == "default":
                trufflehog_args.extend(["--since-commit", "HEAD~100"])
            trufflehog_result = orchestrator.tool_runner.run(
                "trufflehog",
                trufflehog_args,
                timeout=TOOL_TIMEOUT_LONG,
            )
            if trufflehog_result.success and trufflehog_result.stdout.strip():
                try:
                    count = 0
                    for line in trufflehog_result.stdout.strip().split("\n"):
                        if not line.strip():
                            continue
                        parsed = json.loads(line)
                        severity = "CRITICAL" if parsed.get("verified", False) else "HIGH"
                        finding = {
                            "type": f"TRUFFLEHOG_{parsed.get('detector_name', 'UNKNOWN').upper().replace(' ', '_')}",
                            "severity": severity,
                            "endpoint": f"commit:{parsed.get('commit', '')}:{parsed.get('path', '')}",
                            "evidence": {
                                "commit": parsed.get("commit", ""),
                                "path": parsed.get("path", ""),
                                "detector": parsed.get("detector_name", ""),
                                "verified": parsed.get("verified", False),
                                "redacted": parsed.get("redacted", ""),
                            },
                            "confidence": 0.95 if parsed.get("verified", False) else 0.75,
                            "tool": "trufflehog",
                        }
                        normalized = orchestrator._normalize_finding(finding, "trufflehog")
                        if normalized:
                            add_finding(normalized)
                            count += 1
                    _emit("trufflehog", f"Trufflehog scan complete — found {count} secrets", "completed", items=count)
                except json.JSONDecodeError:
                    _emit("trufflehog", "Trufflehog output could not be parsed", "failed")
            else:
                _emit("trufflehog", "No trufflehog secrets found", "completed", items=0)
        except Exception as e:
            _emit("trufflehog", f"Trufflehog scan failed: {str(e)}", "failed")
            logger.warning(f"Trufflehog failed: {e}")

        # ── 3. Working tree secret check ──
        slog.tool_start("secret-scan", [repo_url])
        _emit("secret-scan", "Scanning working tree for exposed secrets", "started")
        try:
            wt_count = 0
            seen_wt = set()
            # Private keys in .pem / .key files
            for pattern in ("**/*.pem", "**/*.key", "**/*.p12", "**/*.pfx", "**/*.asc"):
                for fpath in glob.glob(os.path.join(temp_dir, pattern), recursive=True):
                    # Guard against symlink escapes
                    if not os.path.realpath(fpath).startswith(os.path.realpath(temp_dir)):
                        continue
                    rel = os.path.relpath(fpath, temp_dir)
                    key_id = f"private_key:{rel}"
                    if key_id in seen_wt:
                        continue
                    seen_wt.add(key_id)
                    try:
                        with open(fpath, errors="ignore") as fh:
                            content = fh.read(2000)
                        if "PRIVATE KEY" in content or "BEGIN RSA" in content or "BEGIN EC" in content or "BEGIN DSA" in content or "BEGIN OPENSSH" in content:
                            normalized = orchestrator._normalize_finding({
                                "type": "EXPOSED_PRIVATE_KEY",
                                "severity": "CRITICAL",
                                "endpoint": f"file:{rel}",
                                "evidence": {"file": rel, "content_preview": content[:200]},
                                "confidence": 0.95,
                                "tool": "secret-scan",
                            }, "secret-scan")
                            if normalized:
                                add_finding(normalized)
                                wt_count += 1
                    except Exception:
                        pass
            # .env files with populated values
            for fpath in glob.glob(os.path.join(temp_dir, ".env*"), recursive=False):
                # Guard against symlink escapes
                if not os.path.realpath(fpath).startswith(os.path.realpath(temp_dir)):
                    continue
                rel = os.path.relpath(fpath, temp_dir)
                key_id = f"env_file:{rel}"
                if key_id in seen_wt:
                    continue
                seen_wt.add(key_id)
                try:
                    with open(fpath, errors="ignore") as fh:
                        content = fh.read(5000)
                    populated = [line.strip() for line in content.split("\n") if "=" in line and line.strip() and not line.strip().startswith("#")]
                    if populated:
                        masked = []
                        for line in populated[:10]:
                            key, _, val = line.partition("=")
                            masked.append(f"{key}=***" if val else line)
                        normalized = orchestrator._normalize_finding({
                            "type": "EXPOSED_ENV_FILE",
                            "severity": "HIGH",
                            "endpoint": f"file:{rel}",
                            "evidence": {
                                "file": rel,
                                "populated_keys": [line.split("=")[0].strip() for line in populated[:20]],
                                "lines": masked,
                                "count": len(populated),
                            },
                            "confidence": 0.90,
                            "tool": "secret-scan",
                        }, "secret-scan")
                        if normalized:
                            add_finding(normalized)
                            wt_count += 1
                except Exception:
                    pass
            # Config files with password/secret/private_key keys
            for pattern in ("**/*.yml", "**/*.yaml", "**/*.conf", "**/*.cfg", "**/*.ini", "**/*.toml"):
                for fpath in glob.glob(os.path.join(temp_dir, pattern), recursive=True):
                    # Guard against symlink escapes
                    if not os.path.realpath(fpath).startswith(os.path.realpath(temp_dir)):
                        continue
                    rel = os.path.relpath(fpath, temp_dir)
                    key_id = f"config_secret:{rel}"
                    if key_id in seen_wt:
                        continue
                    seen_wt.add(key_id)
                    try:
                        with open(fpath, errors="ignore") as fh:
                            content = fh.read(10000)
                        secret_keys = re.findall(r'^\s*(password|secret|private_key|api_key|api_secret|auth_token|access_token|db_password|connection_string)\s*[:=]\s*["\']?([^"\'#\s]+)["\']?\s*$', content, re.MULTILINE | re.IGNORECASE)
                        if secret_keys:
                            normalized = orchestrator._normalize_finding({
                                "type": "EXPOSED_CONFIG_SECRET",
                                "severity": "HIGH",
                                "endpoint": f"file:{rel}",
                                "evidence": {
                                    "file": rel,
                                    "exposed_keys": [f"{k}=***" for k, v in secret_keys[:15]],
                                    "count": len(secret_keys),
                                },
                                "confidence": 0.85,
                                "tool": "secret-scan",
                            }, "secret-scan")
                            if normalized:
                                add_finding(normalized)
                                wt_count += 1
                    except Exception:
                        pass
            _emit("secret-scan", f"Working tree secret scan complete — found {wt_count} issues", "completed", items=wt_count)
        except Exception as e:
            _emit("secret-scan", f"Working tree secret scan failed: {str(e)}", "failed")
            logger.warning(f"Working tree secret scan failed: {e}")

        # ── 4. Trivy: dependency vulnerability scanning ──
        slog.tool_start("trivy", [repo_url])
        _emit("trivy", "Scanning dependencies for known CVEs", "started")
        try:
            trivy_scanners = "vuln"
            if agg == "high":
                trivy_scanners = "vuln,misconfig"
            elif agg == "extreme":
                trivy_scanners = "vuln,misconfig,secret"

            trivy_result = orchestrator.tool_runner.run(
                "trivy",
                [
                    "fs", "--scanners", trivy_scanners,
                    "--skip-dirs", "node_modules,vendor,dist,build,.git,coverage",
                    "--format", "json", temp_dir,
                ],
                timeout=TOOL_TIMEOUT_LONG if agg == "default" else 600,
            )
            if trivy_result.success:
                parsed = orchestrator.parser.parse("trivy", trivy_result.stdout)
                count = 0
                for p in parsed:
                    normalized = orchestrator._normalize_finding(p, "trivy")
                    if normalized:
                        add_finding(normalized)
                        count += 1
                _emit("trivy", f"Dependency scan complete — found {count} CVEs", "completed", items=count)
            else:
                _emit("trivy", "No dependency vulnerabilities found", "completed", items=0)
        except Exception as e:
            _emit("trivy", f"Dependency scan failed: {str(e)}", "failed")
            logger.warning(f"Trivy failed: {e}")

        # ── 3. Bandit: Python security scanning ──
        if "python" in detected_langs:
            slog.tool_start("bandit", [repo_url])
            _emit("bandit", "Running Bandit Python security scanner", "started")
            try:
                bandit_result = orchestrator.tool_runner.run(
                    "bandit",
                    [
                        "-r", temp_dir,
                        "-f", "json",
                        "-ll",
                        "-ii",
                        "-x", ".git,node_modules,vendor,dist,build,coverage",
                    ],
                    timeout=TOOL_TIMEOUT_LONG if agg == "default" else 600,
                )
                if bandit_result.success:
                    try:
                        bandit_data = json.loads(bandit_result.stdout)
                        bandit_results = bandit_data.get("results", [])
                        count = 0
                        for issue in bandit_results:
                            severity = issue.get("issue_severity", "LOW").upper()
                            finding = {
                                "type": f"BANDIT_{issue.get('test_id', 'UNKNOWN')}",
                                "severity": severity if severity in ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"] else "LOW",
                                "endpoint": f"file:{issue.get('filename', '')}:{issue.get('line_number', 0)}",
                                "evidence": {
                                    "file": issue.get("filename", ""),
                                    "line": issue.get("line_number", 0),
                                    "code": issue.get("code", ""),
                                    "issue_text": issue.get("issue_text", ""),
                                    "test_name": issue.get("test_name", ""),
                                },
                                "confidence": 0.90,
                                "tool": "bandit",
                            }
                            normalized = orchestrator._normalize_finding(finding, "bandit")
                            if normalized:
                                add_finding(normalized)
                                count += 1
                        _emit("bandit", f"Bandit scan complete — found {count} issues", "completed", items=count)
                    except json.JSONDecodeError:
                        _emit("bandit", "Bandit output could not be parsed", "failed")
                else:
                    _emit("bandit", "No Bandit issues found or scan failed", "completed", items=0)
            except Exception as e:
                _emit("bandit", f"Bandit scan failed: {str(e)}", "failed")
                logger.warning(f"Bandit failed: {e}")

        # ── 4. Brakeman: Ruby on Rails security scanning ──
        if "ruby" in detected_langs:
            slog.tool_start("brakeman", [repo_url])
            _emit("brakeman", "Running Brakeman Rails security scanner", "started")
            try:
                brakeman_result = orchestrator.tool_runner.run(
                    "brakeman",
                    [
                        temp_dir,
                        "--format", "json",
                        "--confidence-level", "2",
                        "--separate-models",
                        "--skip-files", "vendor/.*,node_modules/.*,db/.*,test/.*,spec/.*",
                    ],
                    timeout=TOOL_TIMEOUT_LONG if agg == "default" else 600,
                )
                if brakeman_result.success and brakeman_result.stdout.strip():
                    try:
                        brakeman_data = json.loads(brakeman_result.stdout)
                        warnings = brakeman_data.get("warnings", [])
                        count = 0
                        for w in warnings:
                            confidence = w.get("confidence", "Medium")
                            sev_map = {"High": "HIGH", "Medium": "MEDIUM", "Low": "LOW", "Weak": "LOW"}
                            finding = {
                                "type": f"BRAKEMAN_{w.get('warning_type', 'UNKNOWN').upper().replace(' ', '_')}",
                                "severity": sev_map.get(confidence, "MEDIUM"),
                                "endpoint": f"file:{w.get('file', '')}:{w.get('line', 0)}",
                                "evidence": {
                                    "file": w.get("file", ""),
                                    "line": w.get("line", 0),
                                    "code": w.get("code", ""),
                                    "message": w.get("message", ""),
                                    "warning_type": w.get("warning_type", ""),
                                    "confidence": confidence,
                                },
                                "confidence": 0.85,
                                "tool": "brakeman",
                            }
                            normalized = orchestrator._normalize_finding(finding, "brakeman")
                            if normalized:
                                add_finding(normalized)
                                count += 1
                        _emit("brakeman", f"Brakeman scan complete — found {count} warnings", "completed", items=count)
                    except json.JSONDecodeError:
                        _emit("brakeman", "Brakeman output could not be parsed", "failed")
                else:
                    _emit("brakeman", "No Brakeman warnings found", "completed", items=0)
            except Exception as e:
                _emit("brakeman", f"Brakeman scan failed: {str(e)}", "failed")
                logger.warning(f"Brakeman failed: {e}")

        # ── 5. Gosec: Go security scanning ──
        if "go" in detected_langs:
            slog.tool_start("gosec", [repo_url])
            _emit("gosec", "Running Gosec Go security scanner", "started")
            try:
                gosec_result = orchestrator.tool_runner.run(
                    "gosec",
                    [
                        "-fmt=json",
                        "-quiet",
                        "-exclude-dir=node_modules",
                        "-exclude-dir=vendor",
                        "-exclude-dir=.git",
                        temp_dir,
                    ],
                    timeout=TOOL_TIMEOUT_LONG if agg == "default" else 600,
                )
                if gosec_result.success and gosec_result.stdout.strip():
                    try:
                        gosec_data = json.loads(gosec_result.stdout)
                        issues = gosec_data.get("Issues", [])
                        count = 0
                        for issue in issues:
                            severity = issue.get("severity", "MEDIUM").upper()
                            finding = {
                                "type": f"GOSEC_{issue.get('rule_id', 'UNKNOWN')}",
                                "severity": severity if severity in ["CRITICAL", "HIGH", "MEDIUM", "LOW"] else "MEDIUM",
                                "endpoint": f"file:{issue.get('file', '')}:{issue.get('line', 0)}",
                                "evidence": {
                                    "file": issue.get("file", ""),
                                    "line": issue.get("line", 0),
                                    "code": issue.get("code", ""),
                                    "details": issue.get("details", ""),
                                    "rule_id": issue.get("rule_id", ""),
                                    "cwe": issue.get("cwe", {}).get("id", "") if isinstance(issue.get("cwe"), dict) else "",
                                },
                                "confidence": 0.85,
                                "tool": "gosec",
                            }
                            normalized = orchestrator._normalize_finding(finding, "gosec")
                            if normalized:
                                add_finding(normalized)
                                count += 1
                        _emit("gosec", f"Gosec scan complete — found {count} issues", "completed", items=count)
                    except json.JSONDecodeError:
                        _emit("gosec", "Gosec output could not be parsed", "failed")
                else:
                    _emit("gosec", "No Gosec issues found", "completed", items=0)
            except Exception as e:
                _emit("gosec", f"Gosec scan failed: {str(e)}", "failed")
                logger.warning(f"Gosec failed: {e}")

        # ── 6. ESLint: JavaScript/TypeScript security scanning ──
        if "javascript" in detected_langs:
            slog.tool_start("eslint", [repo_url])
            _emit("eslint", "Running ESLint security scanner", "started")
            try:
                eslint_result = orchestrator.tool_runner.run(
                    "eslint",
                    [
                        temp_dir,
                        "--ext", ".js,.jsx,.ts,.tsx",
                        "--format", "json",
                        "--no-eslintrc",
                        "--rule", '{"security/detect-object-injection":"warn","security/detect-non-literal-fs-filename":"warn","security/detect-possible-timing-attacks":"warn","security/detect-eval-with-expression":"error","security/detect-no-csrf-before-method-override":"warn","security/detect-buffer-noassert":"error","security/detect-child-process":"warn","security/detect-disable-mustache-escape":"error","security/detect-new-buffer":"warn","security/detect-unsafe-regex":"error","security/detect-bidi-characters":"warn","security/detect-non-literal-require":"warn","security/detect-pseudoRandomBytes":"warn"}',
                    ],
                    timeout=TOOL_TIMEOUT_LONG if agg == "default" else 600,
                )
                if eslint_result.success and eslint_result.stdout.strip():
                    try:
                        eslint_data = json.loads(eslint_result.stdout)
                        count = 0
                        for file_result in eslint_data:
                            file_path = file_result.get("filePath", "")
                            for msg in file_result.get("messages", []):
                                rule_id = msg.get("ruleId", "")
                                if not rule_id or not rule_id.startswith("security/"):
                                    continue
                                severity_map = {1: "LOW", 2: "MEDIUM"}
                                finding = {
                                    "type": f"ESLINT_{rule_id.replace('/', '_').upper()}",
                                    "severity": severity_map.get(msg.get("severity", 1), "LOW"),
                                    "endpoint": f"file:{file_path}:{msg.get('line', 0)}",
                                    "evidence": {
                                        "file": file_path,
                                        "line": msg.get("line", 0),
                                        "column": msg.get("column", 0),
                                        "message": msg.get("message", ""),
                                        "rule_id": rule_id,
                                    },
                                    "confidence": 0.85,
                                    "tool": "eslint",
                                }
                                normalized = orchestrator._normalize_finding(finding, "eslint")
                                if normalized:
                                    add_finding(normalized)
                                    count += 1
                        _emit("eslint", f"ESLint security scan complete — found {count} issues", "completed", items=count)
                    except json.JSONDecodeError:
                        _emit("eslint", "ESLint output could not be parsed", "failed")
                else:
                    _emit("eslint", "No ESLint security issues found", "completed", items=0)
            except Exception as e:
                _emit("eslint", f"ESLint scan failed: {str(e)}", "failed")
                logger.warning(f"ESLint failed: {e}")

        # ── 7. PHPCS: PHP security scanning ──
        if "php" in detected_langs:
            slog.tool_start("phpcs", [repo_url])
            _emit("phpcs", "Running PHP CodeSniffer security audit", "started")
            try:
                phpcs_result = orchestrator.tool_runner.run(
                    "phpcs",
                    [
                        "--standard=Security",
                        "--extensions=php",
                        "--report=json",
                        "--ignore=*/vendor/*,*/node_modules/*,*/tests/*,*/test/*",
                        "-q",
                        temp_dir,
                    ],
                    timeout=TOOL_TIMEOUT_LONG if agg == "default" else 600,
                )
                if phpcs_result.success and phpcs_result.stdout.strip():
                    try:
                        phpcs_data = json.loads(phpcs_result.stdout)
                        count = 0
                        for file_path, file_result in phpcs_data.get("files", {}).items():
                            for violation in file_result.get("messages", []):
                                severity = "HIGH" if violation.get("type") == "ERROR" else "MEDIUM" if violation.get("type") == "WARNING" else "LOW"
                                source = violation.get("source", "")
                                finding = {
                                    "type": f"PHPCS_{source.replace('.', '_').upper() if source else 'SECURITY'}",
                                    "severity": severity,
                                    "endpoint": f"file:{file_path}:{violation.get('line', 0)}",
                                    "evidence": {
                                        "file": file_path,
                                        "line": violation.get("line", 0),
                                        "column": violation.get("column", 0),
                                        "message": violation.get("message", ""),
                                        "source": source,
                                        "type": violation.get("type", ""),
                                    },
                                    "confidence": 0.85,
                                    "tool": "phpcs",
                                }
                                normalized = orchestrator._normalize_finding(finding, "phpcs")
                                if normalized:
                                    add_finding(normalized)
                                    count += 1
                        _emit("phpcs", f"PHPCS security audit complete — found {count} issues", "completed", items=count)
                    except json.JSONDecodeError:
                        _emit("phpcs", "PHPCS output could not be parsed", "failed")
                else:
                    _emit("phpcs", "No PHPCS security issues found", "completed", items=0)
            except Exception as e:
                _emit("phpcs", f"PHPCS scan failed: {str(e)}", "failed")
                logger.warning(f"PHPCS failed: {e}")

        # ── 8. SpotBugs: Java/Kotlin security scanning ──
        if "java" in detected_langs:
            slog.tool_start("spotbugs", [repo_url])
            _emit("spotbugs", "Running SpotBugs Java security scanner", "started")
            try:
                spotbugs_result = orchestrator.tool_runner.run(
                    "spotbugs",
                    [
                        "-textui",
                        "-effort:max",
                        "-low",
                        "-progress",
                        "-xml:withMessages",
                        temp_dir,
                    ],
                    timeout=TOOL_TIMEOUT_LONG if agg == "default" else 600,
                )
                if spotbugs_result.success and spotbugs_result.stdout.strip():
                    try:
                        import xml.etree.ElementTree as ET
                        root = ET.fromstring(spotbugs_result.stdout)
                        count = 0
                        for bug_instance in root.findall(".//BugInstance"):
                            pattern = bug_instance.get("type", "UNKNOWN")
                            rank = int(bug_instance.get("rank", "20"))
                            severity = "CRITICAL" if rank <= 5 else "HIGH" if rank <= 10 else "MEDIUM" if rank <= 15 else "LOW"
                            source_line = bug_instance.find("SourceLine")
                            file_path = source_line.get("sourcepath", "") if source_line is not None else ""
                            line_num = int(source_line.get("start", 0)) if source_line is not None else 0
                            short_msg = bug_instance.find("ShortMessage")
                            long_msg = bug_instance.find("LongMessage")
                            message = (long_msg.text if long_msg is not None and long_msg.text else
                                      short_msg.text if short_msg is not None and short_msg.text else pattern)
                            finding = {
                                "type": f"SPOTBUGS_{pattern}",
                                "severity": severity,
                                "endpoint": f"file:{file_path}:{line_num}",
                                "evidence": {
                                    "file": file_path,
                                    "line": line_num,
                                    "message": message,
                                    "pattern": pattern,
                                    "rank": rank,
                                },
                                "confidence": 0.85,
                                "tool": "spotbugs",
                            }
                            normalized = orchestrator._normalize_finding(finding, "spotbugs")
                            if normalized:
                                add_finding(normalized)
                                count += 1
                        _emit("spotbugs", f"SpotBugs scan complete — found {count} bugs", "completed", items=count)
                    except Exception:
                        _emit("spotbugs", "SpotBugs output could not be parsed", "failed")
                else:
                    _emit("spotbugs", "No SpotBugs issues found", "completed", items=0)
            except Exception as e:
                _emit("spotbugs", f"SpotBugs scan failed: {str(e)}", "failed")
                logger.warning(f"SpotBugs failed: {e}")

        # ── 9. Snyk: dependency vulnerability scanning ──
        slog.tool_start("snyk", [repo_url])
        _emit("snyk", "Running Snyk dependency vulnerability scan", "started")
        try:
            snyk_result = orchestrator.tool_runner.run(
                "snyk",
                [
                    "test", temp_dir,
                    "--json",
                    "--severity-threshold", "low" if agg == "extreme" else "medium",
                ],
                timeout=TOOL_TIMEOUT_LONG if agg == "default" else 600,
            )
            count = 0
            if snyk_result.success:
                try:
                    snyk_data = json.loads(snyk_result.stdout)
                    vulns = snyk_data.get("vulnerabilities", [])
                    for vuln in vulns:
                        severity = vuln.get("severity", "low").upper()
                        finding = {
                            "type": "SNYK_VULNERABILITY",
                            "severity": severity if severity in ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"] else "LOW",
                            "endpoint": vuln.get("packageName", ""),
                            "evidence": {
                                "title": vuln.get("title", ""),
                                "cve": vuln.get("identifiers", {}).get("CVE", []),
                                "cwe": vuln.get("identifiers", {}).get("CWE", []),
                                "package_name": vuln.get("packageName", ""),
                                "version": vuln.get("version", ""),
                                "fixed_in": vuln.get("fixedIn", []),
                            },
                            "confidence": 0.85,
                            "tool": "snyk",
                        }
                        normalized = orchestrator._normalize_finding(finding, "snyk")
                        if normalized:
                            add_finding(normalized)
                            count += 1
                    _emit("snyk", f"Snyk scan complete — found {count} vulnerabilities", "completed", items=count)
                except json.JSONDecodeError:
                    _emit("snyk", "Snyk output could not be parsed", "failed")
            else:
                _emit("snyk", "No Snyk vulnerabilities found", "completed", items=0)
        except Exception as e:
            _emit("snyk", f"Snyk scan failed: {str(e)}", "failed")
            logger.warning(f"Snyk failed: {e}")

        # ── 6. Additional SCA scans based on project type ──

        # npm audit for Node.js projects
        if os.path.exists(os.path.join(temp_dir, "package.json")):
            slog.tool_start("npm_audit", [repo_url])
            _emit("npm_audit", "Running npm audit for Node.js dependencies", "started")
            try:
                npm_findings = run_npm_audit(temp_dir)
                count = 0
                for f in npm_findings:
                    normalized = orchestrator._normalize_finding(f, "npm_audit")
                    if normalized:
                        add_finding(normalized)
                        count += 1
                _emit("npm_audit", f"npm audit complete — found {count} vulnerabilities", "completed", items=count)
            except Exception as e:
                _emit("npm_audit", f"npm audit failed: {str(e)}", "failed")
                logger.warning(f"npm audit failed: {e}")

        # pip-audit for Python projects
        if os.path.exists(os.path.join(temp_dir, "requirements.txt")) or \
           os.path.exists(os.path.join(temp_dir, "Pipfile")) or \
           os.path.exists(os.path.join(temp_dir, "setup.py")) or \
           os.path.exists(os.path.join(temp_dir, "pyproject.toml")):
            slog.tool_start("pip_audit", [repo_url])
            _emit("pip_audit", "Running pip-audit for Python dependencies", "started")
            try:
                pip_findings = run_pip_audit(temp_dir)
                count = 0
                for f in pip_findings:
                    normalized = orchestrator._normalize_finding(f, "pip_audit")
                    if normalized:
                        add_finding(normalized)
                        count += 1
                _emit("pip_audit", f"pip-audit complete — found {count} vulnerabilities", "completed", items=count)
            except Exception as e:
                _emit("pip_audit", f"pip-audit failed: {str(e)}", "failed")
                logger.warning(f"pip-audit failed: {e}")

        # govulncheck for Go projects
        if os.path.exists(os.path.join(temp_dir, "go.mod")):
            slog.tool_start("govulncheck", [repo_url])
            _emit("govulncheck", "Running govulncheck for Go vulnerabilities", "started")
            try:
                go_findings = run_govulncheck(temp_dir)
                count = 0
                for f in go_findings:
                    normalized = orchestrator._normalize_finding(f, "govulncheck")
                    if normalized:
                        add_finding(normalized)
                        count += 1
                _emit("govulncheck", f"govulncheck complete — found {count} vulnerabilities", "completed", items=count)
            except Exception as e:
                _emit("govulncheck", f"govulncheck failed: {str(e)}", "failed")
                logger.warning(f"govulncheck failed: {e}")

        # Maven dependency check for Java projects
        if os.path.exists(os.path.join(temp_dir, "pom.xml")):
            slog.tool_start("maven_check", [repo_url])
            _emit("maven_check", "Checking Maven dependencies", "started")
            try:
                maven_findings = check_maven_dependencies(temp_dir)
                count = 0
                for f in maven_findings:
                    normalized = orchestrator._normalize_finding(f, "maven_check")
                    if normalized:
                        add_finding(normalized)
                        count += 1
                _emit("maven_check", f"Maven check complete — found {count} dependencies", "completed", items=count)
            except Exception as e:
                _emit("maven_check", f"Maven check failed: {str(e)}", "failed")
                logger.warning(f"Maven check failed: {e}")

        # ── 7. Semgrep: static code analysis ──
        slog.tool_start("semgrep", [repo_url])
        _rules_registry = os.path.join(os.path.dirname(os.path.dirname(__file__)), "semgrep_rules", "registry")
        def _resolve_semgrep_config(cfg: str) -> list:
            """Resolve a semgrep config name to local file paths."""
            index = {
                "p/php":        ["php-ssl.yaml", "php-xss.yaml", "php-sqli.yaml", "php-csrf.yaml", "php-xxe.yaml", "php-rce.yaml", "php-session.yaml", "php-security.yaml"],
                "p/javascript": ["javascript-security.yaml"],
                "p/secrets":    ["secrets.yaml"],
            }
            files = index.get(cfg, [])
            if files:
                return [os.path.join(_rules_registry, f) for f in files if os.path.isfile(os.path.join(_rules_registry, f))]
            return [cfg] if os.path.isfile(cfg) or os.path.isdir(cfg) else []

        registry_configs = []
        for lang in detected_langs:
            configs = lang_registry_map.get(lang, [])
            for cfg in configs:
                resolved = _resolve_semgrep_config(cfg)
                for rc in resolved:
                    if rc not in registry_configs:
                        registry_configs.append(rc)

        custom_configs = []
        rule_subdirs = [
            "secrets", "auth", "injection", "xss", "ssrf",
            "csrf", "auto", "business-logic", "deserialization",
        ]
        for subdir in rule_subdirs:
            config_dir = os.path.join(rules_dir, subdir)
            if os.path.isdir(config_dir):
                custom_configs.append(config_dir)

        if custom_rules_path and os.path.isdir(custom_rules_path) or custom_rules_path and os.path.isfile(custom_rules_path):
            custom_configs.append(custom_rules_path)

        # Run Semgrep with registry configs + custom rules
        _emit("semgrep", f"Running Semgrep static analysis ({agg} mode) — {len(registry_configs)} rule sets", "started")
        try:
            semgrep_cmd = ["--json"] + exclude_args
            for config in registry_configs:
                semgrep_cmd.extend(["--config", config])
            for rules_used, config in enumerate(custom_configs):
                if rules_used >= custom_rule_limit:
                    break
                semgrep_cmd.extend(["--config", config])
            semgrep_cmd.append(temp_dir)

            semgrep_result = orchestrator.tool_runner.run(
                "semgrep", semgrep_cmd, timeout=semgrep_timeout
            )
            if semgrep_result.success:
                parsed = orchestrator.parser.parse("semgrep", semgrep_result.stdout)
                count = 0
                for p in parsed:
                    normalized = orchestrator._normalize_finding(p, "semgrep")
                    if normalized:
                        add_finding(normalized)
                        count += 1
                _emit("semgrep", f"Static analysis complete — found {count} code issues", "completed", items=count)
            else:
                logger.warning(f"Semgrep scan failed: {semgrep_result.stderr}")
                _emit("semgrep", f"Scan failed: {semgrep_result.stderr[:200]}", "failed")
        except Exception as e:
            _emit("semgrep", f"Static analysis failed: {str(e)}", "failed")
            logger.warning(f"Semgrep failed: {e}")

    except Exception as e:
        logger.warning(f"Repo scan failed: {e}")
        _emit("repo_scan", f"Repository scan failed: {str(e)}", "failed")
    finally:
        with contextlib.suppress(Exception):
            shutil.rmtree(temp_dir)

    slog.info(f"Repo scan complete: {len(all_findings)} total findings across all tools")
    _emit("repo_scan", f"Repository scan complete — {len(all_findings)} total issues found", "completed", items=len(all_findings))

    return all_findings
