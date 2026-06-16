import { describe, expect, test } from "bun:test"
import { resolvePipeline, formatPipelineGaps } from "../../../src/argus/planner/pipeline"

describe("resolvePipeline", () => {
  test("returns empty result for empty tool list", () => {
    const result = resolvePipeline([])
    expect(result.steps).toEqual([])
    expect(result.gaps).toEqual([])
    expect(result.circular).toBe(false)
  })

  test("simple ordering: subfinder before httpx before nuclei", () => {
    const tools = [
      { name: "nuclei", capabilities: ["web_recon"], consumes: ["http_scan"], provides: ["vulnerabilities"] },
      { name: "httpx", capabilities: ["web_recon"], consumes: ["subdomains"], provides: ["http_scan"] },
      { name: "subfinder", capabilities: ["recon"], consumes: ["target"], provides: ["subdomains"] },
    ]
    const result = resolvePipeline(tools, ["target"])
    expect(result.circular).toBe(false)
    expect(result.gaps).toEqual([])
    const names = result.steps.map(s => s.tool)
    expect(names).toEqual(["subfinder", "httpx", "nuclei"])
    expect(result.steps.every(s => s.satisfied)).toBe(true)
  })

  test("gap detection: dalfox with endpoints but no provider", () => {
    const tools = [
      { name: "dalfox", capabilities: ["xss_detection"], consumes: ["endpoints"], provides: ["xss_findings"] },
    ]
    const result = resolvePipeline(tools, ["target"])
    expect(result.gaps).toContain("endpoints")
    expect(result.steps[0].satisfied).toBe(false)
  })

  test("circular dependency detection", () => {
    const tools = [
      { name: "a", capabilities: [], consumes: ["b_data"], provides: ["a_data"] },
      { name: "b", capabilities: [], consumes: ["a_data"], provides: ["b_data"] },
    ]
    const result = resolvePipeline(tools, ["target"])
    expect(result.circular).toBe(true)
  })

  test("initial data satisfaction", () => {
    const tools = [
      { name: "nuclei", capabilities: ["web_recon"], consumes: ["target"], provides: ["vulnerabilities"] },
    ]
    const result = resolvePipeline(tools, ["target"])
    expect(result.steps[0].satisfied).toBe(true)
    expect(result.gaps).toEqual([])
  })

  test("all consumes satisfied with multi-step chain", () => {
    const tools = [
      { name: "c", capabilities: [], consumes: ["b_data"], provides: ["c_data"] },
      { name: "a", capabilities: [], consumes: ["target"], provides: ["a_data"] },
      { name: "b", capabilities: [], consumes: ["a_data"], provides: ["b_data"] },
    ]
    const result = resolvePipeline(tools, ["target"])
    expect(result.circular).toBe(false)
    expect(result.gaps).toEqual([])
    const names = result.steps.map(s => s.tool)
    expect(names).toEqual(["a", "b", "c"])
    expect(result.steps.every(s => s.satisfied)).toBe(true)
  })

  test("no consumes means no dependencies", () => {
    const tools = [
      { name: "nuclei", capabilities: ["web_recon"], provides: ["vulnerabilities"] },
      { name: "dalfox", capabilities: ["xss"], provides: ["xss_findings"] },
    ]
    const result = resolvePipeline(tools, [])
    expect(result.circular).toBe(false)
    expect(result.gaps).toEqual([])
    expect(result.steps).toHaveLength(2)
    expect(result.steps.every(s => s.satisfied)).toBe(true)
  })
})

describe("formatPipelineGaps", () => {
  test("returns empty string when gaps is empty", () => {
    expect(formatPipelineGaps([], ["nuclei"])).toBe("")
  })

  test("returns formatted message when gaps exist", () => {
    const msg = formatPipelineGaps(["endpoints", "credentials"], ["dalfox", "nuclei"])
    expect(msg).toContain("Missing data signals: [endpoints, credentials]")
    expect(msg).toContain("Consider running tools that provide these before the current phase.")
  })
})
