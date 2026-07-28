export declare enum Capability {
    WEB_RECON = "web_recon",
    PORT_SCANNING = "port_scanning",
    TECHNOLOGY_DETECTION = "technology_detection",
    CONTENT_DISCOVERY = "content_discovery",
    API_PROBING = "api_probing",
    AUTH_DETECTION = "auth_detection",
    CREDENTIAL_ANALYSIS = "credential_analysis",
    VULNERABILITY_SCANNING = "vulnerability_scanning",
    TEMPLATE_SCANNING = "template_scanning",
    BROWSER_VERIFICATION = "browser_verification",
    REPORT_GENERATION = "report_generation",
    SQLI_DETECTION = "sqli_detection",
    XSS_DETECTION = "xss_detection",
    DATABASE_EXFILTRATION = "database_exfiltration",
    HTTP_PROBE = "http_probe",
    GRAPHQL_ASSESSMENT = "graphql_assessment",
    EXPRESS_CVE_SCAN = "express_cve_scan",
    API_DOCS_ANALYSIS = "api_docs_analysis",
    JWT_ANALYSIS = "jwt_analysis",
    SSRF_CHECK = "ssrf_check",
    COMMAND_INJECTION = "command_injection",
    POST_EXPLOITATION = "post_exploitation",
    CLOUD_METADATA_PROBE = "cloud_metadata_probe",
    SESSION_HIJACK_ATTEMPT = "session_hijack_attempt",
    LATERAL_MOVEMENT = "lateral_movement",
    PHISHING_CHAIN = "phishing_chain",
    CREDENTIAL_REPLAY = "credential_replay",
    SECURITY_ANALYSIS = "security_analysis",
    SECRET_DETECTION = "secret_detection",
    SAST = "sast",
    SCA = "sca",
    /** @deprecated No tool provider exists — generic VULNERABILITY_SCANNING covers CVEs. */
    CVE_SCANNING = "cve_scanning",
    CLOUD_ENUM = "cloud_enum",
    S3_SCANNING = "s3_scanning"
}
/**
 * Map an LLM-suggested capability string to a Capability enum value.
 * The Python/MCP side may return strings like "XSS_DETECTION", "POST_EXPLOIT",
 * or "deep_scan" in various cases. This tries an exact match against known
 * capabilities, then falls back to a case-insensitive lookup.
 *
 * @param key - The capability string from the LLM (e.g. "SQLI_DETECTION", "post_exploit")
 * @returns The matching Capability enum value, or undefined if unrecognized
 */
export declare function guessCapability(key: string): Capability | undefined;
