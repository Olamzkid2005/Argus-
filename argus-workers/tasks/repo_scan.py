"""
Celery tasks for repository scanning phase

Scans GitHub/GitLab repositories for code vulnerabilities using Semgrep
with custom rules based on vibe-security-ultra framework.

Requirements: 4.2, 4.4, 20.1, 20.2, 20.3
"""
import os
import re
import subprocess
import logging
import json
from datetime import datetime, timezone
import uuid
from celery_app import app
from database.connection import connect

from tasks.loader import load_module
from utils.validation import validate_uuid

_orchestrator = load_module("orchestrator")
Orchestrator = _orchestrator.Orchestrator

_tracing = load_module("tracing")
TracingManager = _tracing.TracingManager

logger = logging.getLogger(__name__)

# Common open source licenses
LICENSE_PATTERNS = {
    'GPL-2.0': [r'GNU General Public License.*version 2', r'GPLv2', r'GPL-2\.0'],
    'GPL-3.0': [r'GNU General Public License.*version 3', r'GPLv3', r'GPL-3\.0'],
    'MIT': [r'MIT License', r'The MIT License'],
    'Apache-2.0': [r'Apache License[\s\S]*?version 2', r'Apache-2\.0'],
    'BSD-3-Clause': [r'BSD 3-Clause', r'New BSD License'],
    'BSD-2-Clause': [r'BSD 2-Clause', r'Simplified BSD License'],
    'LGPL': [r'GNU Lesser General Public License', r'LGPL'],
    'ISC': [r'ISC License'],
    'MPL-2.0': [r'Mozilla Public License.*2\.0'],
}

# Common secret patterns for git history scanning
SECRET_PATTERNS = {
    'aws_access_key': r'AKIA[0-9A-Z]{16}',
    'aws_secret_key': r'(?<![A-Za-z0-9/+])[A-Za-z0-9/+]{40}(?![A-Za-z0-9/+=])',
    'github_token': r'ghp_[a-zA-Z0-9]{36}',
    'github_oauth': r'gho_[a-zA-Z0-9]{36}',
    'slack_token': r'xox[bap]-[0-9]{12}-[0-9]{12}-[0-9]{12}-[a-z0-9]{32}',
    'api_key': r'api[_-]?key[_-]?[=:]+\s*["\']?[a-zA-Z0-9]{32,45}["\']?',
    'private_key': r'-----BEGIN [A-Z]+ PRIVATE KEY-----',
    'password': r'password[_-]?[=:]+\s*["\']?[^\s"\']{8,}["\']?',
}

# Default license policy configuration
_DEFAULT_LICENSE_POLICY = {
    'allowed': ['MIT', 'Apache-2.0', 'BSD-3-Clause', 'BSD-2-Clause', 'ISC'],
    'warn': ['LGPL', 'MPL-2.0'],
    'blocked': ['GPL-2.0', 'GPL-3.0'],
}


def _load_license_policy():
    """Load license policy from environment variables with defaults."""
    policy = _DEFAULT_LICENSE_POLICY.copy()
    blocked_env = os.environ.get('ARGUS_LICENSE_POLICY_BLOCKED')
    warn_env = os.environ.get('ARGUS_LICENSE_POLICY_WARN')
    allowed_env = os.environ.get('ARGUS_LICENSE_POLICY_ALLOWED')
    if blocked_env:
        policy['blocked'] = [x.strip() for x in blocked_env.split(',')]
    if warn_env:
        policy['warn'] = [x.strip() for x in warn_env.split(',')]
    if allowed_env:
        policy['allowed'] = [x.strip() for x in allowed_env.split(',')]
    return policy


LICENSE_POLICY = _load_license_policy()

_distributed_lock = load_module("distributed_lock")
LockContext = _distributed_lock.LockContext
DistributedLock = _distributed_lock.DistributedLock

_state_machine = load_module("state_machine")
EngagementStateMachine = _state_machine.EngagementStateMachine


@app.task(bind=True, name="tasks.repo_scan.run_repo_scan")
def run_repo_scan(self, engagement_id: str, repo_url: str, budget: dict, trace_id: str = None, custom_rules_path: str = None):
    """
    Execute repository scanning phase for an engagement

    Args:
        engagement_id: Engagement ID
        repo_url: GitHub/GitLab repository URL
        budget: Budget configuration
        trace_id: Optional trace_id for distributed tracing (generated if not provided)
        custom_rules_path: Optional path to additional Semgrep/custom rules
    """
    db_conn_string = os.getenv("DATABASE_URL")
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")

    # Initialize tracing manager
    tracing_manager = TracingManager(db_conn_string)

    # Create or use existing trace context
    if not trace_id:
        trace_id = tracing_manager.generate_trace_id()

    # Execute with trace context
    with tracing_manager.trace_execution(engagement_id, "repo_scan", trace_id):
        job = {
            "type": "repo_scan",
            "engagement_id": engagement_id,
            "repo_url": repo_url,
            "budget": budget,
            "trace_id": trace_id,
            "custom_rules_path": custom_rules_path,
        }

        lock = DistributedLock(redis_url)

        try:
            with LockContext(lock, engagement_id):
                state_machine = EngagementStateMachine(
                    engagement_id, db_connection_string=db_conn_string, current_state="created"
                )
                state_machine.transition("recon", "Starting repository scan")

                orchestrator = Orchestrator(engagement_id, trace_id=trace_id)
                result = orchestrator.run_repo_scan(job)

                # Generate SBOMs after dependency scanning
                if result and isinstance(result, dict):
                    dependencies = result.get('dependencies', [])
                    # Get repo path from result or use default engagement artifact path
                    repo_path = result.get('repo_path', os.path.join(os.getenv('ARTIFACTS_DIR', '/tmp/argus_artifacts'), engagement_id))
                    os.makedirs(repo_path, exist_ok=True)
                    
                    if dependencies:
                        try:
                            cyclonedx_sbom = generate_cyclonedx_sbom(repo_path, dependencies)
                            cyclonedx_path = save_sbom(cyclonedx_sbom, repo_path, format='cyclonedx')
                            
                            spdx_sbom = generate_spdx_sbom(repo_path, dependencies)
                            spdx_path = save_sbom(spdx_sbom, repo_path, format='spdx')
                            
                            result['sbom_paths'] = {
                                'cyclonedx': cyclonedx_path,
                                'spdx': spdx_path
                            }
                            logger.info(f"SBOMs generated for engagement {engagement_id}")
                        except Exception as e:
                            logger.error(f"Failed to generate SBOMs: {str(e)}")

                state_machine.transition("awaiting_approval", "Repository scan complete")

                return result
        except Exception as e:
            # Query actual current state from DB before transitioning to failed
            current_state = _get_engagement_state(engagement_id, db_conn_string)
            state_machine = EngagementStateMachine(
                engagement_id, db_connection_string=db_conn_string, current_state=current_state
            )
            state_machine.transition("failed", f"Repository scan failed: {str(e)}")
            raise


@app.task(bind=True, name="tasks.repo_scan.expand_repo_scan")
def expand_repo_scan(self, engagement_id: str, repo_url: str, additional_rules_path: str, budget: dict, trace_id: str = None):
    """
    Expand repository scan with additional custom rules

    Args:
        engagement_id: Engagement ID
        repo_url: Repository URL
        additional_rules_path: Path to additional Semgrep rules
        budget: Budget configuration
        trace_id: Optional trace_id for distributed tracing
    """
    db_conn_string = os.getenv("DATABASE_URL")
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")

    # Initialize tracing manager
    tracing_manager = TracingManager(db_conn_string)

    # Create or use existing trace context
    if not trace_id:
        trace_id = tracing_manager.generate_trace_id()

    # Execute with trace context
    with tracing_manager.trace_execution(engagement_id, "repo_scan_expand", trace_id):
        job = {
            "type": "repo_scan_expand",
            "engagement_id": engagement_id,
            "repo_url": repo_url,
            "additional_rules_path": additional_rules_path,
            "budget": budget,
            "trace_id": trace_id,
        }

        lock = DistributedLock(redis_url)

        with LockContext(lock, engagement_id):
            orchestrator = Orchestrator(engagement_id, trace_id=trace_id)
            return orchestrator.run_repo_scan(job)
        

def get_blame_for_finding(repo_path, finding):
    """
    Run git blame on the file/line associated with a finding.
    Returns blame info: author, commit, date, etc.
    """
    if 'file_path' not in finding or 'line_number' not in finding:
        return None
    
    file_path = finding['file_path']
    line_number = finding.get('line_number', 1)
    
    try:
        result = subprocess.run(
            ['git', 'blame', '-L', f'{line_number},{line_number}',
             '--porcelain', file_path],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if result.returncode == 0:
            blame_info = {}
            for line in result.stdout.split('\n'):
                if line.startswith('author '):
                    blame_info['author'] = line.split(' ', 1)[1]
                elif line.startswith('author-time '):
                    blame_info['author_time'] = line.split(' ')[1]
                elif line.startswith('committer-time '):
                    blame_info['committer_time'] = line.split(' ')[1]
                elif line.startswith('commit '):
                    blame_info['commit_hash'] = line.split(' ')[1]
                elif line.startswith('summary '):
                    blame_info['summary'] = line.split(' ', 1)[1]
            
            return blame_info
    
    except Exception as e:
        logger.error(f"Git blame failed: {e}")
    
    return None


def enrich_findings_with_blame(repo_path, findings):
    """
    Add blame information to all findings that have file/line info.
    """
    for finding in findings:
        if finding.get('type') in ['COMMITTED_SECRET', 'STATIC_ANALYSIS_FINDING']:
            blame = get_blame_for_finding(repo_path, finding)
            if blame:
                finding['blame'] = blame
                finding['introduced_by'] = blame.get('author', 'unknown')
                finding['introduced_at'] = blame.get('author_time', '')
                finding['introduced_in_commit'] = blame.get('commit_hash', '')
    
    return findings


def _get_engagement_state(engagement_id: str, db_conn_string: str) -> str:
    """
    Query the current engagement state from the database.

    Args:
        engagement_id: Engagement ID
        db_conn_string: Database connection string

    Returns:
        Current engagement status string
    """
    try:
        # Validate UUID before DB query to prevent InvalidTextRepresentation errors
        valid_id = validate_uuid(engagement_id, "engagement_id")
        conn = connect(db_conn_string)
        cursor = conn.cursor()
        cursor.execute("SELECT status FROM engagements WHERE id = %s", (valid_id,))
        row = cursor.fetchone()
        cursor.close()
        conn.close()
        return row[0] if row else "created"
    except Exception:
        return "created"


def generate_cyclonedx_sbom(repo_path, dependencies):
    """
    Generate CycloneDX SBOM for the repository.
    """
    sbom = {
        'bomFormat': 'CycloneDX',
        'specVersion': '1.4',
        'version': 1,
        'serialNumber': f'urn:uuid:{uuid.uuid4()}',
        'creationInfo': {
            'timestamp': datetime.now(timezone.utc).isoformat() + 'Z',
            'tools': [{'vendor': 'Argus', 'name': 'Security Platform', 'version': '1.0'}],
        },
        'components': [],
        'dependencies': []
    }
    
    for dep in dependencies:
        component = {
            'type': 'library',
            'bom-ref': f'pkg:{dep.get("ecosystem", "generic")}/{dep.get("name", "unknown")}@{dep.get("version", "unknown")}',
            'name': dep.get('name', 'unknown'),
            'version': dep.get('version', 'unknown'),
            'purl': f'pkg:{dep.get("ecosystem", "generic")}/{dep.get("name", "unknown")}@{dep.get("version", "unknown")}',
            'externalReferences': []
        }
        
        if dep.get('cve'):
            component['externalReferences'].append({
                'type': 'advisory',
                'url': f'https://nvd.nist.gov/vuln/detail/{dep["cve"]}'
            })
        
        sbom['components'].append(component)
        sbom['dependencies'].append({
            'ref': component['bom-ref'],
            'dependsOn': []
        })
    
    return sbom


def generate_spdx_sbom(repo_path, dependencies):
    """Generate SPDX SBOM for the repository."""
    sbom = {
        'spdxVersion': 'SPDX-2.3',
        'dataLicense': 'CC0-1.0',
        'SPDXID': 'SPDXRef-DOCUMENT',
        'name': f'SBOM-{os.path.basename(repo_path)}',
        'documentDescribes': [
            f'SPDXRef-{dep.get("name", "unknown")}' for dep in dependencies
        ],
        'packages': [],
        'relationships': []
    }
    
    for dep in dependencies:
        package = {
            'SPDXID': f'SPDXRef-{dep.get("name", "unknown")}',
            'name': dep.get('name', 'unknown'),
            'versionInfo': dep.get('version', 'unknown'),
            'downloadLocation': 'NOASSERTION',
            'filesAnalyzed': False,
        }
        
        if dep.get('cve'):
            package['externalRefs'] = [{
                'referenceCategory': 'SECURITY',
                'referenceType': 'cpe23Type',
                'referenceLocator': dep['cve'],
            }]
        
        sbom['packages'].append(package)
    
    return sbom


def save_sbom(sbom, repo_path, format='cyclonedx'):
    """Save SBOM to file in the engagement artifacts directory."""
    if format == 'cyclonedx':
        filename = os.path.join(repo_path, 'sbom-cyclonedx.json')
        with open(filename, 'w') as f:
            json.dump(sbom, f, indent=2)
    elif format == 'spdx':
        filename = os.path.join(repo_path, 'sbom-spdx.json')
        with open(filename, 'w') as f:
            json.dump(sbom, f, indent=2)
    else:
        raise ValueError(f"Unsupported SBOM format: {format}")
    
    logger.info(f"SBOM saved to {filename}")
    return filename


# ========== Section 3.1: Dependency Scanning (SCA) ==========

def run_npm_audit(repo_path):
    """Run npm audit and parse results."""
    try:
        result = subprocess.run(
            ['npm', 'audit', '--json'],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=300
        )
        if result.returncode in [0, 1]:
            audit_data = json.loads(result.stdout)
            findings = []
            vulns = audit_data.get('vulnerabilities', {})
            for vuln_type, vuln_list in vulns.items():
                for vuln in vuln_list:
                    findings.append({
                        'type': 'DEPENDENCY_VULNERABILITY',
                        'severity': vuln.get('severity', 'MEDIUM').upper(),
                        'title': vuln.get('title', vuln_type),
                        'package': vuln_type,
                        'version': vuln.get('version', 'unknown'),
                        'fix_available': vuln.get('fixAvailable', False),
                        'vulnerable_versions': vuln.get('vulnerable_versions', ''),
                        'cve': vuln.get('cves', []),
                        'cvss_score': vuln.get('cvss', {}).get('score', 0),
                    })
            return findings
    except Exception as e:
        logger.error(f"npm audit failed: {e}")
    return []

def run_pip_audit(repo_path):
    """Run pip-audit for Python dependencies."""
    try:
        result = subprocess.run(
            ['pip-audit', '--format', 'json', '--quiet'],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=300
        )
        if result.returncode == 0:
            audit_data = json.loads(result.stdout)
            findings = []
            for vuln in audit_data:
                findings.append({
                    'type': 'DEPENDENCY_VULNERABILITY',
                    'severity': vuln.get('severity', 'MEDIUM').upper(),
                    'title': vuln.get('name', 'Unknown'),
                    'package': vuln.get('package', ''),
                    'version': vuln.get('version', ''),
                    'fix_version': vuln.get('fix_version', ''),
                    'vulnerable_versions': vuln.get('vulnerable_versions', ''),
                    'cve': vuln.get('vulnerability_id', ''),
                })
            return findings
    except Exception as e:
        logger.error(f"pip-audit failed: {e}")
    return []

def run_govulncheck(repo_path):
    """Run govulncheck for Go vulnerabilities."""
    try:
        result = subprocess.run(
            ['govulncheck', './...', '-json'],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=300
        )
        if result.returncode == 0:
            vulns = json.loads(result.stdout)
            findings = []
            for vuln in vulns:
                findings.append({
                    'type': 'DEPENDENCY_VULNERABILITY',
                    'severity': 'HIGH' if vuln.get('severity') == 'HIGH' else 'MEDIUM',
                    'title': vuln.get('vulnerability', {}).get('title', 'Go Vulnerability'),
                    'package': vuln.get('module', ''),
                    'version': vuln.get('version', ''),
                    'fixed_version': vuln.get('fixed_version', ''),
                })
            return findings
    except Exception as e:
        logger.error(f"govulncheck failed: {e}")
    return []

# ========== Section 3.2: Git History Secret Scan ==========

def scan_git_history_for_secrets(repo_path):
    """Scan git history for committed secrets."""
    findings = []
    
    try:
        result = subprocess.run(
            ['git', 'log', '--all', '--patch', '--pretty=format:COMMIT:%H|AUTHOR:%an|DATE:%ai'],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=600
        )
        
        if result.returncode != 0:
            logger.warning(f"Git log failed: {result.stderr}")
            return findings
        
        current_commit = None
        current_author = None
        current_date = None
        patch_lines = []
        
        for line in result.stdout.split('\n'):
            if line.startswith('COMMIT:'):
                if current_commit and patch_lines:
                    _check_patch_for_secrets(
                        patch_lines, current_commit, current_author, 
                        current_date, repo_path, findings
                    )
                    patch_lines = []
                
                parts = line.split('|')
                current_commit = parts[0].split(':')[1] if len(parts) > 0 else 'unknown'
                current_author = parts[1].split(':')[1] if len(parts) > 1 else 'unknown'
                current_date = parts[2].split(':')[1] if len(parts) > 2 else 'unknown'
            elif line.startswith('diff ') or line.startswith('commit '):
                continue
            else:
                patch_lines.append(line)
        
        if current_commit and patch_lines:
            _check_patch_for_secrets(
                patch_lines, current_commit, current_author,
                current_date, repo_path, findings
            )
    
    except Exception as e:
        logger.error(f"Git history scan failed: {e}")
    
    return findings

def _check_patch_for_secrets(lines, commit, author, date, repo_path, findings):
    """Check patch lines for secret patterns."""
    full_text = '\n'.join(lines)
    
    for secret_type, pattern in SECRET_PATTERNS.items():
        matches = re.finditer(pattern, full_text, re.MULTILINE)
        for match in matches:
            start_pos = match.start()
            line_num = full_text[:start_pos].count('\n') + 1
            
            findings.append({
                'type': 'COMMITTED_SECRET',
                'severity': 'HIGH',
                'title': f'Secret found in git history: {secret_type}',
                'commit_hash': commit,
                'author': author,
                'date': date,
                'line_number': line_num,
                'matched_text': match.group()[:50] + '...' if len(match.group()) > 50 else match.group(),
                'file_path': _extract_file_path(lines, line_num),
            })

def _extract_file_path(lines, line_num):
    """Extract file path from surrounding context."""
    start = max(0, line_num - 10)
    for line in lines[start:line_num]:
        if line.startswith('diff --git a/'):
            return line.replace('diff --git a/', '').strip()
    return 'unknown'

# ========== Section 3.5: License Compliance ==========

def detect_license(file_path):
    """Detect license from license file content."""
    license_files = ['LICENSE', 'LICENSE.txt', 'LICENSE.md', 'COPYING']
    
    for lic_file in license_files:
        full_path = os.path.join(file_path, lic_file)
        if os.path.exists(full_path):
            with open(full_path, 'r', errors='ignore') as f:
                content = f.read()
                return _match_license(content)
    
    # Check package.json for license field
    package_json = os.path.join(file_path, 'package.json')
    if os.path.exists(package_json):
        try:
            with open(package_json, 'r') as f:
                data = json.load(f)
                if 'license' in data:
                    return data['license']
        except:
            pass
    
    return 'UNKNOWN'

def _match_license(content):
    """Match license patterns against content."""
    for license_name, patterns in LICENSE_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, content, re.IGNORECASE):
                return license_name
    return 'UNKNOWN'

def check_license_compliance(repo_path, policy=None):
    """Check license compliance for all dependencies."""
    if policy is None:
        policy = LICENSE_POLICY
    
    findings = []
    
    # Detect project license
    project_license = detect_license(repo_path)
    
    if project_license != 'UNKNOWN':
        severity = 'LOW'
        if project_license in policy['blocked']:
            severity = 'HIGH'
        elif project_license in policy['warn']:
            severity = 'MEDIUM'
        
        findings.append({
            'type': 'LICENSE_COMPLIANCE',
            'severity': severity,
            'title': f'Project license: {project_license}',
            'license': project_license,
            'file_path': 'LICENSE',
            'compliance_status': 'blocked' if project_license in policy['blocked'] else 'warn' if project_license in policy['warn'] else 'allowed',
        })
    
    return findings

# ========== Section 3.6: More SAST Tools ==========

def run_bandit(repo_path):
    """Run Bandit for Python security issues."""
    try:
        result = subprocess.run(
            ['bandit', '-r', repo_path, '-f', 'json', '-o', '-'],
            capture_output=True,
            text=True,
            timeout=300
        )
        
        if result.returncode in [0, 1]:
            data = json.loads(result.stdout)
            findings = []
            
            for issue in data.get('results', []):
                findings.append({
                    'type': 'STATIC_ANALYSIS_FINDING',
                    'severity': _map_bandit_severity(issue.get('severity', 'MEDIUM')),
                    'title': issue.get('issue_text', 'Python Security Issue'),
                    'file_path': issue.get('filename', ''),
                    'line_number': issue.get('line_number', 0),
                    'code_snippet': issue.get('code', ''),
                    'tool': 'bandit',
                    'cwe': issue.get('cwe', ''),
                    'confidence': issue.get('confidence', 'medium'),
                })
            
            return findings
    except Exception as e:
        logger.error(f"Bandit failed: {e}")
    return []

def _map_bandit_severity(severity):
    mapping = {'LOW': 'LOW', 'MEDIUM': 'MEDIUM', 'HIGH': 'HIGH'}
    return mapping.get(severity, 'MEDIUM')

def run_eslint_security(repo_path):
    """Run ESLint with security plugins."""
    try:
        result = subprocess.run(
            ['npx', 'eslint', '--ext', '.js,.jsx,.ts,.tsx', 
             '--format', 'json', repo_path],
            capture_output=True,
            text=True,
            timeout=300
        )
        
        if result.returncode in [0, 1]:
            data = json.loads(result.stdout)
            findings = []
            
            for issue in data:
                if issue.get('ruleId', '').startswith('security/'):
                    findings.append({
                        'type': 'STATIC_ANALYSIS_FINDING',
                        'severity': _map_eslint_severity(issue.get('severity', 1)),
                        'title': issue.get('message', 'JS Security Issue'),
                        'file_path': issue.get('filePath', ''),
                        'line_number': issue.get('line', 0),
                        'code_snippet': issue.get('source', ''),
                        'tool': 'eslint',
                        'rule_id': issue.get('ruleId', ''),
                    })
            
            return findings
    except Exception as e:
        logger.error(f"ESLint failed: {e}")
    return []

def _map_eslint_severity(severity):
    return 'LOW' if severity == 1 else 'MEDIUM' if severity == 2 else 'HIGH'

def run_gosec(repo_path):
    """Run gosec for Go security issues."""
    try:
        result = subprocess.run(
            ['gosec', '-fmt=json', repo_path],
            capture_output=True,
            text=True,
            timeout=300
        )
        
        if result.returncode in [0, 1]:
            data = json.loads(result.stdout)
            findings = []
            
            for issue in data.get('Issues', []):
                findings.append({
                    'type': 'STATIC_ANALYSIS_FINDING',
                    'severity': issue.get('severity', 'MEDIUM').upper(),
                    'title': issue.get('details', 'Go Security Issue'),
                    'file_path': issue.get('file', ''),
                    'line_number': issue.get('line', 0),
                    'code_snippet': issue.get('code', ''),
                    'tool': 'gosec',
                    'rule_id': issue.get('rule_id', ''),
                    'cwe': issue.get('cwe', {}).get('id', ''),
                })
            
            return findings
    except Exception as e:
        logger.error(f"gosec failed: {e}")
    return []
