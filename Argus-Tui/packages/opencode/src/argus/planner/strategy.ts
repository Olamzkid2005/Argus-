import type { TargetType, AuthState } from "./types"
import { Capability } from "./capabilities"

export function detectTargetType(url: string, techStack?: string[]): TargetType {
  const lowerUrl = url.toLowerCase()
  const tech = techStack?.map((t) => t.toLowerCase()) ?? []

  if (lowerUrl.includes("/api") || lowerUrl.includes("/graphql") || lowerUrl.endsWith(".json")) {
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

export function detectAuthState(url: string): AuthState {
  const lowerUrl = url.toLowerCase()
  if (lowerUrl.includes("oauth") || lowerUrl.includes("auth")) return "oauth"
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
  if (tech.includes("express")) caps.add(Capability.EXPRESS_CVE_SCAN)
  if (tech.includes("swagger") || tech.includes("openapi")) caps.add(Capability.API_DOCS_ANALYSIS)
  if (tech.includes("jwt")) caps.add(Capability.JWT_ANALYSIS)

  caps.add(Capability.BROWSER_VERIFICATION)
  caps.add(Capability.REPORT_GENERATION)

  return Array.from(caps)
}
