import { readFileSync } from "fs"
import YAML from "yaml"
import { Capability } from "../planner/capabilities"

interface ToolDef {
  name: string
  label: string
  capabilities: string[]
  requires_auth: boolean
  destructive: boolean
  supports_api: boolean
  supports_web: boolean
  timeout_seconds: number
  scoring?: {
    confidence_score: number
    coverage_score: number
  }
}

interface ToolDefsFile {
  tools: ToolDef[]
}

export class ToolRegistry {
  private toolsByCapability = new Map<Capability, ToolDef[]>()
  private toolsByName = new Map<string, ToolDef>()

  load(definitionsPath: string): void {
    const content = readFileSync(definitionsPath, "utf-8")
    const parsed: ToolDefsFile = YAML.parse(content)

    for (const tool of parsed.tools) {
      this.toolsByName.set(tool.name, tool)

      for (const cap of tool.capabilities) {
        if (!Object.values(Capability).includes(cap as Capability)) {
          throw new Error(`Tool '${tool.name}' declares unknown capability '${cap}'`)
        }
        const c = cap as Capability
        if (!this.toolsByCapability.has(c)) {
          this.toolsByCapability.set(c, [])
        }
        this.toolsByCapability.get(c)!.push(tool)
      }
    }
  }

  getToolsByCapability(cap: Capability): ToolDef[] {
    return this.toolsByCapability.get(cap) ?? []
  }

  getCapabilities(toolName: string): string[] {
    return this.toolsByName.get(toolName)?.capabilities ?? []
  }

  getTool(name: string): ToolDef | undefined {
    return this.toolsByName.get(name)
  }

  listTools(): ToolDef[] {
    return Array.from(this.toolsByName.values())
  }

  findBestTools(capabilities: Capability[], targetType: string): ToolDef[] {
    const candidates = new Map<string, { tool: ToolDef; score: number }>()

    for (const cap of capabilities) {
      const tools = this.getToolsByCapability(cap)
      for (const tool of tools) {
        const current = candidates.get(tool.name)
        const score = (tool.scoring?.confidence_score ?? 50) + (tool.scoring?.coverage_score ?? 50)

        if (!current || score > current.score) {
          candidates.set(tool.name, { tool, score })
        }
      }
    }

    return Array.from(candidates.values())
      .sort((a, b) => b.score - a.score)
      .map((c) => c.tool)
  }
}
