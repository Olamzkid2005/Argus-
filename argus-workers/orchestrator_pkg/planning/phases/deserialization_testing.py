"""Phase: deserialization_testing — _activate_deserialization_testing and _deserialization_testing_tools."""

from __future__ import annotations

import logging
from typing import Any

from ._types import ToolTask, _get_attr, _get_tech_stack

logger = logging.getLogger(__name__)





# Recognized deserialization libraries/frameworks by language
_DESERIALIZATION_LIBS: set[str] = {
    # Python
    "pickle", "yaml", "pyyaml", "ruamel.yaml", "jsonpickle",
    "cPickle", "dill", "cloudpickle", "shelve",
    # Java
    "xstream", "jackson", "fastjson", "jboss", "weblogic",
    "hessian", "kryo", "snakeyaml", "jodd", "json-io",
    "flexjson", "genson", "logback", "jndi",
    # PHP
    "php unserialize", "php serialization", "phpobject",
    # Ruby
    "ruby marshal", "oj.load", "ruby yaml load",
    # .NET
    "binaryformatter", "soapformatter", "losformatter",
    "datacontractserializer", "javascriptserializer",
    "netdatacontractserializer", "jsonnet",
    # Node.js / JavaScript
    "node-serialize", "serialize-javascript", "funcster",
    "node serialize", "javascript serialize",
}
def _activate_deserialization_testing(rc) -> tuple[bool, str]:
    """Activate when insecure deserialization libraries are detected.

    Insecure deserialization can lead to remote code execution (RCE),
    authentication bypass, and privilege escalation. The risk exists
    across all major languages that handle serialized data.

    Activates when:
      - ``has_deserialization`` flag is set (forward-compatible)
      - ``deserialization_libs`` list is populated (forward-compatible)
      - Known deserialization libraries appear in tech_stack
      - API endpoints are present (deserialization is common in APIs)
      - Parameter-bearing URLs are present (deserialization vector)
    """
    # Forward-compatible: check for dedicated deserialization attribute
    has_deser = _get_attr(rc, "has_deserialization", False)
    if has_deser:
        return True, "insecure deserialization signals detected in recon"

    deser_libs = _get_attr(rc, "deserialization_libs", [])
    if deser_libs and len(deser_libs) > 0:
        return True, f"{len(deser_libs)} deserialization library(ies) found: {', '.join(deser_libs[:3])}"

    # Check tech_stack for known deserialization libraries
    tech = _get_tech_stack(rc)
    if tech:
        tech_lower = " ".join(t.lower() for t in tech)
        matched = [lib for lib in _DESERIALIZATION_LIBS if lib in tech_lower]
        if matched:
            return True, f"deserialization library detected: {', '.join(matched[:3])}"

    # Deserialization is common via API request bodies
    has_api = _get_attr(rc, "has_api", False)
    api_eps = _get_attr(rc, "api_endpoints", [])
    if has_api:
        return True, "API detected — deserialization attack surface present"
    if api_eps and len(api_eps) > 0:
        return True, f"{len(api_eps)} API endpoint(s) — deserialization testing recommended"

    # Parameter-bearing URLs can carry serialized data
    param_urls = _get_attr(rc, "parameter_bearing_urls", [])
    if param_urls and len(param_urls) > 0:
        return True, f"{len(param_urls)} parameter-bearing URL(s) — potential deserialization vector"

    return False, "no deserialization signals detected"


def _deserialization_testing_tools(recon_context) -> list[ToolTask]:
    """Build tool tasks for insecure deserialization testing.

    Tests for deserialization vulnerabilities in:
      - Java: Jackson, Fastjson, XStream, JNDI injection via log4j
      - Python: Pickle, PyYAML, JSON Pickle
      - PHP: PHP object injection via unserialize()
      - .NET: BinaryFormatter, SoapFormatter, LosFormatter
      - Node.js: node-serialize, serialize-javascript
      - Ruby: Marshal.load, YAML.load
    """
    tools: list[ToolTask] = [
        ToolTask(
            tool_name="nuclei",
            description="Insecure deserialization scanning (Java, Python, PHP, .NET)",
            priority=10,
            timeout=300,
            args_template=["-u", "{target}", "-jsonl", "-silent",
                           "-severity", "medium,high,critical",
                           "-tags", "deserialization,rce,oob,injection"],
        ),
        ToolTask(
            tool_name="nuclei",
            description="JNDI injection and log4shell detection (deserialization vector)",
            priority=20,
            timeout=300,
            args_template=["-u", "{target}", "-jsonl", "-silent",
                           "-severity", "medium,high,critical",
                           "-tags", "jndi,log4shell,log4j,rce,oast"],
        ),
    ]
    return tools


# ── Phase: SSRF Testing ────────────────────────────────────────────────
