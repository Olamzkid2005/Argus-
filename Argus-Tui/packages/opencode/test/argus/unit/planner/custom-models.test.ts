/**
 * Custom cyber-model registry tests (TUI half).
 *
 * Pure parsing/validation plus the opencode.json snippet generator. Filesystem
 * reads go through temp registry files so the tests never depend on what the
 * operator registered in the shipped file.
 */

import { describe, expect, test } from "bun:test"
import { mkdtempSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import {
  listCustomModels,
  opencodeProviderSnippet,
  parseCustomModelsRegistry,
  resolveCustomModel,
} from "../../../../src/argus/planner/custom-models"

function writeRegistry(models: Record<string, unknown>): string {
  const dir = mkdtempSync(join(tmpdir(), "argus-custom-models-"))
  const path = join(dir, "custom_models.json")
  writeFileSync(path, JSON.stringify({ models }))
  return path
}

const LAB = {
  base_url: "http://localhost:11434/v1",
  model: "white-rabbit",
  api_key_env: null,
  description: "local cyber model",
}

describe("parseCustomModelsRegistry", () => {
  test("empty models object parses to []", () => {
    expect(parseCustomModelsRegistry('{"models": {}}')).toEqual([])
  })

  test("entries are sorted by name and URLs trimmed", () => {
    const parsed = parseCustomModelsRegistry(
      JSON.stringify({ models: { zeta: LAB, alpha: { ...LAB, base_url: "https://x.example/v1/" } } }),
    )
    expect(parsed.map((e) => e.name)).toEqual(["alpha", "zeta"])
    expect(parsed[0]!.baseURL).toBe("https://x.example/v1")
  })

  test.each([
    ["not json", "valid JSON"],
    ['{"models": []}', '"models" must be an object'],
    [JSON.stringify({ models: { "a/b": LAB } }), "slash-free"],
    [JSON.stringify({ models: { bad: { ...LAB, base_url: "ftp://x" } } }), "http(s)"],
    [JSON.stringify({ models: { bad: { ...LAB, model: "" } } }), "model id"],
    [JSON.stringify({ models: { bad: { ...LAB, api_key_env: "has-dash" } } }), "env var"],
  ])("rejects %p (%s)", (text, fragment) => {
    expect(() => parseCustomModelsRegistry(text)).toThrow(fragment as string)
  })
})

describe("file reads", () => {
  test("listCustomModels reads a registry file", () => {
    const path = writeRegistry({ lab: LAB })
    expect(listCustomModels(path).map((e) => e.name)).toEqual(["lab"])
  })

  test("resolveCustomModel finds by name and misses unknown", () => {
    const path = writeRegistry({ lab: LAB })
    expect(resolveCustomModel("lab", path)?.model).toBe("white-rabbit")
    expect(resolveCustomModel("nope", path)).toBeUndefined()
  })
})

describe("opencodeProviderSnippet", () => {
  test("renders a paste-ready provider block namespaced under argus-", () => {
    const path = writeRegistry({ lab: { ...LAB, api_key_env: "CYBER_KEY" } })
    const snippet = opencodeProviderSnippet(resolveCustomModel("lab", path)!)
    const parsed = JSON.parse(snippet)
    const provider = parsed.provider["argus-lab"]
    // The AI SDK appends /chat/completions itself; the block must be the root.
    expect(provider.options.baseURL).toBe("http://localhost:11434/v1")
    expect(provider.options.apiKey).toBe("{env:CYBER_KEY}")
    expect(provider.models["white-rabbit"]).toBeDefined()
  })

  test("strips a /chat/completions suffix instead of doubling it", () => {
    const path = writeRegistry({ lab: { ...LAB, base_url: "http://localhost:11434/v1/chat/completions" } })
    const snippet = opencodeProviderSnippet(resolveCustomModel("lab", path)!)
    expect(JSON.parse(snippet).provider["argus-lab"].options.baseURL).toBe("http://localhost:11434/v1")
  })

  test("keyless endpoints get a placeholder key", () => {
    const path = writeRegistry({ lab: LAB })
    const snippet = opencodeProviderSnippet(resolveCustomModel("lab", path)!)
    expect(JSON.parse(snippet).provider["argus-lab"].options.apiKey).toBe("not-needed")
  })
})
