"""Tool registrations mirrored from ``tools/definitions/*.yaml``.

Kept by hand: there is no generator behind this file (earlier headers named
``scripts/generate_tool_defs.py``, which does not exist). When a YAML definition
changes, update the matching block here.

Delegated tools — the ones whose args run ``tools/scripts/delegate_shim.py`` —
are the exception. They are registered from their YAML at the bottom of this
file, because a hand-maintained second copy of that metadata is what drifted
before (a stale ``target_kind`` and a lost indentation level).
"""

from tool_definitions import ToolDefinition, ToolParameter, ToolRequires, SignalQuality, _register


# ── alterx (from alterx.yaml) ──
_register(ToolDefinition(
    name="alterx",
    description="Subdomain permutation generator for expanding recon surface",
    phases=["recon"],
    default_args=["-silent"],
    parameters=[
    ToolParameter(name="target", description="Root domain(s) to generate permutations for (comma-separated or file)", required=True, flag="-l"),
],
    timeout=120,
    signal_quality=SignalQuality.CANDIDATE,
    priority=30,
    cost="low",
    risk_level="low",
))

# ── amass (from amass.yaml) ──
_register(ToolDefinition(
    name="amass",
    description="Subdomain enumeration and reconnaissance tool",
    phases=["recon"],
    default_args=["enum"],
    parameters=[
    ToolParameter(name="target", description="Target domain", required=True, flag="-d"),
    ToolParameter(name="brute", description="Enable brute forcing", flag="-brute"),
],
    timeout=600,
    signal_quality=SignalQuality.CANDIDATE,
    priority=65,
    cost="high",
    risk_level="medium",
))

# ── arjun (from arjun.yaml) ──
_register(ToolDefinition(
    name="arjun",
    description="HTTP parameter discovery tool",
    phases=["scan"],
    default_args=["-m", "GET"],
    parameters=[
    ToolParameter(name="target", description="Target URL", required=True, flag="-u"),
    ToolParameter(name="threads", description="Thread count", flag="-t", default=10),
],
    timeout=300,
    signal_quality=SignalQuality.CANDIDATE,
    priority=50,
    cost="medium",
    risk_level="low",
))

# ── assessment_orchestrator (from assessment_orchestrator.yaml) ──
_register(ToolDefinition(
    name="assessment_orchestrator",
    description="assessment_orchestrator - security assessment tool",
    binary="python3",
    phases=["analyze"],
    default_args=["argus-workers/tools/run_agent_tool.py", "assessment_orchestrator"],
    parameters=[
    ToolParameter(name="target", description="Target URL or scope", required=True, flag="--target"),
    ToolParameter(name="extra", description="JSON-encoded extra parameters (e.g. {\"tech_stack\":[\"apache\"]})", flag="--extra"),
],
    timeout=300,
    signal_quality=SignalQuality.CONFIRMED,
    priority=90,
    cost="low",
    risk_level="low",
))

# ── attack_path_generator (from attack_path_generator.yaml) ──
_register(ToolDefinition(
    name="attack_path_generator",
    description="attack_path_generator - security assessment tool",
    binary="python3",
    phases=["analyze"],
    default_args=["argus-workers/tools/run_agent_tool.py", "attack_path_generator"],
    parameters=[
    ToolParameter(name="target", description="Target URL or scope", required=True, flag="--target"),
    ToolParameter(name="extra", description="JSON-encoded extra parameters (e.g. {\"tech_stack\":[\"apache\"]})", flag="--extra"),
],
    timeout=300,
    signal_quality=SignalQuality.CONFIRMED,
    priority=90,
    cost="low",
    risk_level="low",
))

# ── attack_surface_mapper (from attack_surface_mapper.yaml) ──
_register(ToolDefinition(
    name="attack_surface_mapper",
    description="attack_surface_mapper - security assessment tool",
    binary="python3",
    phases=["analyze", "recon"],
    default_args=["argus-workers/tools/run_agent_tool.py", "attack_surface_mapper"],
    parameters=[
    ToolParameter(name="target", description="Target URL or scope", required=True, flag="--target"),
    ToolParameter(name="extra", description="JSON-encoded extra parameters (e.g. {\"tech_stack\":[\"apache\"]})", flag="--extra"),
],
    timeout=300,
    signal_quality=SignalQuality.CONFIRMED,
    priority=90,
    cost="low",
    risk_level="low",
))



# ── browser_security_operator (from browser_security_operator.yaml) ──
_register(ToolDefinition(
    name="browser_security_operator",
    description="browser_security_operator - security assessment tool",
    binary="python3",
    phases=["analyze", "scan", "deep_scan"],
    default_args=["argus-workers/tools/run_agent_tool.py", "browser_security_operator"],
    parameters=[
    ToolParameter(name="target", description="Target URL or scope", required=True, flag="--target"),
    ToolParameter(name="extra", description="JSON-encoded extra parameters (e.g. {\"tech_stack\":[\"apache\"]})", flag="--extra"),
],
    timeout=300,
    signal_quality=SignalQuality.CONFIRMED,
    priority=90,
    cost="low",
    risk_level="low",
))

# ── bucket_upload (from bucket_upload.yaml) ──
_register(ToolDefinition(
    name="bucket_upload",
    description="Cloud storage bucket upload testing for permission misconfigurations",
    phases=["scan", "deep_scan"],
    parameters=[
    ToolParameter(name="target", description="Bucket URL or name", required=True),
],
    timeout=120,
    signal_quality=SignalQuality.PROBABLE,
    priority=50,
    cost="low",
    risk_level="medium",
))


# ── cloud_enum (from cloud_enum.yaml) ──
_register(ToolDefinition(
    name="cloud_enum",
    description="Cloud asset enumeration tool (AWS, Azure, GCP)",
    phases=["recon", "scan"],
    parameters=[
    ToolParameter(name="target", description="Target domain or keyword", required=True, flag="-k"),
],
    timeout=300,
    signal_quality=SignalQuality.CANDIDATE,
    priority=30,
    cost="low",
    risk_level="low",
))

# ── cloud_metadata_probe (from cloud_metadata_probe.yaml) ──
_register(ToolDefinition(
    name="cloud_metadata_probe",
    description="cloud_metadata_probe - security assessment tool",
    binary="python3",
    phases=["scan"],
    default_args=["argus-workers/tools/run_agent_tool.py", "cloud_metadata_probe"],
    parameters=[
    ToolParameter(name="target", description="Target URL or scope", required=True, flag="--target"),
    ToolParameter(name="extra", description="JSON-encoded extra parameters (e.g. {\"tech_stack\":[\"apache\"]})", flag="--extra"),
],
    timeout=60,
    signal_quality=SignalQuality.CONFIRMED,
    priority=95,
    cost="low",
    risk_level="high",
))

# ── commix (from commix.yaml) ──
_register(ToolDefinition(
    name="commix",
    description="Command injection detection tool",
    phases=["scan", "deep_scan"],
    default_args=["--batch"],
    parameters=[
    ToolParameter(name="target", description="Target URL", required=True, flag="--url"),
],
    timeout=300,
    signal_quality=SignalQuality.PROBABLE,
    requires=ToolRequires(recon_signals=["has_file_upload"]),
    priority=70,
    cost="medium",
    risk_level="high",
))

# ── dalfox (from dalfox.yaml) ──
_register(ToolDefinition(
    name="dalfox",
    description="XSS vulnerability scanner with DOM/param analysis",
    phases=["scan", "deep_scan"],
    default_args=["url", "--format", "jsonl", "--no-color", "--no-spinner"],
    parameters=[
    ToolParameter(name="target", description="Target URL", required=True),
    ToolParameter(name="blind", description="Blind XSS callback URL", flag="-b"),
    ToolParameter(name="deep_dom", description="Enable deep DOM XSS testing with more payloads (slow)", flag="--deep-domxss"),
],
    timeout=600,
    signal_quality=SignalQuality.PROBABLE,
    priority=75,
    cost="medium",
    risk_level="medium",
))


# ── dnsx (from dnsx.yaml) ──
_register(ToolDefinition(
    name="dnsx",
    description="Fast DNS resolver and probe tool",
    phases=["recon"],
    default_args=["-json", "-silent"],
    parameters=[
    ToolParameter(name="target", description="Domain or subdomain list", required=True, flag="-d"),
],
    timeout=120,
    signal_quality=SignalQuality.CANDIDATE,
    priority=40,
    cost="low",
    risk_level="low",
))

# ── engagement_analytics_engine (from engagement_analytics_engine.yaml) ──
_register(ToolDefinition(
    name="engagement_analytics_engine",
    description="engagement_analytics_engine - security assessment tool",
    binary="python3",
    phases=["analyze", "report"],
    default_args=["argus-workers/tools/run_agent_tool.py", "engagement_analytics_engine"],
    parameters=[
    ToolParameter(name="target", description="Target URL or scope", required=True, flag="--target"),
    ToolParameter(name="extra", description="JSON-encoded extra parameters (e.g. {\"tech_stack\":[\"apache\"]})", flag="--extra"),
],
    timeout=300,
    signal_quality=SignalQuality.CONFIRMED,
    priority=90,
    cost="low",
    risk_level="low",
))


# ── evidence_intelligence_engine (from evidence_intelligence_engine.yaml) ──
_register(ToolDefinition(
    name="evidence_intelligence_engine",
    description="evidence_intelligence_engine - security assessment tool",
    binary="python3",
    phases=["analyze"],
    default_args=["argus-workers/tools/run_agent_tool.py", "evidence_intelligence_engine"],
    parameters=[
    ToolParameter(name="target", description="Target URL or scope", required=True, flag="--target"),
    ToolParameter(name="extra", description="JSON-encoded extra parameters (e.g. {\"tech_stack\":[\"apache\"]})", flag="--extra"),
],
    timeout=300,
    signal_quality=SignalQuality.CONFIRMED,
    priority=90,
    cost="low",
    risk_level="low",
))

# ── executive_report_generator (from executive_report_generator.yaml) ──
_register(ToolDefinition(
    name="executive_report_generator",
    description="executive_report_generator - security assessment tool",
    binary="python3",
    phases=["analyze", "report"],
    default_args=["argus-workers/tools/run_agent_tool.py", "executive_report_generator"],
    parameters=[
    ToolParameter(name="target", description="Target URL or scope", required=True, flag="--target"),
    ToolParameter(name="extra", description="JSON-encoded extra parameters (e.g. {\"tech_stack\":[\"apache\"]})", flag="--extra"),
],
    timeout=300,
    signal_quality=SignalQuality.CONFIRMED,
    priority=90,
    cost="low",
    risk_level="low",
))

# ── ffuf (from ffuf.yaml) ──
_register(ToolDefinition(
    name="ffuf",
    description="Web fuzzing tool for directory and parameter discovery",
    phases=["recon", "scan"],
    default_args=["-json"],
    parameters=[
    ToolParameter(name="target", description="Target URL with FUZZ keyword", required=True, flag="-u"),
    ToolParameter(name="wordlist", description="Path to wordlist", required=True, flag="-w"),
    ToolParameter(name="threads", description="Thread count", flag="-t", default=40),
],
    timeout=300,
    signal_quality=SignalQuality.CANDIDATE,
    priority=70,
    cost="medium",
    risk_level="medium",
))

# ── finding_correlation_engine (from finding_correlation_engine.yaml) ──
_register(ToolDefinition(
    name="finding_correlation_engine",
    description="finding_correlation_engine - security assessment tool",
    binary="python3",
    phases=["analyze"],
    default_args=["argus-workers/tools/run_agent_tool.py", "finding_correlation_engine"],
    parameters=[
    ToolParameter(name="target", description="Target URL or scope", required=True, flag="--target"),
    ToolParameter(name="extra", description="JSON-encoded extra parameters (e.g. {\"tech_stack\":[\"apache\"]})", flag="--extra"),
],
    timeout=300,
    signal_quality=SignalQuality.CONFIRMED,
    priority=90,
    cost="low",
    risk_level="low",
))

# ── finding_verifier (from finding_verifier.yaml) ──
_register(ToolDefinition(
    name="finding_verifier",
    description="Verify findings by re-testing with independent HTTP-based methods — validates SQLi, XSS, and Open Redirect via httpx",
    binary="python3",
    phases=["scan"],
    default_args=["argus-workers/tools/scripts/run_finding_verifier.py"],
    parameters=[
    ToolParameter(name="target", description="Target URL to verify", required=True, flag="--target"),
    ToolParameter(name="finding_type", description="Type of finding to verify (sqli, xss, open_redirect)", required=True, flag="--finding-type"),
    ToolParameter(name="payload", description="Payload used in the original finding (for sqli and xss verification)", flag="--payload"),
    ToolParameter(name="endpoint", description="Specific endpoint URL where the finding was detected (defaults to target)", flag="--endpoint"),
    ToolParameter(name="engagement_id", description="Engagement ID for logging", flag="--engagement-id"),
],
    timeout=60,
    signal_quality=SignalQuality.CONFIRMED,
    priority=85,
    cost="low",
    risk_level="low",
))

# ── gau (from gau.yaml) ──
_register(ToolDefinition(
    name="gau",
    description="Get all URLs from web archives (Wayback, AlienVault, etc.)",
    phases=["recon"],
    default_args=["--json"],
    parameters=[
    ToolParameter(name="target", description="Target domain", required=True),
],
    timeout=180,
    signal_quality=SignalQuality.CANDIDATE,
    priority=40,
    cost="low",
    risk_level="low",
))


# ── gitleaks (from gitleaks.yaml) ──
_register(ToolDefinition(
    name="gitleaks",
    description="Git repository secret scanning for hardcoded credentials",
    phases=["repo_scan"],
    target_kind="path",
    default_args=["detect", "--no-git", "--no-color", "--report-format", "json", "--report-path", "-"],
    parameters=[
    ToolParameter(name="target", description="Filesystem path or repository directory to scan (not a URL)", required=True, flag="--source"),
    ToolParameter(name="max_target_mb", description="Max target size in MB", flag="--max-target-megabytes"),
],
    timeout=300,
    signal_quality=SignalQuality.CONFIRMED,
    priority=85,
    cost="medium",
    risk_level="low",
))


# ── gospider (from gospider.yaml) ──
_register(ToolDefinition(
    name="gospider",
    description="Web spider for endpoint and parameter discovery",
    phases=["recon", "scan"],
    default_args=["-q", "--json"],
    parameters=[
    ToolParameter(name="target", description="Target URL", required=True, flag="-s"),
    ToolParameter(name="depth", description="Crawl depth", flag="-d", default=3),
],
    timeout=300,
    signal_quality=SignalQuality.CANDIDATE,
    priority=55,
    cost="medium",
    risk_level="low",
))


# ── httpx (from httpx.yaml) ──
_register(ToolDefinition(
    name="httpx",
    description="HTTPX probe for HTTP server discovery and technology detection",
    phases=["recon"],
    default_args=["-json", "-silent"],
    parameters=[
    ToolParameter(name="target", description="Target URL or host to probe", required=True, flag="-u"),
],
    timeout=120,
    signal_quality=SignalQuality.CANDIDATE,
    priority=80,
    cost="low",
    risk_level="low",
))

# ── infrastructure_security_analyzer (from infrastructure_security_analyzer.yaml) ──
_register(ToolDefinition(
    name="infrastructure_security_analyzer",
    description="infrastructure_security_analyzer - security assessment tool",
    binary="python3",
    phases=["analyze"],
    default_args=["argus-workers/tools/run_agent_tool.py", "infrastructure_security_analyzer"],
    parameters=[
    ToolParameter(name="target", description="Target URL or scope", required=True, flag="--target"),
    ToolParameter(name="extra", description="JSON-encoded extra parameters (e.g. {\"tech_stack\":[\"apache\"]})", flag="--extra"),
],
    timeout=300,
    signal_quality=SignalQuality.CONFIRMED,
    priority=90,
    cost="low",
    risk_level="low",
))

# ── jwt_tool (from jwt_tool.yaml) ──
_register(ToolDefinition(
    name="jwt_tool",
    description="JWT security testing toolkit",
    phases=["scan"],
    default_args=["-C", "-d"],
    parameters=[
    ToolParameter(name="target", description="Target URL", required=True, flag="-t"),
],
    timeout=120,
    signal_quality=SignalQuality.PROBABLE,
    requires=ToolRequires(recon_signals=["has_api", "has_login_page"]),
    priority=70,
    cost="low",
    risk_level="medium",
))

# ── katana (from katana.yaml) ──
_register(ToolDefinition(
    name="katana",
    description="Web crawling and endpoint discovery tool",
    phases=["recon", "scan"],
    default_args=["-jsonl", "-silent"],
    parameters=[
    ToolParameter(name="target", description="Target URL", required=True, flag="-u"),
    ToolParameter(name="depth", description="Crawl depth", flag="-d", default=3),
],
    timeout=300,
    signal_quality=SignalQuality.CANDIDATE,
    priority=60,
    cost="medium",
    risk_level="low",
))

# ── login (from login.yaml) ──
_register(ToolDefinition(
    name="login",
    description="login - security assessment tool",
    binary="python3",
    phases=["scan"],
    default_args=["argus-workers/tools/run_agent_tool.py", "login"],
    parameters=[
    ToolParameter(name="target", description="Target URL or scope", required=True, flag="--target"),
    ToolParameter(name="extra", description="JSON-encoded extra parameters (e.g. {\"email\":\"test@example.com\",\"password\":\"test123\"})", flag="--extra"),
],
    timeout=120,
    signal_quality=SignalQuality.CONFIRMED,
    priority=95,
    cost="low",
    risk_level="low",
))

# ── masscan (from masscan.yaml) ──
_register(ToolDefinition(
    name="masscan",
    description="Massive-scale port scanner (entire internet in minutes)",
    phases=[],
    disabled_reason=(
        "requires root or CAP_NET_RAW for raw sockets, which the unprivileged "
        "worker does not have; naabu and nmap cover port scanning"
    ),
    default_args=["--rate", "1000", "--output-format", "json"],
    parameters=[
    ToolParameter(name="target", description="Target CIDR range or IP", required=True, flag="--range"),
    ToolParameter(name="ports", description="Port range (e.g. 80,443 or 1-65535)", required=True, flag="-p"),
],
    timeout=600,
    signal_quality=SignalQuality.CANDIDATE,
    priority=50,
    cost="high",
    risk_level="high",
))

# ── naabu (from naabu.yaml) ──
_register(ToolDefinition(
    name="naabu",
    description="Port scanning tool (fast TCP/UDP port discovery)",
    phases=["recon"],
    default_args=["-json"],
    parameters=[
    ToolParameter(name="target", description="Target host", required=True, flag="-host"),
    ToolParameter(name="top_ports", description="Top ports to scan", flag="-top-ports"),
    ToolParameter(name="port_range", description="Port range (e.g. 1-1000)", flag="-p"),
],
    timeout=300,
    signal_quality=SignalQuality.CANDIDATE,
    priority=75,
    cost="medium",
    risk_level="medium",
))

# ── nikto (from nikto.yaml) ──
_register(ToolDefinition(
    name="nikto",
    description="Nikto web server scanner for known vulnerabilities and misconfigurations",
    phases=["recon", "scan", "deep_scan"],
    default_args=["-Tuning", "123456", "-timeout", "10", "-ask", "no", "-nointeractive"],
    parameters=[
    ToolParameter(name="target", description="Target URL or host", required=True, flag="-h"),
],
    timeout=120,
    signal_quality=SignalQuality.CANDIDATE,
    priority=60,
    cost="medium",
    risk_level="medium",
))

# ── nmap (from nmap.yaml) ──
_register(ToolDefinition(
    name="nmap",
    description="Nmap port scanner for port discovery and service identification",
    phases=["recon"],
    default_args=["-sT", "-Pn", "-oX", "-", "-T4", "--top-ports", "200"],
    parameters=[
    ToolParameter(name="target", description="Target hostname or IP address", required=True),
    ToolParameter(name="ports", description="Port range (e.g. 80,443 or 1-1000)", flag="-p"),
],
    timeout=300,
    signal_quality=SignalQuality.CONFIRMED,
    priority=85,
    cost="medium",
    risk_level="medium",
))

# ── npm-audit (from npm-audit.yaml) ──
_register(ToolDefinition(
    name="npm-audit",
    description="Node.js dependency vulnerability scanner",
    binary="npm",
    phases=["repo_scan", "scan", "deep_scan"],
    target_kind="path",
    default_args=["audit", "--json"],
    parameters=[
    ToolParameter(name="target", description="Target project directory (must contain package.json)", required=True),
],
    timeout=300,
    signal_quality=SignalQuality.CANDIDATE,
    requires=ToolRequires(tech_contains=["javascript", "typescript"]),
    priority=50,
    cost="low",
    risk_level="low",
))

# ── nuclei (from nuclei.yaml) ──
_register(ToolDefinition(
    name="nuclei",
    description="Nuclei vulnerability scanner using customizable YAML templates",
    phases=["scan", "deep_scan"],
    default_args=["-jsonl", "-silent", "-timeout", "10", "-retries", "1", "-bulk-size", "25", "-concurrency", "10"],
    parameters=[
    ToolParameter(name="target", description="Target URL or host to scan", required=True, flag="-u"),
    ToolParameter(name="severity", description="Severity filter (info, low, medium, high, critical)", flag="-severity"),
    ToolParameter(name="templates", description="Custom template directory or template ID", flag="-t"),
    ToolParameter(name="tags", description="Template tags to run (comma-separated)", flag="-tags"),
],
    timeout=600,
    signal_quality=SignalQuality.CONFIRMED,
    priority=95,
    cost="medium",
    risk_level="medium",
))



# ── playwright-bola (from playwright-bola.yaml) ──
_register(ToolDefinition(
    name="playwright-bola",
    description="Broken Object Level Authorization detection via browser automation",
    binary="python3",
    phases=["scan", "deep_scan"],
    default_args=["argus-workers/tools/scripts/playwright_bola.py"],
    parameters=[
    ToolParameter(name="target", description="Target URL", required=True, flag="--target"),
    ToolParameter(name="creds_file", description="Path to JSON credentials file with attacker/victim credentials (alternative to --attacker-username/--attacker-password and --victim-username/--victim-password)", flag="--creds-file"),
    ToolParameter(name="attacker-username", description="Attacker username (not required when --creds-file is provided)", flag="--attacker-username"),
    ToolParameter(name="attacker-password", description="Attacker password (not required when --creds-file is provided)", flag="--attacker-password"),
    ToolParameter(name="victim-username", description="Victim username (not required when --creds-file is provided)", flag="--victim-username"),
    ToolParameter(name="victim-password", description="Victim password (not required when --creds-file is provided)", flag="--victim-password"),
    ToolParameter(name="resource-pattern", description="URL pattern for victim resource (use {username} placeholder)", flag="--resource-pattern", default="/api/users/{username}/details"),
    ToolParameter(name="username-selector", description="CSS selector for username input field", flag="--username-selector", default="input[name=username]"),
    ToolParameter(name="password-selector", description="CSS selector for password input field", flag="--password-selector", default="input[name=password]"),
    ToolParameter(name="submit-selector", description="CSS selector for submit button", flag="--submit-selector", default="button[type=submit]"),
],
    timeout=120,
    signal_quality=SignalQuality.CONFIRMED,
    requires=ToolRequires(target_scheme="['http', 'https']"),
    priority=80,
    cost="medium",
    risk_level="low",
))

# ── playwright-privesc (from playwright-privesc.yaml) ──
_register(ToolDefinition(
    name="playwright-privesc",
    description="Privilege Escalation detection via browser automation",
    binary="python3",
    phases=["scan", "deep_scan"],
    default_args=["argus-workers/tools/scripts/playwright_privesc.py"],
    parameters=[
    ToolParameter(name="target", description="Target URL", required=True, flag="--target"),
    ToolParameter(name="creds_file", description="Path to JSON credentials file with low-privilege credentials (alternative to --low-priv-username/--low-priv-password)", flag="--creds-file"),
    ToolParameter(name="low-priv-username", description="Low-privilege user username (not required when --creds-file is provided)", flag="--low-priv-username"),
    ToolParameter(name="low-priv-password", description="Low-privilege user password (not required when --creds-file is provided)", flag="--low-priv-password"),
    ToolParameter(name="admin-paths", description="Comma-separated admin endpoints to probe", flag="--admin-paths"),
    ToolParameter(name="username-selector", description="CSS selector for username input field", flag="--username-selector", default="input[name=username]"),
    ToolParameter(name="password-selector", description="CSS selector for password input field", flag="--password-selector", default="input[name=password]"),
    ToolParameter(name="submit-selector", description="CSS selector for submit button", flag="--submit-selector", default="button[type=submit]"),
],
    timeout=120,
    signal_quality=SignalQuality.CONFIRMED,
    requires=ToolRequires(target_scheme="['http', 'https']"),
    priority=80,
    cost="medium",
    risk_level="low",
))

# ── playwright-xss (from playwright-xss.yaml) ──
_register(ToolDefinition(
    name="playwright-xss",
    description="Stored Cross-Site Scripting detection via browser automation",
    binary="python3",
    phases=["scan", "deep_scan"],
    default_args=["argus-workers/tools/scripts/playwright_xss.py"],
    parameters=[
    ToolParameter(name="target", description="Target URL", required=True, flag="--target"),
    ToolParameter(name="creds_file", description="Path to JSON credentials file with login credentials (alternative to --username/--password)", flag="--creds-file"),
    ToolParameter(name="username", description="Login username (not required when --creds-file is provided)", flag="--username"),
    ToolParameter(name="password", description="Login password (not required when --creds-file is provided)", flag="--password"),
    ToolParameter(name="form-page", description="Path to the form page (default /feedback)", flag="--form-page", default="/feedback"),
    ToolParameter(name="payload", description="XSS payload to inject", flag="--payload"),
    ToolParameter(name="username-selector", description="CSS selector for username input field", flag="--username-selector", default="input[name=username]"),
    ToolParameter(name="password-selector", description="CSS selector for password input field", flag="--password-selector", default="input[name=password]"),
    ToolParameter(name="submit-selector", description="CSS selector for submit button", flag="--submit-selector", default="button[type=submit]"),
],
    timeout=120,
    signal_quality=SignalQuality.CONFIRMED,
    requires=ToolRequires(target_scheme="['http', 'https']"),
    priority=80,
    cost="medium",
    risk_level="low",
))

# ── register (from register.yaml) ──
_register(ToolDefinition(
    name="register",
    description="register - security assessment tool",
    binary="python3",
    phases=["scan"],
    default_args=["argus-workers/tools/run_agent_tool.py", "register"],
    parameters=[
    ToolParameter(name="target", description="Target URL or scope", required=True, flag="--target"),
    ToolParameter(name="extra", description="JSON-encoded extra parameters (e.g. {\"email\":\"test@example.com\",\"password\":\"test123\"})", flag="--extra"),
],
    timeout=300,
    signal_quality=SignalQuality.CONFIRMED,
    priority=95,
    cost="low",
    risk_level="low",
))

# ── s3scanner (from s3scanner.yaml) ──
_register(ToolDefinition(
    name="s3scanner",
    description="Amazon S3 bucket discovery and enumeration",
    phases=["recon", "scan"],
    default_args=["-json"],
    parameters=[
    ToolParameter(name="target", description="Bucket name to check", required=True, flag="-bucket"),
],
    timeout=180,
    signal_quality=SignalQuality.CANDIDATE,
    priority=35,
    cost="low",
    risk_level="low",
))

# ── secure_code_intelligence_engine (from secure_code_intelligence_engine.yaml) ──
_register(ToolDefinition(
    name="secure_code_intelligence_engine",
    description="secure_code_intelligence_engine - security assessment tool",
    binary="python3",
    phases=["source_analysis", "analyze", "repo_scan"],
    default_args=["argus-workers/tools/run_agent_tool.py", "secure_code_intelligence_engine"],
    parameters=[
    ToolParameter(name="target", description="Target URL or scope", required=True, flag="--target"),
    ToolParameter(name="extra", description="JSON-encoded extra parameters (e.g. {\"tech_stack\":[\"apache\"]})", flag="--extra"),
],
    timeout=300,
    signal_quality=SignalQuality.CONFIRMED,
    priority=90,
    cost="low",
    risk_level="low",
))

# ── semgrep (from semgrep.yaml) ──
_register(ToolDefinition(
    name="semgrep",
    description="Static code analysis tool for finding security issues and code quality problems",
    phases=["repo_scan", "scan", "deep_scan"],
    target_kind="path",
    default_args=["--json"],
    parameters=[
    ToolParameter(name="target", description="Target path", required=True),
    ToolParameter(name="config", description="Rule config path", flag="--config"),
],
    timeout=600,
    signal_quality=SignalQuality.CONFIRMED,
    priority=80,
    cost="medium",
    risk_level="low",
))

# ── shuffledns (from shuffledns.yaml) ──
_register(ToolDefinition(
    name="shuffledns",
    description="Mass DNS resolver for resolved subdomain enumeration",
    phases=[],
    disabled_reason=(
        "needs a public resolver list (-r) to mass-resolve; without one the "
        "installed build exits 0 having resolved nothing"
    ),
    default_args=["-silent"],
    parameters=[
    ToolParameter(name="target", description="Subdomain list or domain", required=True, flag="-d"),
    ToolParameter(name="wordlist", description="Wordlist for brute forcing", flag="-w"),
],
    timeout=300,
    signal_quality=SignalQuality.CANDIDATE,
    priority=45,
    cost="medium",
    risk_level="low",
))

# ── sn1per (from sn1per.yaml) ──
_register(ToolDefinition(
    name="sn1per",
    description="Automated penetration testing framework",
    phases=["scan", "deep_scan"],
    parameters=[
    ToolParameter(name="target", description="Target domain or IP", required=True),
],
    timeout=600,
    signal_quality=SignalQuality.CANDIDATE,
    priority=40,
    cost="high",
    risk_level="high",
))


# ── sqlmap (from sqlmap.yaml) ──
_register(ToolDefinition(
    name="sqlmap",
    description="SQL injection detection and exploitation tool",
    phases=["scan", "deep_scan"],
    default_args=["--batch"],
    parameters=[
    ToolParameter(name="target", description="Target URL", required=True, flag="-u"),
    ToolParameter(name="level", description="Test level (1-5)", flag="--level", default=1),
    ToolParameter(name="risk", description="Risk level (1-3)", flag="--risk", default=1),
],
    timeout=600,
    signal_quality=SignalQuality.CONFIRMED,
    requires=ToolRequires(recon_signals=["parameterized_forms"]),
    priority=90,
    cost="high",
    risk_level="high",
))

# ── subfinder (from subfinder.yaml) ──
_register(ToolDefinition(
    name="subfinder",
    description="Fast passive subdomain enumeration tool using multiple sources",
    phases=["recon"],
    default_args=["-silent"],
    parameters=[
    ToolParameter(name="target", description="Target domain to enumerate subdomains for", required=True, flag="-d"),
    ToolParameter(name="all", description="Use all sources (including slower ones)", flag="-all"),
],
    timeout=300,
    signal_quality=SignalQuality.CANDIDATE,
    priority=70,
    cost="low",
    risk_level="low",
))


# ── threat_intelligence_aggregator (from threat_intelligence_aggregator.yaml) ──
_register(ToolDefinition(
    name="threat_intelligence_aggregator",
    description="threat_intelligence_aggregator - security assessment tool",
    binary="python3",
    phases=["analyze"],
    default_args=["argus-workers/tools/run_agent_tool.py", "threat_intelligence_aggregator"],
    parameters=[
    ToolParameter(name="target", description="Target URL or scope", required=True, flag="--target"),
    ToolParameter(name="extra", description="JSON-encoded extra parameters (e.g. {\"tech_stack\":[\"apache\"]})", flag="--extra"),
],
    timeout=300,
    signal_quality=SignalQuality.CONFIRMED,
    priority=90,
    cost="low",
    risk_level="low",
))

# ── trivy (from trivy.yaml) ──
_register(ToolDefinition(
    name="trivy",
    description="Container and filesystem vulnerability scanner",
    phases=["repo_scan", "scan", "deep_scan"],
    target_kind="path",
    default_args=["fs", "--format", "json", "--skip-dirs", "node_modules,vendor,dist,build,.git,coverage"],
    parameters=[
    ToolParameter(name="target", description="Image name or filesystem path", required=True),
    ToolParameter(name="scanners", description="Comma-separated scanners (vuln,misconfig,secret)", flag="--scanners", default="vuln,misconfig,secret"),
],
    timeout=600,
    signal_quality=SignalQuality.PROBABLE,
    priority=75,
    cost="medium",
    risk_level="medium",
))



# ── verification_agent (from verification_agent.yaml) ──
_register(ToolDefinition(
    name="verification_agent",
    description="verification_agent - security assessment tool",
    binary="python3",
    phases=["analyze"],
    default_args=["argus-workers/tools/run_agent_tool.py", "verification_agent"],
    parameters=[
    ToolParameter(name="target", description="Target URL or scope", required=True, flag="--target"),
    ToolParameter(name="extra", description="JSON-encoded extra parameters (e.g. {\"tech_stack\":[\"apache\"]})", flag="--extra"),
],
    timeout=300,
    signal_quality=SignalQuality.CONFIRMED,
    priority=90,
    cost="low",
    risk_level="low",
))

# ── vulnerability_knowledge_engine (from vulnerability_knowledge_engine.yaml) ──
_register(ToolDefinition(
    name="vulnerability_knowledge_engine",
    description="vulnerability_knowledge_engine - security assessment tool",
    binary="python3",
    phases=["analyze"],
    default_args=["argus-workers/tools/run_agent_tool.py", "vulnerability_knowledge_engine"],
    parameters=[
    ToolParameter(name="target", description="Target URL or scope", required=True, flag="--target"),
    ToolParameter(name="extra", description="JSON-encoded extra parameters (e.g. {\"tech_stack\":[\"apache\"]})", flag="--extra"),
],
    timeout=300,
    signal_quality=SignalQuality.CONFIRMED,
    priority=90,
    cost="low",
    risk_level="low",
))

# ── wafw00f (from wafw00f.yaml) ──
_register(ToolDefinition(
    name="wafw00f",
    description="Web Application Firewall fingerprinting and detection",
    phases=["recon"],
    default_args=["-a"],
    parameters=[
    ToolParameter(name="target", description="Target URL", required=True),
    ToolParameter(name="verbose", description="Enable verbose output", flag="-v"),
],
    timeout=120,
    signal_quality=SignalQuality.CONFIRMED,
    priority=45,
    cost="low",
    risk_level="low",
))

# ── waybackurls (from waybackurls.yaml) ──
_register(ToolDefinition(
    name="waybackurls",
    description="Fetch URLs from Wayback Machine archive",
    phases=["recon"],
    parameters=[
    ToolParameter(name="target", description="Target domain", required=True),
],
    timeout=120,
    signal_quality=SignalQuality.CANDIDATE,
    priority=35,
    cost="low",
    risk_level="low",
))

# ── whatweb (from whatweb.yaml) ──
_register(ToolDefinition(
    name="whatweb",
    description="WhatWeb technology detection and fingerprinting",
    phases=["recon"],
    parameters=[
    ToolParameter(name="target", description="Target URL to fingerprint", required=True),
],
    timeout=120,
    signal_quality=SignalQuality.CANDIDATE,
    priority=75,
    cost="low",
    risk_level="low",
))

# ── workflow_intelligence_engine (from workflow_intelligence_engine.yaml) ──
_register(ToolDefinition(
    name="workflow_intelligence_engine",
    description="workflow_intelligence_engine - security assessment tool",
    binary="python3",
    phases=["analyze"],
    default_args=["argus-workers/tools/run_agent_tool.py", "workflow_intelligence_engine"],
    parameters=[
    ToolParameter(name="target", description="Target URL or scope", required=True, flag="--target"),
    ToolParameter(name="extra", description="JSON-encoded extra parameters (e.g. {\"tech_stack\":[\"apache\"]})", flag="--extra"),
],
    timeout=300,
    signal_quality=SignalQuality.CONFIRMED,
    priority=90,
    cost="low",
    risk_level="low",
))

# ── api-spec (from api-spec.yaml) ──
_register(ToolDefinition(
    name="api-spec",
    description="Spec-driven API testing: replays every operation in the OpenAPI/Swagger document",
    phases=["api_exploitation"],
    binary="python3",
    default_args=["argus-workers/tools/api_spec_scan.py", "--mode", "spec"],
    parameters=[
    ToolParameter(name="target", description="Target base URL (the document is discovered under it)", required=True, flag="--target"),
    ToolParameter(name="spec_url", description="Explicit OpenAPI/Swagger document URL (skips discovery)", flag="--spec-url"),
],
    timeout=300,
    signal_quality=SignalQuality.CONFIRMED,
    priority=78,
    cost="low",
    risk_level="low",
))

# ── graphql (from graphql.yaml) ──
_register(ToolDefinition(
    name="graphql",
    description="GraphQL testing: introspection, query depth, unauthenticated mutations",
    phases=["api_exploitation"],
    binary="python3",
    default_args=["argus-workers/tools/api_spec_scan.py", "--mode", "graphql"],
    parameters=[
    ToolParameter(name="target", description="Target URL (base URL or the GraphQL endpoint itself)", required=True, flag="--target"),
],
    timeout=180,
    signal_quality=SignalQuality.CONFIRMED,
    priority=76,
    cost="low",
    risk_level="low",
))

# ── Delegated tools (YAML + delegate_shim.py) ──
# Their YAML file is the only definition; see _delegate_tools.py for why the mirror
# above must not carry a second copy of that metadata.
from _delegate_tools import register_delegates as _register_delegates

_register_delegates(_register, ToolDefinition, ToolParameter, ToolRequires, SignalQuality)
