import { readFileSync, writeFileSync, existsSync, mkdirSync, readdirSync } from "fs"
import { join } from "path"
import { homedir } from "os"
import { EngagementState, PhaseRecord, EngagementStatus } from "./types"

const ENGAGEMENTS_DIR = join(homedir(), ".argus", "engagements")

export class EngagementStore {
  private ensureDir(): void {
    if (!existsSync(ENGAGEMENTS_DIR)) {
      mkdirSync(ENGAGEMENTS_DIR, { recursive: true })
    }
  }

  private engagementPath(id: string): string {
    return join(ENGAGEMENTS_DIR, `${id}.json`)
  }

  createEngagement(target: string, workflow: string): EngagementState {
    this.ensureDir()
    const id = `ENG-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 6)}`
    const now = new Date().toISOString()

    const engagement: EngagementState = {
      id,
      target,
      workflow,
      workflowVersion: 1,
      status: "CREATED",
      schemaVersion: 1,
      createdAt: now,
      updatedAt: now,
    }

    this.saveEngagement(engagement)
    return engagement
  }

  getEngagement(id: string): EngagementState | null {
    const path = this.engagementPath(id)
    if (!existsSync(path)) return null
    try {
      return JSON.parse(readFileSync(path, "utf-8"))
    } catch {
      return null
    }
  }

  saveEngagement(engagement: EngagementState): void {
    this.ensureDir()
    engagement.updatedAt = new Date().toISOString()
    writeFileSync(this.engagementPath(engagement.id), JSON.stringify(engagement, null, 2))
  }

  updateStatus(id: string, status: EngagementStatus): void {
    const engagement = this.getEngagement(id)
    if (engagement) {
      engagement.status = status
      this.saveEngagement(engagement)
    }
  }

  listEngagements(): EngagementState[] {
    this.ensureDir()
    const files = readdirSync(ENGAGEMENTS_DIR)
    return files
      .filter((f) => f.endsWith(".json"))
      .map((f) => {
        try {
          return JSON.parse(readFileSync(join(ENGAGEMENTS_DIR, f), "utf-8"))
        } catch {
          return null
        }
      })
      .filter((e): e is EngagementState => e !== null)
      .sort((a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime())
  }

  private phasesPath(id: string): string {
    return join(ENGAGEMENTS_DIR, `${id}-phases.json`)
  }

  savePhases(id: string, phases: PhaseRecord[]): void {
    this.ensureDir()
    writeFileSync(this.phasesPath(id), JSON.stringify(phases, null, 2))
  }

  getPhases(id: string): PhaseRecord[] {
    const path = this.phasesPath(id)
    if (!existsSync(path)) return []
    try {
      return JSON.parse(readFileSync(path, "utf-8"))
    } catch {
      return []
    }
  }
}
