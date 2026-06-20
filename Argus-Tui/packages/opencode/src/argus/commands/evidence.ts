import { EngagementStore } from "../engagement/store"
import { EvidenceCollector } from "../evidence/collector"
import { verifyPackage } from "../evidence/integrity"
import { homedir } from "os"
import { join } from "path"

export async function evidenceCommand(
  action: "list" | "show" | "prune" | "verify-package",
  args: string[],
  overrides?: {
    store?: EngagementStore
    collector?: EvidenceCollector
  },
): Promise<string> {
  const store = overrides?.store ?? new EngagementStore()
  const evidenceBaseDir = join(homedir(), ".argus", "engagements")
  const lines: string[] = []

  switch (action) {
    case "list": {
      const engagementId = args[0]
      if (engagementId) {
        // List evidence for a specific engagement
        const findings = store.getFindings(engagementId)
        if (findings.length === 0) {
          return `No findings for engagement ${engagementId}`
        }
        lines.push(`Evidence for engagement ${engagementId}:`)
        for (const f of findings) {
          const packages = store.getEvidencePackages(f.id)
          lines.push(`  ${f.id}: ${f.title} (${packages.length} package(s))`)
          for (const pkg of packages) {
            const artifacts = store.getArtifacts(pkg.id)
            for (const art of artifacts) {
              lines.push(`    └─ ${art.type}: ${art.path} (${art.sizeBytes} bytes)`)
            }
          }
        }
      } else {
        // List all engagements with findings
        const engagements = store.listEngagements()
        if (engagements.length === 0) {
          return "No engagements found"
        }
        lines.push("Engagements with evidence:")
        for (const eng of engagements) {
          const findings = store.getFindings(eng.id)
          if (findings.length > 0) {
            lines.push(`  ${eng.id}: ${eng.target} (${findings.length} finding(s))`)
          }
        }
      }
      break
    }

    case "show": {
      const packageId = args[0]
      if (!packageId) {
        return "Usage: evidence show <package-id>"
      }
      const result = await verifyPackage(evidenceBaseDir, packageId)
      lines.push(`Package ID: ${result.packageId}`)
      lines.push(`Valid: ${result.valid}`)
      for (const err of result.errors) {
        lines.push(`  Error: ${err}`)
      }
      break
    }

    case "prune": {
      const retentionDays = parseInt(args[0] ?? "30", 10)
      const engagements = store.listEngagements()
      let totalPruned = 0
      for (const eng of engagements) {
        const collector = overrides?.collector ?? new EvidenceCollector(evidenceBaseDir)
        const pruned = await collector.pruneEngagement(eng.id, retentionDays)
        totalPruned += pruned
        store.appendAuditLog(eng.id, "EVIDENCE_PRUNE", `Pruned ${pruned} artifact(s) older than ${retentionDays} days`)
      }
      lines.push(`Pruned ${totalPruned} artifact(s) older than ${retentionDays} days across ${engagements.length} engagement(s)`)
      break
    }

    case "verify-package": {
      const packageId = args[0]
      if (!packageId) {
        return "Usage: evidence verify-package <package-id>"
      }
      const result = await verifyPackage(evidenceBaseDir, packageId)
      if (result.valid) {
        lines.push(`Package ${packageId}: OK (${result.manifestHash})`)
      } else {
        lines.push(`Package ${packageId}: INVALID`)
        for (const err of result.errors) {
          lines.push(`  ${err}`)
        }
      }
      break
    }

    default:
      return `Unknown evidence action: ${action}. Use: list, show <package-id>, prune [keep-last], verify-package <package-id>`
  }

  return lines.join("\n")
}
