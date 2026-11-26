/** Role tool policy: the verifier is deliberately narrower than vuln-scan. */

import { describe, expect, test } from "bun:test"
import { SECURITY_ROLES } from "../../../src/argus/agents/security-roles"

function allowList(role: string): string[] {
  const found = SECURITY_ROLES.find((r) => r.name === role)
  if (!found) throw new Error(`no such role: ${role}`)
  return Object.entries(found.permission)
    .filter(([, rule]) => rule === "allow")
    .map(([tool]) => tool)
}

describe("security role tool policy", () => {
  test("verifier excludes high-impact injectors and state-modifying tools", () => {
    const verifier = allowList("verifier")
    for (const excluded of [
      "sqlmap",
      "commix",
      "cloud-metadata-probe",
      "bucket-upload",
      "login",
      "register",
    ]) {
      expect(verifier, `verifier must not allow ${excluded}`).not.toContain(excluded)
    }
    // ...but keeps the core re-probing scanners and the finding verifier.
    for (const kept of ["nuclei", "dalfox", "nikto", "finding-verifier"]) {
      expect(verifier, `verifier must keep ${kept}`).toContain(kept)
    }
  })

  test("verifier is a strict subset of vuln-scan", () => {
    const scanner = new Set(allowList("vuln-scan"))
    for (const tool of allowList("verifier")) {
      if (tool === "bash" || tool === "read" || tool === "grep" || tool === "glob" || tool === "list") continue
      expect(scanner.has(tool), `verifier tool ${tool} not in vuln-scan`).toBe(true)
    }
    expect(allowList("verifier").length).toBeLessThan(allowList("vuln-scan").length)
  })
})
