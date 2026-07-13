export enum Capability {
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

  // Autonomous red-team / post-exploitation capabilities
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
  S3_SCANNING = "s3_scanning",
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
export function guessCapability(key: string): Capability | undefined {
  const upper = key.toUpperCase().replace(/\s+/g, "_")

  // Fast-path: direct match against known LLM-capability mapping
  const known: Record<string, Capability> = {
    "RECON": Capability.WEB_RECON,
    "SCAN": Capability.VULNERABILITY_SCANNING,
    "DEEP_SCAN": Capability.VULNERABILITY_SCANNING,
    "XSS_DETECTION": Capability.XSS_DETECTION,
    "SQLI_DETECTION": Capability.SQLI_DETECTION,
    "JWT_ANALYSIS": Capability.JWT_ANALYSIS,
    "SSRF_CHECK": Capability.SSRF_CHECK,
    "COMMAND_INJECTION": Capability.COMMAND_INJECTION,
    "BOLA_CHECK": Capability.API_PROBING,
    "IDOR_CHECK": Capability.API_PROBING,
    "AUTH_CHECK": Capability.AUTH_DETECTION,
    "CREDENTIAL_ANALYSIS": Capability.CREDENTIAL_ANALYSIS,
    "POST_EXPLOIT": Capability.POST_EXPLOITATION,
    "POST_EXPLOITATION": Capability.POST_EXPLOITATION,
    "CLOUD_METADATA_PROBE": Capability.CLOUD_METADATA_PROBE,
    "SECRET_DETECTION": Capability.SECRET_DETECTION,
    "SECRETS": Capability.SECRET_DETECTION,
    "LATERAL_MOVEMENT": Capability.LATERAL_MOVEMENT,
    "CREDENTIAL_REPLAY": Capability.CREDENTIAL_REPLAY,
    "SAST": Capability.SAST,
    "SCA": Capability.SCA,
    "CVE_SCANNING": Capability.VULNERABILITY_SCANNING,
    "TEMPLATE_SCANNING": Capability.TEMPLATE_SCANNING,
    "NUCLEI": Capability.TEMPLATE_SCANNING,
    "PORT_SCANNING": Capability.PORT_SCANNING,
    "CONTENT_DISCOVERY": Capability.CONTENT_DISCOVERY,
    "API_PROBING": Capability.API_PROBING,
    "GRAPHQL": Capability.GRAPHQL_ASSESSMENT,
    "BROWSER_VERIFICATION": Capability.BROWSER_VERIFICATION,
    "SESSION_HIJACK": Capability.SESSION_HIJACK_ATTEMPT,
    "PHISHING": Capability.PHISHING_CHAIN,
    "REPORT": Capability.REPORT_GENERATION,
    "DATABASE_EXFIL": Capability.DATABASE_EXFILTRATION,
  }

  if (known[upper]) return known[upper]

  // Fallback: case-insensitive scan of all Capability enum values
  const lower = upper.toLowerCase()
  for (const value of Object.values(Capability)) {
    if (typeof value === "string" && value.toLowerCase() === lower) {
      return value as Capability
    }
  }

  return undefined
}
