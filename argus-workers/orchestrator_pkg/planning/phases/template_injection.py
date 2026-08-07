"""Phase: template_injection — _activate_template_injection and _template_injection_tools."""

from __future__ import annotations

import logging

from ._types import ToolTask, _get_attr, _get_tech_stack

logger = logging.getLogger(__name__)





# Recognized templating engines and their framework/language associations
_TEMPLATE_ENGINES: set[str] = {
    # Python
    "jinja", "jinja2", "mako", "tornado", "django template",
    # PHP
    "twig", "smarty", "blade", "latte", "plates",
    # JavaScript / TypeScript
    "pug", "jade", "handlebars", "mustache", "ejs",
    "nunjucks", "liquid", "eta", "hogan.js",
    # Ruby
    "erb", "haml", "slim",
    # Java
    "velocity", "freemarker", "thymeleaf", "jsp",
    "apache tiles", "groovy template",
    # Go
    "go template", "html/template",
    # .NET
    "razor", "dotliquid",
}
def _activate_template_injection(rc) -> tuple[bool, str]:
    """Activate when recognized templating engines are detected in tech_stack.

    Server-Side Template Injection (SSTI) occurs when user input is
    embedded in template expressions without proper sanitization.
    Impact ranges from information disclosure to remote code execution
    depending on the template engine.

    Activates when:
      - ``has_template_injection`` flag is set (forward-compatible)
      - ``template_engines`` list is populated (forward-compatible)
      - Known templating engines appear in tech_stack
      - Parameter-bearing URLs are present (SSTI vector)
    """
    # Forward-compatible: check for dedicated SSTI attribute
    has_ssti = _get_attr(rc, "has_template_injection", False)
    if has_ssti:
        return True, "template injection signals detected in recon"

    tpl_engines = _get_attr(rc, "template_engines", [])
    if tpl_engines and len(tpl_engines) > 0:
        return True, f"{len(tpl_engines)} template engine(s) detected: {', '.join(tpl_engines[:3])}"

    # Check tech_stack for known templating engines
    tech = _get_tech_stack(rc)
    if tech:
        tech_lower = " ".join(t.lower() for t in tech)
        matched = [eng for eng in _TEMPLATE_ENGINES if eng in tech_lower]
        if matched:
            return True, f"templating engine detected: {', '.join(matched[:3])}"

    # Parameter-bearing URLs can be SSTI vectors
    param_urls = _get_attr(rc, "parameter_bearing_urls", [])
    if param_urls and len(param_urls) > 0:
        return True, f"{len(param_urls)} parameter-bearing URL(s) — potential SSTI vector"

    return False, "no templating engines or SSTI signals detected"


def _template_injection_tools(recon_context) -> list[ToolTask]:
    """Build tool tasks for server-side template injection testing.

    Tests for SSTI in:
      - Jinja2 / Django (Python) — {{ }} syntax
      - Twig / Smarty / Blade (PHP) — {{ }} / {$ } syntax
      - Pug / Handlebars / EJS (JS) — #{ } / {{ }} syntax
      - Velocity / FreeMarker (Java) — ${{ }} / ${ } syntax
      - ERB / HAML (Ruby) — <%= %> syntax
      - Generic template syntax detection
    """
    tools: list[ToolTask] = [
        ToolTask(
            tool_name="nuclei",
            description="Server-Side Template Injection scanning (multi-engine)",
            priority=10,
            timeout=300,
            args_template=["-u", "{target}", "-jsonl", "-silent",
                           "-severity", "medium,high,critical",
                           "-tags", "ssti,template-injection,injection"],
        ),
        ToolTask(
            tool_name="nuclei",
            description="SSTI polyglot detection and engine-specific probes",
            priority=20,
            timeout=300,
            args_template=["-u", "{target}", "-jsonl", "-silent",
                           "-severity", "medium,high,critical",
                           "-tags", "ssti,tech,rce,exposure"],
        ),
    ]
    return tools


# ── Phase: Deserialization Testing ────────────────────────────────────

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
