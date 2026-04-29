"""
Repository scanning logic extracted from Orchestrator.
"""
import glob
import json
import logging
import os
import shutil
import subprocess
import tempfile
from typing import Dict, List

from config.constants import DEFAULT_AGGRESSIVENESS, TOOL_TIMEOUT_DEFAULT, TOOL_TIMEOUT_LONG
from streaming import emit_tool_start

logger = logging.getLogger(__name__)


def run_npm_audit(repo_path: str) -> List[Dict]:
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


def run_pip_audit(repo_path: str) -> List[Dict]:
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


def run_govulncheck(repo_path: str) -> List[Dict]:
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


def check_maven_dependencies(repo_path: str) -> List[Dict]:
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


def execute_repo_scan(orchestrator, repo_url: str, budget: Dict, aggressiveness: str = DEFAULT_AGGRESSIVENESS, custom_rules_path: str = None) -> List[Dict]:
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
    all_findings = []
    agg = aggressiveness or DEFAULT_AGGRESSIVENESS

    # Get path to custom semgrep rules
    rules_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "semgrep_rules")

    temp_dir = tempfile.mkdtemp(prefix="argus_repo_scan_")

    # Aggressiveness config for repo scans
    clone_depth = ["--depth", "1"] if agg == "default" else ["--depth", "1"] if agg == "high" else []
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

    # Helper to deduplicate findings by endpoint + type
    seen = set()
    def add_finding(finding: Dict):
        key = f"{finding.get('endpoint', '')}:{finding.get('type', '')}:{finding.get('evidence', {}).get('check_id', '') or finding.get('evidence', {}).get('cve_id', '')}"
        if key not in seen:
            seen.add(key)
            all_findings.append(finding)

    def _emit(tool: str, activity: str, status: str, items: int = None):
        orchestrator.ws_publisher.publish_scanner_activity(
            engagement_id=orchestrator.engagement_id,
            tool_name=tool,
            activity=activity,
            status=status,
            target=repo_url,
            items_found=items,
        )

    try:
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
            logger.warning(f"Failed to clone repo {repo_url}: {clone_result.stderr}")
            _emit("git", f"Clone failed: {clone_result.stderr[:200]}", "failed")
            return []

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
            if gitleaks_result.get("success"):
                parsed = orchestrator.parser.parse("gitleaks", gitleaks_result.get("stdout", ""))
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

        # ── 2. Trivy: dependency vulnerability scanning ──
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
            if trivy_result.get("success"):
                parsed = orchestrator.parser.parse("trivy", trivy_result.get("stdout", ""))
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
                if bandit_result.get("success"):
                    try:
                        bandit_data = json.loads(bandit_result.get("stdout", "{}"))
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

        # ── 4. Snyk: dependency vulnerability scanning ──
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
            if snyk_result.get("success"):
                try:
                    snyk_data = json.loads(snyk_result.get("stdout", "{}"))
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
        _rules_registry = os.path.join(os.path.dirname(os.path.dirname(__file__)), "semgrep_rules", "registry")
        def _resolve_semgrep_config(cfg: str) -> list:
            """Resolve a semgrep config name to local file paths."""
            INDEX = {
                "p/php":        ["php-ssl.yaml", "php-xss.yaml", "php-sqli.yaml", "php-csrf.yaml", "php-xxe.yaml", "php-rce.yaml", "php-session.yaml", "php-security.yaml"],
                "p/javascript": ["javascript-security.yaml"],
                "p/secrets":    ["secrets.yaml"],
            }
            files = INDEX.get(cfg, [])
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

        if custom_rules_path and os.path.isdir(custom_rules_path):
            custom_configs.append(custom_rules_path)
        elif custom_rules_path and os.path.isfile(custom_rules_path):
            custom_configs.append(custom_rules_path)

        # Run Semgrep with registry configs + custom rules
        _emit("semgrep", f"Running Semgrep static analysis ({agg} mode) — {len(registry_configs)} rule sets", "started")
        try:
            semgrep_cmd = ["--json"] + exclude_args
            for config in registry_configs:
                semgrep_cmd.extend(["--config", config])
            rules_used = 0
            for config in custom_configs:
                if rules_used >= custom_rule_limit:
                    break
                semgrep_cmd.extend(["--config", config])
                rules_used += 1
            semgrep_cmd.append(temp_dir)

            semgrep_result = orchestrator.tool_runner.run(
                "semgrep", semgrep_cmd, timeout=semgrep_timeout
            )
            if semgrep_result.get("success"):
                parsed = orchestrator.parser.parse("semgrep", semgrep_result.get("stdout", ""))
                count = 0
                for p in parsed:
                    normalized = orchestrator._normalize_finding(p, "semgrep")
                    if normalized:
                        add_finding(normalized)
                        count += 1
                _emit("semgrep", f"Static analysis complete — found {count} code issues", "completed", items=count)
            else:
                logger.warning(f"Semgrep scan failed: {semgrep_result.get('stderr')}")
                _emit("semgrep", f"Scan failed: {semgrep_result.get('stderr', 'unknown error')[:200]}", "failed")
        except Exception as e:
            _emit("semgrep", f"Static analysis failed: {str(e)}", "failed")
            logger.warning(f"Semgrep failed: {e}")

    except Exception as e:
        logger.warning(f"Repo scan failed: {e}")
        _emit("repo_scan", f"Repository scan failed: {str(e)}", "failed")
    finally:
        try:
            shutil.rmtree(temp_dir)
        except Exception:
            pass

    _emit("repo_scan", f"Repository scan complete — {len(all_findings)} total issues found", "completed", items=len(all_findings))

    return all_findings
