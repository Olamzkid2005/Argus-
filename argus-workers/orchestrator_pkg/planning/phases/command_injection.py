"""Phase: command_injection — _activate_command_injection and _command_injection_tools."""

from __future__ import annotations

import logging

from ._types import ToolTask, _get_attr, _get_tech_stack

logger = logging.getLogger(__name__)





# Recognized OS command execution functions by language
_CMD_EXECUTION_FUNCTIONS: set[str] = {
    # Python
    "os.system", "subprocess", "subprocess.run", "subprocess.popen",
    "subprocess.call", "subprocess.check_call", "subprocess.check_output",
    "os.popen", "commands.getoutput", "pty.spawn",
    # PHP
    "exec", "shell_exec", "system", "passthru", "popen",
    "proc_open", "pcntl_exec", "eval", "assert",
    # Java
    "runtime.exec", "runtime.getruntime.exec", "processbuilder",
    "processbuilder.start",
    # .NET
    "process.start", "diagnostics.process.start",
    # Node.js
    "child_process", "child_process.exec", "child_process.execsync",
    "child_process.spawn", "child_process.execfile",
    "child_process.fork",
    # Ruby
    "open",
    # Go
    "os.exec", "exec.command", "exec.commandcontext",
}
def _activate_command_injection(rc) -> tuple[bool, str]:
    """Activate when shell-execution functions are detected in tech_stack.

    Command injection (also known as OS command injection) allows an
    attacker to execute arbitrary operating system commands via a
    vulnerable application. It is one of the most critical web
    application vulnerabilities (OWASP Top 3) and typically leads
    to full server compromise.

    Activates when:
      - ``has_command_injection`` flag is set (forward-compatible)
      - ``cmd_injection_endpoints`` list is populated (forward-compatible)
      - Shell-execution function keywords appear in tech_stack
      - Parameter-bearing URLs are present (command injection vector)
      - File upload is present (filename-based command injection)
    """
    # Forward-compatible: check for dedicated command injection attribute
    has_cmdi = _get_attr(rc, "has_command_injection", False)
    if has_cmdi:
        return True, "command injection signals detected in recon"

    cmdi_eps = _get_attr(rc, "cmd_injection_endpoints", [])
    if cmdi_eps and len(cmdi_eps) > 0:
        return True, f"{len(cmdi_eps)} command injection endpoint(s) found"

    # Check tech_stack for shell-execution function keywords
    tech = _get_tech_stack(rc)
    if tech:
        tech_lower = " ".join(t.lower() for t in tech)
        matched = [kw for kw in _CMD_EXECUTION_FUNCTIONS if kw in tech_lower]
        if matched:
            return True, f"shell execution function detected: {', '.join(matched[:3])}"

    # Parameter-bearing URLs are a common command injection vector
    param_urls = _get_attr(rc, "parameter_bearing_urls", [])
    reasons = []
    if param_urls and len(param_urls) > 0:
        reasons.append(f"{len(param_urls)} parameter URL(s)")

    # File upload can involve command injection via filename processing
    has_upload = _get_attr(rc, "has_file_upload", False)
    if has_upload:
        reasons.append("file upload present")

    if reasons:
        return True, "possible command injection context: " + "; ".join(reasons)

    return False, "no command injection signals detected"


def _command_injection_tools(recon_context) -> list[ToolTask]:
    """Build tool tasks for OS command injection vulnerability testing.

    Tests for:
      - Command injection via URL parameters (ping, host, nslookup)
      - Blind command injection (time-based, OOB/DNS)
      - Command injection via HTTP headers (User-Agent, X-Forwarded-For)
      - Command injection via file upload filenames
      - OS command chaining (; | && || `)
      - Blind payload delivery via OOB/out-of-band channels
      - Time-based command injection detection
    """
    tools: list[ToolTask] = [
        ToolTask(
            tool_name="nuclei",
            description="OS command injection scanning (parameter-based, blind, time-based)",
            priority=10,
            timeout=300,
            args_template=["-u", "{target}", "-jsonl", "-silent",
                           "-severity", "medium,high,critical",
                           "-tags", "cmd-injection,rce,command,oast,blind"],
        ),
        ToolTask(
            tool_name="nuclei",
            description="OS command injection via headers and chaining techniques",
            priority=20,
            timeout=300,
            args_template=["-u", "{target}", "-jsonl", "-silent",
                           "-severity", "medium,high,critical",
                           "-tags", "cmd-injection,oast,time-based,chaining,exposure"],
        ),
    ]
    return tools


# ── Phase: NoSQL Injection Testing ─────────────────────────────────────────

# NoSQL databases and related technologies for tech_stack matching
_NOSQL_DATABASES: set[str] = {
    # Document stores
    "mongodb", "mongo", "mongoose", "mongos", "mongosh",
    "couchdb", "couchbase", "pouchdb",
    "ravendb", "litedb", "sphinx",
    # Key-value stores
    "redis", "redis-rack", "redis-py",
    "dynamodb", "amazon dynamodb", "aws dynamodb",
    "riak", "etcd", "consul",
    # Wide-column stores
    "cassandra", "datastax", "scylla", "scylladb",
    "apache cassandra", "hbase", "apache hbase",
    # Graph databases
    "neo4j", "neo4j-ogm", "sparql",
    "orientdb", "arangodb", "janusgraph",
    # Search/document engines
    "elasticsearch", "elastic", "opensearch",
    "meilisearch", "algolia", "typesense",
    # Real-time / Firebase
    "firebase", "firestore", "realtime database",
    "supabase", "appwrite", "nhost",
    # Other NoSQL
    "cockroachdb", "rethinkdb", "leveldb",
    "rocksdb", "badgerdb", "boltdb",
    # ORM/ODM abstractions
    "prisma", "typeorm", "sequelize",
    "django mongodb", "flask-pymongo",
}
