import type { TargetType, AuthState } from "./types"
import { Capability } from "./capabilities"

export function detectTargetType(url: string, techStack?: string[]): TargetType {
  const lowerUrl = url.toLowerCase()
  const tech = techStack?.map((t) => t.toLowerCase()) ?? []

  if (/\/api(\/|$|\?|#)/.test(lowerUrl) || lowerUrl.includes("/graphql") || lowerUrl.endsWith(".json")) {
    return "api"
  }

  if (tech.includes("react") || tech.includes("vue") || tech.includes("angular") || tech.includes("svelte")) {
    return "spa"
  }

  if (lowerUrl.startsWith("http")) {
    return "web_app"
  }

  return "unknown"
}

/**
 * Detects auth state from URL alone.
 *
 * NOTE: URL-only detection is unreliable — it may miss auth mechanisms that
 * don't appear in the URL (e.g., header-based, cookie-based, form-based auth).
 * This is a best-effort heuristic and should be supplemented with actual page
 * analysis when accuracy is critical.
 */
export function detectAuthState(url: string): AuthState {
  const lowerUrl = url.toLowerCase()
  if (/(^|\/)(auth|login|signin|oauth)(\/|$|\?|#)/.test(lowerUrl)) return "oauth"
  if (lowerUrl.includes("jwt") || lowerUrl.includes("token")) return "jwt"
  if (lowerUrl.includes("session")) return "session"
  if (lowerUrl.startsWith("http")) return "basic"
  return "none"
}

export function determineRequiredCapabilities(
  targetType: TargetType,
  authState: AuthState,
  techStack?: string[],
): Capability[] {
  const caps = new Set<Capability>()

  caps.add(Capability.WEB_RECON)

  if (targetType === "web_app" || targetType === "spa") {
    caps.add(Capability.PORT_SCANNING)
    caps.add(Capability.TECHNOLOGY_DETECTION)
    caps.add(Capability.CONTENT_DISCOVERY)
    caps.add(Capability.VULNERABILITY_SCANNING)
    caps.add(Capability.TEMPLATE_SCANNING)
    caps.add(Capability.HTTP_PROBE)
  }

  if (targetType === "api") {
    caps.add(Capability.API_PROBING)
    caps.add(Capability.CONTENT_DISCOVERY)
    caps.add(Capability.VULNERABILITY_SCANNING)
    caps.add(Capability.HTTP_PROBE)
  }

  if (authState !== "none") {
    caps.add(Capability.AUTH_DETECTION)
    caps.add(Capability.CREDENTIAL_ANALYSIS)
  }

  const tech = techStack?.map((t) => t.toLowerCase()) ?? []
  if (tech.includes("graphql")) caps.add(Capability.GRAPHQL_ASSESSMENT)
  // EXPRESS_CVE_SCAN → VULNERABILITY_SCANNING: no dedicated Express CVE scanner exists.
  // Generic vulnerability scanners (nuclei, nikto, DependencyCheck, etc.) already
  // handle Express CVEs during the standard scan phase.
  if (tech.includes("express")) caps.add(Capability.VULNERABILITY_SCANNING)
  if (tech.includes("swagger") || tech.includes("openapi")) caps.add(Capability.API_DOCS_ANALYSIS)
  if (tech.includes("jwt")) caps.add(Capability.JWT_ANALYSIS)

  caps.add(Capability.BROWSER_VERIFICATION)
  caps.add(Capability.REPORT_GENERATION)

  return Array.from(caps)
}
