import type { NormalizedFinding, EvidencePackage } from "../planner/types"
import { Severity, Confidence } from "../planner/types"

function enumValue<T extends Record<string, number | string>>(e: T, v: unknown, fallback: T[keyof T]): T[keyof T] {
  const num = Number(v)
  if (!Number.isNaN(num) && (Object.values(e) as unknown[]).includes(num)) {
    return num as T[keyof T]
  }
  if (typeof v === "string") {
    const val = (e as Record<string, unknown>)[v]
    if (typeof val === "number") return val as T[keyof T]
  }
  return fallback
}

export function normalizeFinding(raw: unknown): NormalizedFinding {
  const input = raw as Record<string, unknown>

  return {
    id: (input.id as string) ?? `find-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 6)}`,
    title: (input.title as string) || "Unknown Finding",
    severity: enumValue(Severity, input.severity, Severity.INFO),
    confidence: enumValue(Confidence, input.confidence, Confidence.INFORMATIONAL),
    status: (input.status as NormalizedFinding["status"]) ?? "PENDING",
    description: (input.description as string) || "",
    subtype: input.subtype as string,
    evidence: input.evidence as EvidencePackage[] | undefined,
    cve: input.cve as string,
    cwe: input.cwe as string,
    owasp: input.owasp as string,
    remediation: input.remediation as string,
    tool: (input.tool as string) || "unknown",
    phase: (input.phase as string) || "unknown",
    created_at: (input.created_at as string) ?? new Date().toISOString(),
    updated_at: (input.updated_at as string) ?? new Date().toISOString(),
  }
}
