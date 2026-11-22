import crypto from "crypto"
import type { NormalizedFinding, EvidencePackage, ResponseEvidence } from "../shared/types"
import { Severity, Confidence } from "../shared/types"

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

/** Coerce a scanner's http_response block into the reportable shape. */
function asResponseEvidence(value: unknown): ResponseEvidence | undefined {
  if (!value || typeof value !== "object") return undefined
  const v = value as Record<string, unknown>
  const str = (x: unknown) => (typeof x === "string" && x ? x : undefined)
  const num = (x: unknown) => (typeof x === "number" ? x : undefined)
  const result: ResponseEvidence = {
    url: str(v.url),
    statusCode: num(v.status_code ?? v.statusCode),
    headers:
      v.headers && typeof v.headers === "object"
        ? (v.headers as Record<string, string>)
        : undefined,
    bodyBytes: num(v.body_bytes ?? v.bodyBytes),
    bodySha256: str(v.body_sha256 ?? v.bodySha256),
    preview: str(v.body_preview ?? v.preview),
  }
  return Object.values(result).every((field) => field === undefined) ? undefined : result
}

/**
 * Pull the observed response out of a worker finding.
 *
 * Web scanner findings carry it as an ``http_response`` evidence entry; the
 * direct field is honoured too so other producers can set it without
 * pretending to be the web scanner.
 */
export function responseEvidenceFrom(
  input: Record<string, unknown>,
): ResponseEvidence | undefined {
  const direct = asResponseEvidence(input.responseEvidence)
  if (direct) return direct
  const entries = Array.isArray(input.evidence) ? input.evidence : [input.evidence]
  for (const entry of entries) {
    if (!entry || typeof entry !== "object") continue
    const record = entry as Record<string, unknown>
    const observed = asResponseEvidence(record.http_response ?? record.httpResponse)
    if (observed) return observed
  }
  return undefined
}

export function normalizeFinding(raw: unknown): NormalizedFinding {
  const input = raw as Record<string, unknown>

  return {
    id: (input.id as string) ?? `find-${crypto.randomUUID()}`,
    title: (input.title as string) || "Unknown Finding",
    severity: enumValue(Severity, input.severity, Severity.INFO),
    confidence: enumValue(Confidence, input.confidence, Confidence.INFORMATIONAL),
    status: (input.status as NormalizedFinding["status"]) ?? "PENDING",
    description: (input.description as string) || "",
    subtype: input.subtype as string,
    evidence: input.evidence as EvidencePackage[] | undefined,
    responseEvidence: responseEvidenceFrom(input),
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
