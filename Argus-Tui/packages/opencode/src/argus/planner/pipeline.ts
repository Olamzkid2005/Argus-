export interface DataContract {
  consumes: string[]
  provides: string[]
}

export interface PipelineStep {
  tool: string
  capabilities: string[]
  contracts: DataContract
  satisfied: boolean
}

export interface PipelineResult {
  steps: PipelineStep[]
  gaps: string[]
  circular: boolean
}

export function resolvePipeline(
  tools: Array<{
    name: string
    capabilities: string[]
    consumes?: string[]
    provides?: string[]
  }>,
  initialData: string[] = ["target"],
): PipelineResult {
  const available = new Set(initialData)
  const remaining = [...tools]
  const ordered: PipelineStep[] = []
  const gaps = new Set<string>()

  let prevSize = -1
  let circular = false

  while (remaining.length > 0 && remaining.length !== prevSize) {
    prevSize = remaining.length

    for (let i = remaining.length - 1; i >= 0; i--) {
      const tool = remaining[i]
      const consumes = tool.consumes ?? []

      const unsatisfied = consumes.filter(c => !available.has(c))
      if (unsatisfied.length === 0) {
        const provides = tool.provides ?? []
        for (const p of provides) {
          available.add(p)
        }

        ordered.push({
          tool: tool.name,
          capabilities: tool.capabilities,
          contracts: { consumes, provides },
          satisfied: true,
        })

        remaining.splice(i, 1)
      }
    }
  }

  for (const tool of remaining) {
    const consumes = tool.consumes ?? []
    const unsatisfied = consumes.filter(c => !available.has(c))
    for (const g of unsatisfied) {
      gaps.add(g)
    }

    ordered.push({
      tool: tool.name,
      capabilities: tool.capabilities,
      contracts: { consumes, provides: tool.provides ?? [] },
      satisfied: false,
    })
  }

  if (remaining.length > 0 && remaining.length === prevSize) {
    circular = true
  }

  return {
    steps: ordered,
    gaps: [...gaps],
    circular,
  }
}

export function formatPipelineGaps(gaps: string[], availableTools: string[]): string {
  if (gaps.length === 0) return ""

  return [
    `Missing data signals: [${gaps.join(", ")}]`,
    "Consider running tools that provide these before the current phase.",
  ].join("\n")
}
