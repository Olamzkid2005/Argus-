import re
import os
import json
from typing import List, Dict, Set

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

# Default policy configuration (overridden by env vars if present)
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
    """
    Check license compliance for all dependencies.
    Returns list of license compliance findings.
    """
    if policy is None:
        policy = _load_license_policy()
    
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
    
    # TODO: Check dependency licenses (requires dependency list)
    
    return findings


import subprocess
import logging

logger = logging.getLogger(__name__)


def _detect_languages(repo_path: str) -> Dict[str, bool]:
    """Detect which languages are used in the repository."""
    languages = {'python': False, 'javascript': False, 'go': False}
    
    try:
        result = subprocess.run(
            ['find', repo_path, '-type', 'f', '-name', '*.py', '-o', '-name', '*.js', '-o', '-name', '*.ts', '-o', '-name', '*.tsx', '-o', '-name', '*.jsx', '-o', '-name', '*.go'],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        for file_path in result.stdout.split('\n'):
            if file_path.strip():
                if file_path.endswith('.py'):
                    languages['python'] = True
                elif any(file_path.endswith(ext) for ext in ['.js', '.ts', '.tsx', '.jsx']):
                    languages['javascript'] = True
                elif file_path.endswith('.go'):
                    languages['go'] = True
    except Exception as e:
        logger.error(f"Language detection failed: {e}")
    
    return languages


def _map_bandit_severity(severity):
    mapping = {'LOW': 'LOW', 'MEDIUM': 'MEDIUM', 'HIGH': 'HIGH'}
    return mapping.get(severity, 'MEDIUM')


def run_bandit(repo_path):
    """Run Bandit for Python security issues."""
    try:
        result = subprocess.run(
            ['bandit', '-r', repo_path, '-f', 'json', '-o', '-'],
            capture_output=True,
            text=True,
            timeout=300
        )
        
        if result.returncode in [0, 1]:  # Bandit returns 1 if issues found
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


def _map_eslint_severity(severity):
    return 'LOW' if severity == 1 else 'MEDIUM' if severity == 2 else 'HIGH'


def run_eslint_security(repo_path):
    """Run ESLint with security plugins."""
    try:
        # Ensure eslint-plugin-security is installed
        result = subprocess.run(
            ['npx', 'eslint', '--ext', '.js,.jsx,.ts,.tsx', 
             '--format', 'json', repo_path],
            capture_output=True,
            text=True,
            timeout=300
        )
        
        if result.returncode in [0, 1]:  # ESLint returns 1 if issues found
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

def _extract_file_path(lines: List[str], line_num: int) -> str:
    """Extract file path from diff lines given a 1-based line number."""
    file_path = "unknown"
    for i in range(line_num - 1, -1, -1):
        line = lines[i]
        if line.startswith("+++ b/"):
            file_path = line[6:].strip()
            break
        elif line.startswith("--- a/"):
            file_path = line[6:].strip()
            break
    return file_path

def _check_patch_for_secrets(
    lines: List[str],
    commit: str,
    author: str,
    date: str,
    repo_path: str,
    findings: List[Dict]
) -> None:
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

def scan_git_history_for_secrets(repo_path: str) -> List[Dict]:
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
                    _check_patch_for_secrets(patch_lines, current_commit, current_author, current_date, repo_path, findings)
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
            _check_patch_for_secrets(patch_lines, current_commit, current_author, current_date, repo_path, findings)
    except Exception as e:
        logger.error(f"Git history scan failed: {e}")
    return findings

def scan_repo(repo_path: str) -> Dict:
    """
    Main repo scan flow.
    Runs after checkout/clone, aggregates all findings.
    """
    results = {
        'repo_path': repo_path,
        'license_findings': [],
        'static_analysis_findings': [],
        'git_secret_findings': []
    }
    
    # Run license compliance check
    results['license_findings'] = check_license_compliance(repo_path)
    
    # Detect languages and run appropriate SAST tools
    languages = _detect_languages(repo_path)
    
    if languages['python']:
        results['static_analysis_findings'].extend(run_bandit(repo_path))
    
    if languages['javascript']:
        results['static_analysis_findings'].extend(run_eslint_security(repo_path))
    
    if languages['go']:
        results['static_analysis_findings'].extend(run_gosec(repo_path))
    
    # Run git history secret scan
    results['git_secret_findings'] = scan_git_history_for_secrets(repo_path)
    
    return results
