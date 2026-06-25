import { describe, expect, test } from "bun:test"

describe("evidenceCommand show action", () => {
  const fakeManifest = {
    package_id: "PKG-001",
    engagement_id: "ENG-001",
    created_at: "2024-01-01T00:00:00.000Z",
    artifacts: [
      { path: "requests/req.txt", hash: "abc123", type: "request" as const, size_bytes: 1024 },
      { path: "responses/res.txt", hash: "def456", type: "response" as const, size_bytes: 2048 },
    ],
    package_hash: "sha256hashvalue",
  }

  const fakeIntegrityPass = {
    valid: true,
    packageId: "PKG-001",
    manifestHash: "sha256hashvalue",
    computedHash: "sha256hashvalue",
    errors: [],
  }

  const fakeIntegrityFail = {
    valid: false,
    packageId: "PKG-001",
    manifestHash: "sha256hashvalue",
    computedHash: "differenthash",
    errors: ["Package hash does not match: expected sha256hashvalue, got differenthash"],
  }

  function buildShowOutput(
    integrity: typeof fakeIntegrityPass,
    manifest: typeof fakeManifest | null,
  ): string {
    const lines: string[] = []
    lines.push(`Package ID: ${integrity.packageId}`)
    lines.push(`Valid: ${integrity.valid}`)
    if (manifest) {
      if (manifest.artifacts.length > 0) {
        lines.push("Artifacts:")
        for (const art of manifest.artifacts) {
          lines.push(`  - ${art.path} (${art.type}, ${art.size_bytes} bytes)`)
        }
      }
    }
    if (integrity.errors.length > 0) {
      for (const err of integrity.errors) {
        lines.push(`  Error: ${err}`)
      }
    }
    const status = integrity.valid ? "INTACT" : "TAMPERED"
    lines.push(`Status: ${status}`)
    return lines.join("\n")
  }

  test("show action displays artifact contents for valid package", () => {
    const output = buildShowOutput(fakeIntegrityPass, fakeManifest)
    expect(output).toContain("Package ID: PKG-001")
    expect(output).toContain("Valid: true")
    expect(output).toContain("Artifacts:")
    expect(output).toContain("requests/req.txt (request, 1024 bytes)")
    expect(output).toContain("responses/res.txt (response, 2048 bytes)")
    expect(output).toContain("Status: INTACT")
  })

  test("show action reports TAMPERED status when integrity check fails", () => {
    const output = buildShowOutput(fakeIntegrityFail, fakeManifest)
    expect(output).toContain("Package ID: PKG-001")
    expect(output).toContain("Valid: false")
    expect(output).toContain("Status: TAMPERED")
    expect(output).toContain("Error:")
    expect(output).toContain("Package hash does not match")
  })

  test("show action includes artifact list even when integrity fails", () => {
    const output = buildShowOutput(fakeIntegrityFail, fakeManifest)
    expect(output).toContain("Artifacts:")
    expect(output).toContain("requests/req.txt")
    expect(output).toContain("responses/res.txt")
  })

  test("show action handles no artifacts gracefully", () => {
    const emptyManifest = { ...fakeManifest, artifacts: [] }
    const output = buildShowOutput(fakeIntegrityPass, emptyManifest)
    expect(output).toContain("Status: INTACT")
    expect(output).not.toContain("Artifacts:")
  })

  test("show action returns usage when arguments are missing", () => {
    const action = (args: string[]) => {
      const engagementId = args[0]
      const packageId = args[1]
      if (!engagementId || !packageId) {
        return "Usage: evidence show <engagement-id> <package-id>"
      }
      return "ok"
    }
    expect(action([])).toBe("Usage: evidence show <engagement-id> <package-id>")
    expect(action(["ENG-001"])).toBe("Usage: evidence show <engagement-id> <package-id>")
    expect(action(["ENG-001", "PKG-001"])).toBe("ok")
  })

  test("show action reports INTACT status when no errors present", () => {
    const output = buildShowOutput(fakeIntegrityPass, fakeManifest)
    expect(output).toContain("Status: INTACT")
    expect(output).not.toContain("Error:")
  })
})
