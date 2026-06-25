import { existsSync, readFileSync } from "fs"
import { join } from "path"
import { EngagementStore } from "../engagement/store"
import type { IEngagementStore } from "../engagement/types"
import { EvidenceCollector } from "../evidence/collector"
import { verifyPackage } from "../evidence/integrity"
import { StoragePaths } from "../storage/paths"

export async function evidenceCommand(
  action: "list" | "show" | "prune" | "verify-package",
  args: string[],
  overrides?: {
    store?: IEngagementStore
    collector?: EvidenceCollector
    evidenceBaseDir?: string
  },
): Promise<string> {
  const store = overrides?.store ?? new EngagementStore()
  const evidenceBaseDir = overrides?.evidenceBaseDir ?? StoragePaths.engagementsDir
  const lines: string[] = []

  switch (action) {
    case "list": {
      const engagementId = args[0]
      if (engagementId) {
        // List evidence for a specific engagement (bulk query instead of N+1)
        const evidenceByFinding = store.getEvidenceByEngagement(engagementId)
        if (evidenceByFinding.length === 0) {
          return `No findings for engagement ${engagementId}`
        }
        lines.push(`Evidence for engagement ${engagementId}:`)
        for (const entry of evidenceByFinding) {
          lines.push(`  ${entry.findingId}: ${entry.findingTitle} (${entry.packages.length} package(s))`)
          for (const pkg of entry.packages) {
            for (const art of pkg.artifacts) {
              lines.push(`    └─ ${art.type}: ${art.path} (${art.sizeBytes} bytes)`)
            }
          }
        }
      } else {
        // List all engagements with findings (single grouped query instead of N+1)
        const engagements = store.listEngagements()
        if (engagements.length === 0) {
          return "No engagements found"
        }
        const ids = engagements.map((e) => e.id)
        const countsByEngId = store.getFindingCountsByEngagementIds(ids)
        lines.push("Engagements with evidence:")
        for (const eng of engagements) {
          const count = countsByEngId.get(eng.id)?.total ?? 0
          if (count > 0) {
            lines.push(`  ${eng.id}: ${eng.target} (${count} finding(s))`)
          }
        }
      }
      break
    }

    case "show": {
      const engagementId = args[0]
      const packageId = args[1]
      if (!engagementId || !packageId) {
        return "Usage: evidence show <engagement-id> <package-id>"
      }
      const result = await verifyPackage(evidenceBaseDir, engagementId, packageId)
      lines.push(`Package ID: ${result.packageId}`)
      lines.push(`Valid: ${result.valid}`)
      const manifestPath = join(evidenceBaseDir, engagementId, "artifacts", packageId, "manifest.json")
      if (existsSync(manifestPath)) {
        const manifest = JSON.parse(readFileSync(manifestPath, "utf-8"))
        if (manifest.artifacts?.length > 0) {
          lines.push("Artifacts:")
          for (const art of manifest.artifacts) {
            lines.push(`  - ${art.path} (${art.type}, ${art.size_bytes} bytes)`)
          }
        }
      }
      if (result.errors.length > 0) {
        for (const err of result.errors) {
          lines.push(`  Error: ${err}`)
        }
      }
      const status = result.valid ? "INTACT" : "TAMPERED"
      lines.push(`Status: ${status}`)
      break
    }

    case "prune": {
      const rawDays = args[0] ?? "30"
      const retentionDays = parseInt(rawDays, 10)
      if (isNaN(retentionDays) || retentionDays < 1) {
        return `Invalid retention days: "${rawDays}". Usage: evidence prune [days] (must be a positive integer, defaults to 30)`
      }
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
      const engagementId = args[0]
      const packageId = args[1]
      if (!engagementId || !packageId) {
        return "Usage: evidence verify-package <engagement-id> <package-id>"
      }
      const result = await verifyPackage(evidenceBaseDir, engagementId, packageId)
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
