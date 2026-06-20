import { describe, expect, test, mock } from "bun:test"
import { FindingAnalyzer } from "../../../src/argus/engagement/finding-analyzer"
import type { FindingAnalysis } from "../../../src/argus/shared/types"

function makeMockStore() {
  const analyses = new Map<string, FindingAnalysis>()
  return {
    getValidAnalysis: (id: string) => analyses.get(id) ?? null,
    saveFindingAnalysis: (a: FindingAnalysis) => { analyses.set(a.findingId, a) },
  }
}

describe("FindingAnalyzer", () => {
  test("returns cached analysis if valid", async () => {
    const store = makeMockStore()
    const cached: FindingAnalysis = {
      findingId: "find-1",
      explanation: "Cached explanation",
      impact: ["impact1"],
      remediation: ["fix1"],
      model: "test",
      generatedAt: Date.now(),
      findingUpdatedAt: Date.now(),
    }
    store.saveFindingAnalysis(cached)
    const analyzer = new FindingAnalyzer(store as any, {} as any)
    const result = await analyzer.analyze({
      id: "find-1", title: "Test", severity: 2, confidence: 2,
      description: "desc", tool: "nuclei", phase: "phase-1",
    }, [])
    expect(result).not.toBeNull()
    expect(result!.explanation).toBe("Cached explanation")
  })

  test("returns null if LLM client missing", async () => {
    const store = makeMockStore()
    const analyzer = new FindingAnalyzer(store as any)
    const result = await analyzer.analyze({
      id: "find-2", title: "Test", severity: 2, confidence: 2,
      description: "desc", tool: "nuclei", phase: "phase-1",
    }, [])
    expect(result).toBeNull()
  })

  test("returns LLM analysis response when client is configured", async () => {
    const store = makeMockStore()
    const mockClient = {
      complete: mock(async () => ({
        text: JSON.stringify({
          explanation: "Real analysis",
          impact: ["impact1"],
          remediation: ["fix1"],
        }),
      })),
    }
    const analyzer = new FindingAnalyzer(store as any, mockClient as any)
    const result = await analyzer.analyze({
      id: "find-3", title: "Test", severity: 2, confidence: 2,
      description: "desc", tool: "nuclei", phase: "phase-1",
      updated_at: new Date().toISOString(),
    }, [])

    expect(result).not.toBeNull()
    expect(typeof result!.explanation).toBe("string")
  })

  test("returns null when llmClient is undefined and no cached analysis", async () => {
    const store = makeMockStore()
    const analyzer = new FindingAnalyzer(store as any)
    const result = await analyzer.analyze({
      id: "find-4", title: "Test", severity: 2, confidence: 2,
      description: "desc", tool: "nuclei", phase: "phase-1",
    }, [])
    expect(result).toBeNull()
  })

  test("getCachedAnalysis delegates to store", async () => {
    const store = makeMockStore()
    const analyzer = new FindingAnalyzer(store as any)
    const result = await analyzer.getCachedAnalysis("nonexistent")
    expect(result).toBeNull()
  })
})
