import { NormalizedFinding, Severity, Confidence } from "../planner/types"

export function normalizeFinding(raw: unknown): NormalizedFinding {
  const input = raw as Record<string, unknown>

  return {
    id: (input.id as string) ?? `find-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 6)}`,
    title: (input.title as string) ?? "Unknown Finding",
    severity: (input.severity as Severity) ?? Severity.INFO,
    confidence: (input.confidence as Confidence) ?? Confidence.INFORMATIONAL,
    status: "PENDING",
    description: (input.description as string) ?? "",
    subtype: input.subtype as string,
    cve: input.cve as string,
    cwe: input.cwe as string,
    owasp: input.owasp as string,
    remediation: input.remediation as string,
    tool: (input.tool as string) ?? "unknown",
    phase: (input.phase as string) ?? "unknown",
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  }
}
