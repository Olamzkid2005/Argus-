"""
Parser Layer - Converts CLI tool output to JSON

Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 20.5, 21.1, 21.2
"""
import json
from typing import List, Dict, Generator
from abc import ABC, abstractmethod
import time
import os

from tracing import StructuredLogger, ExecutionSpan


class ParserError(Exception):
    """Raised when parsing fails"""
    pass


class BaseParser(ABC):
    """Base class for tool output parsers"""

    @abstractmethod
    def parse(self, raw_output: str) -> List[Dict]:
        """
        Parse tool output into structured findings

        Args:
            raw_output: Raw tool output string

        Returns:
            List of finding dictionaries
        """
        pass

    def parse_stream(self, raw_output: str) -> Generator[Dict, None, None]:
        """
        Parse tool output as a generator, yielding one finding at a time.

        This avoids loading all findings into memory at once,
        which is useful for large tool outputs.

        Args:
            raw_output: Raw tool output string

        Yields:
            Finding dictionaries one at a time
        """
        # Default implementation delegates to parse()
        # Subclasses can override for true streaming
        for finding in self.parse(raw_output):
            yield finding


class NucleiParser(BaseParser):
    """Parser for nuclei JSON output"""
    
    def parse(self, raw_output: str) -> List[Dict]:
        """
        Parse nuclei JSON lines output
        
        Args:
            raw_output: Nuclei output (JSON lines format)
            
        Returns:
            List of findings
        """
        findings = []
        
        for line in raw_output.split("\n"):
            if not line.strip():
                continue
            
            try:
                data = json.loads(line)
                
                # Extract finding information
                finding = {
                    "type": data.get("info", {}).get("name", "UNKNOWN"),
                    "severity": data.get("info", {}).get("severity", "INFO").upper(),
                    "endpoint": data.get("matched-at", ""),
                    "evidence": {
                        "template_id": data.get("template-id"),
                        "matcher_name": data.get("matcher-name"),
                        "extracted_results": data.get("extracted-results", []),
                        "curl_command": data.get("curl-command"),
                    },
                    "confidence": 0.8,  # Default confidence for nuclei
                    "tool": "nuclei",
                }
                
                findings.append(finding)
                
            except json.JSONDecodeError:
                # Skip lines that aren't valid JSON
                continue
            except Exception as e:
                # Log error but continue processing
                print(f"Error parsing nuclei line: {e}")
                continue
        
        return findings


class HttpxParser(BaseParser):
    """Parser for httpx output"""
    
    def parse(self, raw_output: str) -> List[Dict]:
        """
        Parse httpx output
        
        Args:
            raw_output: Httpx output (URL list or JSON)
            
        Returns:
            List of findings (endpoints)
        """
        findings = []
        
        for line in raw_output.split("\n"):
            if not line.strip():
                continue
            
            try:
                # Try parsing as JSON first
                data = json.loads(line)
                
                finding = {
                    "type": "HTTP_ENDPOINT",
                    "severity": "INFO",
                    "endpoint": data.get("url", ""),
                    "evidence": {
                        "status_code": data.get("status_code"),
                        "content_length": data.get("content_length"),
                        "content_type": data.get("content_type"),
                        "title": data.get("title"),
                    },
                    "confidence": 1.0,  # High confidence for discovered endpoints
                    "tool": "httpx",
                }
                
                findings.append(finding)
                
            except json.JSONDecodeError:
                # Not JSON, treat as plain URL
                if line.startswith("http://") or line.startswith("https://"):
                    finding = {
                        "type": "HTTP_ENDPOINT",
                        "severity": "INFO",
                        "endpoint": line.strip(),
                        "evidence": {},
                        "confidence": 1.0,
                        "tool": "httpx",
                    }
                    findings.append(finding)
        
        return findings


class SqlmapParser(BaseParser):
    """Parser for sqlmap output"""
    
    def parse(self, raw_output: str) -> List[Dict]:
        """
        Parse sqlmap output
        
        Args:
            raw_output: Sqlmap output
            
        Returns:
            List of SQL injection findings
        """
        findings = []
        
        # Look for SQL injection indicators in output
        if "sqlmap identified the following injection point" in raw_output.lower():
            finding = {
                "type": "SQL_INJECTION",
                "severity": "CRITICAL",
                "endpoint": "",  # Will be filled by normalizer
                "evidence": {
                    "raw_output": raw_output[:1000],  # First 1000 chars
                },
                "confidence": 0.9,  # High confidence for sqlmap
                "tool": "sqlmap",
            }
            findings.append(finding)
        
        return findings


class FfufParser(BaseParser):
    """Parser for ffuf output"""
    
    def parse(self, raw_output: str) -> List[Dict]:
        """
        Parse ffuf JSON output
        
        Args:
            raw_output: Ffuf output (JSON format)
            
        Returns:
            List of findings
        """
        findings = []
        
        try:
            data = json.loads(raw_output)
            
            for result in data.get("results", []):
                finding = {
                    "type": "DIRECTORY_FOUND",
                    "severity": "INFO",
                    "endpoint": result.get("url", ""),
                    "evidence": {
                        "status_code": result.get("status"),
                        "length": result.get("length"),
                        "words": result.get("words"),
                        "lines": result.get("lines"),
                    },
                    "confidence": 0.7,
                    "tool": "ffuf",
                }
                findings.append(finding)
                
        except json.JSONDecodeError:
            # Ffuf output not in JSON format
            pass
        
        return findings


class KatanaParser(BaseParser):
    """Parser for katana output (web crawler)"""
    
    def parse(self, raw_output: str) -> List[Dict]:
        """
        Parse katana JSON lines output
        
        Args:
            raw_output: Katana output (JSON lines format)
            
        Returns:
            List of findings
        """
        findings = []
        
        for line in raw_output.split("\n"):
            if not line.strip():
                continue
            
            try:
                data = json.loads(line)
                request = data.get("request", {})
                
                finding = {
                    "type": "CRAWLED_ENDPOINT",
                    "severity": "INFO",
                    "endpoint": request.get("url", request.get("endpoint", "")),
                    "evidence": {
                        "method": request.get("method", "GET"),
                        "body": request.get("body"),
                        "header": request.get("header"),
                    },
                    "confidence": 0.85,
                    "tool": "katana",
                }
                findings.append(finding)
                
            except json.JSONDecodeError:
                # Try plain URL fallback
                if line.strip().startswith("http"):
                    findings.append({
                        "type": "CRAWLED_ENDPOINT",
                        "severity": "INFO",
                        "endpoint": line.strip(),
                        "evidence": {},
                        "confidence": 0.85,
                        "tool": "katana",
                    })
                continue
        
        return findings


class GauParser(BaseParser):
    """Parser for gau output (GetAllUrls)"""
    
    def parse(self, raw_output: str) -> List[Dict]:
        """
        Parse gau plain URL output
        
        Args:
            raw_output: Gau output (plain URLs)
            
        Returns:
            List of findings
        """
        findings = []
        
        for line in raw_output.split("\n"):
            if not line.strip():
                continue
            
            url = line.strip()
            if url.startswith("http://") or url.startswith("https://"):
                finding = {
                    "type": "KNOWN_URL",
                    "severity": "INFO",
                    "endpoint": url,
                    "evidence": {
                        "source": "gau",
                    },
                    "confidence": 0.75,
                    "tool": "gau",
                }
                findings.append(finding)
        
        return findings


class WaybackurlsParser(BaseParser):
    """Parser for waybackurls output"""
    
    def parse(self, raw_output: str) -> List[Dict]:
        """
        Parse waybackurls plain URL output
        
        Args:
            raw_output: Waybackurls output (plain URLs)
            
        Returns:
            List of findings
        """
        findings = []
        
        for line in raw_output.split("\n"):
            if not line.strip():
                continue
            
            url = line.strip()
            if url.startswith("http://") or url.startswith("https://"):
                finding = {
                    "type": "HISTORICAL_URL",
                    "severity": "INFO",
                    "endpoint": url,
                    "evidence": {
                        "source": "wayback",
                    },
                    "confidence": 0.70,
                    "tool": "waybackurls",
                }
                findings.append(finding)
        
        return findings


class ArjunParser(BaseParser):
    """Parser for arjun output (parameter discovery)"""
    
    def parse(self, raw_output: str) -> List[Dict]:
        """
        Parse arjun JSON output
        
        Args:
            raw_output: Arjun output
            
        Returns:
            List of findings
        """
        findings = []
        
        try:
            data = json.loads(raw_output)
            
            if isinstance(data, list):
                items = data
            elif isinstance(data, dict):
                items = data.get("params", [data])
            else:
                return findings
            
            for item in items:
                param_name = item.get("name", item.get("param", ""))
                url = item.get("url", item.get("endpoint", ""))
                
                # Check for auth-related parameters
                severity = "MEDIUM"
                if any(kw in param_name.lower() for kw in ["token", "auth", "key", "secret", "password"]):
                    severity = "HIGH"
                
                finding = {
                    "type": "PARAMETER_DISCOVERY",
                    "severity": severity,
                    "endpoint": url,
                    "evidence": {
                        "parameter": param_name,
                        "method": item.get("method", "GET"),
                        "type": item.get("type", "param"),
                    },
                    "confidence": 0.85,
                    "tool": "arjun",
                }
                findings.append(finding)
                
        except json.JSONDecodeError:
            pass
        
        return findings


class DalfoxParser(BaseParser):
    """Parser for dalfox output (XSS scanner)"""
    
    def parse(self, raw_output: str) -> List[Dict]:
        """
        Parse dalfox JSON lines output
        
        Args:
            raw_output: Dalfox output (JSON lines format)
            
        Returns:
            List of findings
        """
        findings = []
        
        for line in raw_output.split("\n"):
            if not line.strip():
                continue
            
            try:
                data = json.loads(line)
                
                # Determine severity based on dalfox's analysis
                severity = "HIGH"
                if data.get("state") == "confirmed" or data.get("type") == "stored":
                    severity = "HIGH"
                
                finding = {
                    "type": "XSS",
                    "severity": severity,
                    "endpoint": data.get("url", data.get("endpoint", "")),
                    "evidence": {
                        "parameter": data.get("param", ""),
                        "payload": data.get("payload", ""),
                        "state": data.get("state", "unknown"),
                        "poc": data.get("poc", ""),
                    },
                    "confidence": 0.90,
                    "tool": "dalfox",
                }
                findings.append(finding)
                
            except json.JSONDecodeError:
                continue
        
        return findings


class JwtToolParser(BaseParser):
    """Parser for jwt_tool output"""
    
    def parse(self, raw_output: str) -> List[Dict]:
        """
        Parse jwt_tool JSON output
        
        Args:
            raw_output: jwt_tool output
            
        Returns:
            List of findings
        """
        findings = []
        
        try:
            data = json.loads(raw_output)
            
            vulnerabilities = data.get("vulnerabilities", [])
            token = data.get("token", {})
            
            for vuln in vulnerabilities:
                vuln_type = vuln.get("type", "unknown")
                
                # Map jwt_tool vulnerability types to standard types
                if "none" in vuln_type.lower():
                    finding_type = "JWT_VULNERABILITY"
                    severity = "HIGH"
                    confidence = 0.95
                elif "weak" in vuln_type.lower():
                    finding_type = "JWT_VULNERABILITY"
                    severity = "MEDIUM"
                    confidence = 0.85
                else:
                    finding_type = "JWT_VULNERABILITY"
                    severity = "MEDIUM"
                    confidence = 0.80
                
                finding = {
                    "type": finding_type,
                    "severity": severity,
                    "endpoint": token.get("url", ""),
                    "evidence": {
                        "algorithm": token.get("alg", ""),
                        "vulnerability": vuln_type,
                        "claims": token.get("payload", {}),
                    },
                    "confidence": confidence,
                    "tool": "jwt_tool",
                }
                findings.append(finding)
                
        except json.JSONDecodeError:
            pass
        
        return findings


class CommixParser(BaseParser):
    """Parser for commix output (command injection)"""
    
    def parse(self, raw_output: str) -> List[Dict]:
        """
        Parse commix plain text output
        
        Args:
            raw_output: Commix output
            
        Returns:
            List of findings
        """
        findings = []
        
        # Look for command injection indicators
        injection_indicators = [
            "command injection",
            "shellshock",
            "suspicious",
            "shell",
            "#!",
        ]
        
        raw_lower = raw_output.lower()
        
        # Check if any injection was found
        if any(indicator in raw_lower for indicator in injection_indicators):
            # Extract the most likely injection point
            endpoint = ""
            for line in raw_output.split("\n"):
                if "http" in line and ("://" in line or "parameter" in line.lower()):
                    endpoint = line.strip()
                    break
            
            finding = {
                "type": "COMMAND_INJECTION",
                "severity": "HIGH",  # Will be CRITICAL if verified
                "endpoint": endpoint,
                "evidence": {
                    "raw_output": raw_output[:1000],
                },
                "confidence": 0.95,
                "tool": "commix",
            }
            findings.append(finding)
        
        return findings


class SemgrepParser(BaseParser):
    """Parser for Semgrep output (static code analysis)"""
    
    def parse(self, raw_output: str) -> List[Dict]:
        """
        Parse Semgrep JSON output
        
        Args:
            raw_output: Semgrep output (JSON)
            
        Returns:
            List of code vulnerability findings
        """
        findings = []
        
        try:
            data = json.loads(raw_output)
            
            # Semgrep outputs results in "results" array
            results = data.get("results", [])
            
            for result in results:
                extra = result.get("extra", {})
                metadata = extra.get("metadata", {})
                
                # Map severity
                severity = "MEDIUM"
                severity_str = extra.get("severity", "").lower()
                if severity_str == "error":
                    severity = "CRITICAL"
                elif severity_str == "warning":
                    severity = "HIGH"
                
                # Get file and line info
                path = result.get("path", "")
                start_line = result.get("start", {}).get("line", 0)
                
                finding = {
                    "type": "CODE_VULNERABILITY",
                    "severity": severity,
                    "endpoint": f"file:{path}:{start_line}",
                    "evidence": {
                        "file": path,
                        "line": start_line,
                        "content": result.get("extra", {}).get("lines", ""),
                        "check_id": result.get("check_id", ""),
                        "cwe": metadata.get("cwe", ""),
                        "owasp": metadata.get("owasp", ""),
                    },
                    "confidence": 0.90,
                    "tool": "semgrep",
                }
                findings.append(finding)
                
        except json.JSONDecodeError:
            pass
        
        return findings


class NiktoParser(BaseParser):
    """Parser for Nikto output (web server scanner)"""
    
    def parse(self, raw_output: str) -> List[Dict]:
        """
        Parse Nikto output (CSV or text format)
        
        Args:
            raw_output: Nikto output
            
        Returns:
            List of findings
        """
        findings = []
        
        for line in raw_output.split("\n"):
            if not line.strip() or not line.startswith("+"):
                continue
            
            # Parse Nikto output lines like:
            # + /admin - OSVDB-3263 (Apache/Perl MIME types / XSS)
            if " - " in line:
                parts = line.split(" - ", 1)
                endpoint = parts[0].replace("+", "").strip()
                description = parts[1] if len(parts) > 1 else ""
                
                # Determine severity
                severity = "MEDIUM"
                if any(x in description.lower() for x in ["xss", "sql", "injection"]):
                    severity = "HIGH"
                elif any(x in description.lower() for x in ["default", "credential", "password"]):
                    severity = "CRITICAL"
                
                finding = {
                    "type": "WEB_VULNERABILITY",
                    "severity": severity,
                    "endpoint": endpoint,
                    "evidence": {
                        "description": description[:200],
                        "raw": line[:300],
                    },
                    "confidence": 0.75,
                    "tool": "nikto",
                }
                findings.append(finding)
        
        return findings


class WhatWebParser(BaseParser):
    """Parser for WhatWeb output (web technology fingerprinting)"""
    
    def parse(self, raw_output: str) -> List[Dict]:
        """
        Parse WhatWeb JSON output
        
        Args:
            raw_output: WhatWeb output (JSON format)
            
        Returns:
            List of technology findings
        """
        findings = []
        
        for line in raw_output.split("\n"):
            if not line.strip():
                continue
            
            try:
                # Try JSON format
                data = json.loads(line)
                target = data.get("target", "")
                plugins = data.get("plugins", {})
                
                # Extract technologies
                technologies = list(plugins.keys())
                
                if technologies:
                    # Determine if any are sensitive
                    sensitive = ["wordpress", "drupal", "joomla", "apache", "nginx", "php"]
                    severity = "INFO"
                    if any(t.lower() in [s.lower() for s in sensitive] for t in technologies):
                        severity = "LOW"
                    
                    finding = {
                        "type": "TECHNOLOGY_FINGERPRINT",
                        "severity": severity,
                        "endpoint": target,
                        "evidence": {
                            "technologies": technologies,
                            "plugins": plugins,
                        },
                        "confidence": 0.95,
                        "tool": "whatweb",
                    }
                    findings.append(finding)
                    
            except json.JSONDecodeError:
                # Try plain text format: 127.0.0.1 [200] [Apache] [PHP/5.3.3]
                if "[" in line:
                    parts = line.split("[")
                    if len(parts) >= 3:
                        endpoint = parts[0].strip()
                        technologies = [p.replace("]", "").strip() for p in parts[2:]]
                        
                        finding = {
                            "type": "TECHNOLOGY_FINGERPRINT",
                            "severity": "INFO",
                            "endpoint": endpoint,
                            "evidence": {"technologies": technologies},
                            "confidence": 0.90,
                            "tool": "whatweb",
                        }
                        findings.append(finding)
        
        return findings


class AmassParser(BaseParser):
    """Parser for Amass output (subdomain enumeration)"""
    
    def parse(self, raw_output: str) -> List[Dict]:
        """
        Parse Amass JSON/Lines output
        
        Args:
            raw_output: Amass output (JSON lines or text)
            
        Returns:
            List of subdomain findings
        """
        findings = []
        
        for line in raw_output.split("\n"):
            if not line.strip():
                continue
            
            try:
                # Try JSON format first
                data = json.loads(line)
                
                if data.get("name"):  # subdomain
                    finding = {
                        "type": "SUBDOMAIN_DISCOVERY",
                        "severity": "INFO",
                        "endpoint": data.get("name", ""),
                        "evidence": {
                            "sources": data.get("sources", []),
                            "domain": data.get("domain", ""),
                        },
                        "confidence": 0.90,
                        "tool": "amass",
                    }
                    findings.append(finding)
                    
            except json.JSONDecodeError:
                # Try plain subdomain format
                if line.startswith("http") or "*." in line or not " " in line:
                    endpoint = line.strip()
                    if endpoint and ("." in endpoint or "*." in endpoint):
                        finding = {
                            "type": "SUBDOMAIN_DISCOVERY",
                            "severity": "INFO",
                            "endpoint": endpoint,
                            "evidence": {"source": "amass"},
                            "confidence": 0.85,
                            "tool": "amass",
                        }
                        findings.append(finding)
        
        return findings


class NaabuParser(BaseParser):
    """Parser for Naabu output (port scanning)"""
    
    def parse(self, raw_output: str) -> List[Dict]:
        """
        Parse Naabu output (JSON or text)
        
        Args:
            raw_output: Naabu output
            
        Returns:
            List of port findings
        """
        findings = []
        
        for line in raw_output.split("\n"):
            if not line.strip():
                continue
            
            try:
                # Try JSON format
                data = json.loads(line)
                host = data.get("host", "")
                port = data.get("port", "")
                
                finding = {
                    "type": "OPEN_PORT",
                    "severity": "INFO",
                    "endpoint": f"{host}:{port}",
                    "evidence": {
                        "port": port,
                        "service": data.get("service", ""),
                        "banner": data.get("banner", "")[:100],
                    },
                    "confidence": 0.95,
                    "tool": "naabu",
                }
                findings.append(finding)
                
            except json.JSONDecodeError:
                # Try text format: host:port
                if ":" in line:
                    parts = line.strip().split(":")
                    if len(parts) == 2:
                        finding = {
                            "type": "OPEN_PORT",
                            "severity": "INFO",
                            "endpoint": line.strip(),
                            "evidence": {"port": parts[1]},
                            "confidence": 0.90,
                            "tool": "naabu",
                        }
                        findings.append(finding)
        
        return findings


class GitleaksParser(BaseParser):
    """Parser for gitleaks output (secret detection in git history)"""
    
    def parse(self, raw_output: str) -> List[Dict]:
        """
        Parse gitleaks JSON output
        
        Args:
            raw_output: Gitleaks output (JSON array)
            
        Returns:
            List of secret leak findings
        """
        findings = []
        
        try:
            data = json.loads(raw_output)
            
            if not isinstance(data, list):
                data = [data] if isinstance(data, dict) else []
            
            for leak in data:
                finding = {
                    "type": "SECRET_LEAK",
                    "severity": "CRITICAL",
                    "endpoint": leak.get("File", leak.get("file", "")),
                    "evidence": {
                        "file": leak.get("File", leak.get("file", "")),
                        "line": leak.get("StartLine", leak.get("startLine", leak.get("line", 0))),
                        "secret_type": leak.get("RuleID", leak.get("ruleId", leak.get("Description", "unknown"))),
                        "commit": leak.get("Commit", leak.get("commit", "")),
                        "author": leak.get("Author", leak.get("author", "")),
                        "date": leak.get("Date", leak.get("date", "")),
                        "match": leak.get("Match", leak.get("match", "")),
                    },
                    "confidence": 0.95,
                    "tool": "gitleaks",
                }
                findings.append(finding)
                
        except json.JSONDecodeError:
            pass
        
        return findings


class TrivyParser(BaseParser):
    """Parser for trivy output (dependency vulnerability scanning)"""
    
    def parse(self, raw_output: str) -> List[Dict]:
        """
        Parse trivy JSON output
        
        Args:
            raw_output: Trivy output (JSON format with Results array)
            
        Returns:
            List of dependency vulnerability findings
        """
        findings = []
        
        try:
            data = json.loads(raw_output)
            
            results = data.get("Results", [])
            if isinstance(data, list):
                results = data
            
            for result in results:
                target = result.get("Target", "")
                vulns = result.get("Vulnerabilities", [])
                
                for vuln in vulns:
                    severity = vuln.get("Severity", "UNKNOWN").upper()
                    if severity == "UNKNOWN":
                        severity = "INFO"
                    
                    cve_id = vuln.get("VulnerabilityID", "")
                    pkg_name = vuln.get("PkgName", "")
                    installed = vuln.get("InstalledVersion", "")
                    fixed = vuln.get("FixedVersion", "")
                    
                    finding = {
                        "type": "DEPENDENCY_VULNERABILITY",
                        "severity": severity,
                        "endpoint": target,
                        "evidence": {
                            "cve_id": cve_id,
                            "package": pkg_name,
                            "installed_version": installed,
                            "fixed_version": fixed,
                            "title": vuln.get("Title", ""),
                            "description": vuln.get("Description", "")[:500],
                            "references": vuln.get("References", [])[:5],
                            "cvss": vuln.get("CVSS", {}),
                        },
                        "confidence": 0.90,
                        "tool": "trivy",
                    }
                    findings.append(finding)
                    
        except json.JSONDecodeError:
            pass
        
        return findings


class TestSSLParser(BaseParser):
    """Parser for testssl output (TLS scanning)"""
    
    def parse(self, raw_output: str) -> List[Dict]:
        """
        Parse testssl JSON output
        
        Args:
            raw_output: testssl output (JSON format)
            
        Returns:
            List of TLS vulnerability findings
        """
        findings = []
        
        try:
            data = json.loads(raw_output)
            
            # Process each finding
            for check in data.get("results", []):
                id_info = check.get("id", {})
                vuln = check.get("vulnerability", "")
                
                if not vuln:
                    continue
                
                # Map severity
                severity = "LOW"
                rating = check.get("severity", "").upper()
                if rating == "CRITICAL" or rating == "HIGH":
                    severity = rating
                elif rating == "MEDIUM":
                    severity = "MEDIUM"
                
                finding = {
                    "type": "TLS_VULNERABILITY",
                    "severity": severity,
                    "endpoint": data.get("host", ""),
                    "evidence": {
                        "check": id_info.get("header", ""),
                        "vulnerability": vuln,
                        "rating": rating,
                    },
                    "confidence": 0.90,
                    "tool": "testssl",
                }
                findings.append(finding)
                
        except json.JSONDecodeError:
            # Try plain text format
            for line in raw_output.split("\n"):
                if "Rating" in line or "VULNERABLE" in line.upper():
                    severity = "HIGH"
                    if "MEDIUM" in line.upper():
                        severity = "MEDIUM"
                    elif "LOW" in line.upper():
                        severity = "LOW"
                    
                    if severity != "INFO":  # Skip info lines
                        finding = {
                            "type": "TLS_VULNERABILITY",
                            "severity": severity,
                            "endpoint": "TLS",
                            "evidence": {"raw": line[:200]},
                            "confidence": 0.80,
                            "tool": "testssl",
                        }
                        findings.append(finding)
        
        return findings


class GospiderParser(BaseParser):
    """Parser for Gospider output (JavaScript file discovery)"""
    
    def parse(self, raw_output: str) -> List[Dict]:
        """
        Parse Gospider JSON or text output
        
        Args:
            raw_output: Gospider output
            
        Returns:
            List of endpoint findings
        """
        findings = []
        
        for line in raw_output.split("\n"):
            if not line.strip():
                continue
            
            try:
                data = json.loads(line)
                output = data.get("output", "")
                
                if output and output.startswith("http"):
                    finding = {
                        "type": "DISCOVERED_ENDPOINT",
                        "severity": "INFO",
                        "endpoint": output,
                        "evidence": {
                            "source": data.get("source", ""),
                            "type": data.get("type", ""),
                        },
                        "confidence": 0.90,
                        "tool": "gospider",
                    }
                    findings.append(finding)
            except json.JSONDecodeError:
                if line.startswith("http"):
                    finding = {
                        "type": "DISCOVERED_ENDPOINT",
                        "severity": "INFO",
                        "endpoint": line.strip(),
                        "evidence": {},
                        "confidence": 0.85,
                        "tool": "gospider",
                    }
                    findings.append(finding)
        
        return findings


class WpscanParser(BaseParser):
    """Parser for WPScan output (WordPress security scanning)"""
    
    def parse(self, raw_output: str) -> List[Dict]:
        """
        Parse WPScan JSON output
        
        Args:
            raw_output: WPScan JSON output
            
        Returns:
            List of WordPress vulnerability findings
        """
        findings = []
        
        try:
            data = json.loads(raw_output)
            
            # Parse interesting findings
            interesting = data.get("interesting_findings", [])
            for finding_data in interesting:
                severity = "MEDIUM"
                finding_type = finding_data.get("type", "unknown")
                if finding_type in ["db_backup", "backups"]:
                    severity = "HIGH"
                elif finding_type in ["log_file"]:
                    severity = "MEDIUM"
                
                finding = {
                    "type": f"WP_{finding_type.upper()}",
                    "severity": severity,
                    "endpoint": finding_data.get("url", ""),
                    "evidence": {
                        "description": finding_data.get("to_s", ""),
                        "found_by": finding_data.get("found_by", ""),
                    },
                    "confidence": 0.90,
                    "tool": "wpscan",
                }
                findings.append(finding)
            
            # Parse vulnerabilities
            vulns = data.get("vulnerabilities", {})
            for vuln_type, vuln_list in vulns.items():
                for vuln in vuln_list:
                    severity = vuln.get("cvss", {}).get("score", 5.0)
                    severity_str = "MEDIUM"
                    if severity >= 7.0:
                        severity_str = "HIGH"
                    elif severity >= 9.0:
                        severity_str = "CRITICAL"
                    elif severity < 4.0:
                        severity_str = "LOW"
                    
                    finding = {
                        "type": f"WP_VULNERABILITY_{vuln_type.upper()}",
                        "severity": severity_str,
                        "endpoint": data.get("target_url", ""),
                        "evidence": {
                            "title": vuln.get("title", ""),
                            "references": vuln.get("references", {}),
                            "fixed_in": vuln.get("fixed_in", ""),
                        },
                        "confidence": 0.85,
                        "tool": "wpscan",
                    }
                    findings.append(finding)
            
            # Parse version vulnerabilities
            version = data.get("version", {})
            version_vulns = version.get("vulnerabilities", [])
            for vuln in version_vulns:
                finding = {
                    "type": "WP_CORE_VULNERABILITY",
                    "severity": "HIGH",
                    "endpoint": data.get("target_url", ""),
                    "evidence": {
                        "title": vuln.get("title", ""),
                        "fixed_in": vuln.get("fixed_in", ""),
                    },
                    "confidence": 0.85,
                    "tool": "wpscan",
                }
                findings.append(finding)
                
        except json.JSONDecodeError:
            pass
        
        return findings


class Parser:
    """
    Main parser class that routes to appropriate tool parser
    """
    
    def __init__(self, connection_string: str = None):
        """
        Initialize Parser with optional database connection for tracing.
        
        Args:
            connection_string: Database connection string
        """
        self.parsers = {
            "nuclei": NucleiParser(),
            "httpx": HttpxParser(),
            "sqlmap": SqlmapParser(),
            "ffuf": FfufParser(),
            "katana": KatanaParser(),
            "gau": GauParser(),
            "waybackurls": WaybackurlsParser(),
            "arjun": ArjunParser(),
            "dalfox": DalfoxParser(),
            "jwt_tool": JwtToolParser(),
            "commix": CommixParser(),
            "semgrep": SemgrepParser(),
            "nikto": NiktoParser(),
            "whatweb": WhatWebParser(),
            "amass": AmassParser(),
            "naabu": NaabuParser(),
            "testssl": TestSSLParser(),
            "gitleaks": GitleaksParser(),
            "trivy": TrivyParser(),
            "gospider": GospiderParser(),
            "wpscan": WpscanParser(),
        }
        
        # Initialize tracing
        self.connection_string = connection_string or os.getenv("DATABASE_URL")
        self.logger = StructuredLogger(self.connection_string)
        self.span_recorder = ExecutionSpan(self.connection_string)
    
    def parse(self, tool_name: str, raw_output: str) -> List[Dict]:
        """
        Route to appropriate parser based on tool name

        Args:
            tool_name: Name of the tool
            raw_output: Raw tool output

        Returns:
            List of parsed findings

        Raises:
            ParserError: If no parser exists for tool
        """
        parser = self.parsers.get(tool_name.lower())

        if not parser:
            raise ParserError(f"No parser found for tool: {tool_name}")

        # Record start time
        start_time = time.time()

        # Execute with span tracing
        with self.span_recorder.span(ExecutionSpan.SPAN_PARSING, {"tool": tool_name}):
            try:
                findings = parser.parse(raw_output)

                # Calculate duration
                duration_ms = int((time.time() - start_time) * 1000)

                # Log parser completion
                self.logger.log_parser_completed(
                    tool_name=tool_name,
                    findings_count=len(findings),
                    parse_time_ms=duration_ms
                )

                return findings

            except Exception as e:
                # Calculate duration
                duration_ms = int((time.time() - start_time) * 1000)

                # Log parser failure
                self.logger.log(
                    "parser_failed",
                    f"Parser failed for {tool_name}: {str(e)}",
                    {
                        "tool_name": tool_name,
                        "error": str(e),
                        "parse_time_ms": duration_ms,
                    }
                )

                raise ParserError(f"Failed to parse {tool_name} output: {e}")

    def parse_stream(self, tool_name: str, raw_output: str, batch_size: int = 50) -> Generator[List[Dict], None, None]:
        """
        Parse tool output as a stream, yielding findings in batches.

        This avoids loading all findings into memory at once,
        which is useful for large tool outputs. Yields batches
        of findings that can be inserted into the database.

        Args:
            tool_name: Name of the tool
            raw_output: Raw tool output
            batch_size: Number of findings per batch (default: 50)

        Yields:
            Batches of parsed findings (List[Dict])

        Raises:
            ParserError: If no parser exists for tool

        Example:
            for batch in runner.parse_stream("nuclei", output, batch_size=50):
                db.insert_findings(batch)  # Insert 50 at a time
        """
        parser = self.parsers.get(tool_name.lower())

        if not parser:
            raise ParserError(f"No parser found for tool: {tool_name}")

        # Record start time
        start_time = time.time()
        total_count = 0
        batch = []

        # Execute with span tracing
        with self.span_recorder.span(ExecutionSpan.SPAN_PARSING, {"tool": tool_name, "stream": True}):
            try:
                for finding in parser.parse_stream(raw_output):
                    batch.append(finding)
                    total_count += 1

                    if len(batch) >= batch_size:
                        yield batch
                        batch = []

                # Yield remaining findings
                if batch:
                    yield batch

                # Calculate duration
                duration_ms = int((time.time() - start_time) * 1000)

                # Log parser completion
                self.logger.log_parser_completed(
                    tool_name=tool_name,
                    findings_count=total_count,
                    parse_time_ms=duration_ms
                )

            except Exception as e:
                # Calculate duration
                duration_ms = int((time.time() - start_time) * 1000)

                # Log parser failure
                self.logger.log(
                    "parser_failed",
                    f"Stream parser failed for {tool_name}: {str(e)}",
                    {
                        "tool_name": tool_name,
                        "error": str(e),
                        "parse_time_ms": duration_ms,
                    }
                )

                raise ParserError(f"Failed to stream parse {tool_name} output: {e}")
