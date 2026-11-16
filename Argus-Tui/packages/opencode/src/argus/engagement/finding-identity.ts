import type { NormalizedFinding } from "../shared/types"

/**
 * What a finding *is*: the thing found, where, and by which tool.
 *
 * The id says nothing — recon crawls a page and api_discovery crawls it again,
 * and each phase hands its finding in with a fresh id. Both the run and the
 * resume path have to agree on this identity or a resumed run reports the same
 * endpoint twice (measured: 169 report entries over 89 stored findings).
 */
export function findingIdentity(finding: NormalizedFinding): string {
  return [
    finding.title,
    finding.tool ?? "",
    finding.url ?? "",
    finding.description ?? "",
  ].join("\u0000")
}

/**
 * Merge one finding into a list, keeping the strongest severity and confidence
 * seen. Returns true when the finding was new (so callers can emit it once).
 */
export function mergeFinding(findings: NormalizedFinding[], finding: NormalizedFinding): boolean {
  const identity = findingIdentity(finding)
  const existing = findings.find((candidate) => findingIdentity(candidate) === identity)
  if (!existing) {
    findings.push(finding)
    return true
  }
  if (finding.severity > existing.severity) existing.severity = finding.severity
  if (finding.confidence > existing.confidence) existing.confidence = finding.confidence
  return false
}
