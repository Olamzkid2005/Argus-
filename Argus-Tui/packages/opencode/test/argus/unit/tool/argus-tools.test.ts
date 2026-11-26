/**
 * Registry-driven native tools: argv parity with the Python builder plus
 * generated-surface sanity.
 *
 * `buildRegistryArgv` must mirror `agent/tool_arguments.build_tool_argv`
 * exactly — the TUI runner and the worker can never disagree about how a
 * tool is invoked. The spec checks pin the generator contract (every native
 * tool addressable by a required target, unique kebab ids).
 */

import { describe, expect, test } from "bun:test"
import { REGISTRY_GENERATED_TOOLS } from "../../../../src/tool/argus-tools.generated"
import { REGISTRY_TOOL_SPECS } from "../../../../src/tool/argus-tools.specs.generated"
import {
  buildRegistryArgv,
  formatRegistryResult,
  runRegistryInvocation,
  type RegistryToolSpec,
} from "../../../../src/tool/argus-tools"

const KATANA_LIKE: RegistryToolSpec = {
  id: "katana",
  toolName: "katana",
  command: "katana",
  args: ["-jsonl", "-silent"],
  params: [
    { name: "target", flag: "-u" },
    { name: "depth", flag: "-d" },
  ],
  timeoutMs: 300_000,
  requiredEnv: [],
  phases: ["recon"],
  risk: "low",
}

describe("buildRegistryArgv", () => {
  test("static args first, then flag/value pairs in declaration order", () => {
    expect(buildRegistryArgv(KATANA_LIKE, { target: "https://t.example", depth: 3 })).toEqual([
      "-jsonl",
      "-silent",
      "-u",
      "https://t.example",
      "-d",
      "3",
    ])
  })

  test("absent optional parameters are not invented", () => {
    expect(buildRegistryArgv(KATANA_LIKE, { target: "https://t.example" })).toEqual([
      "-jsonl",
      "-silent",
      "-u",
      "https://t.example",
    ])
  })

  test("parameters the schema does not declare are ignored", () => {
    expect(
      buildRegistryArgv(KATANA_LIKE, { target: "https://t.example", bogus: "x" }),
    ).toEqual(["-jsonl", "-silent", "-u", "https://t.example"])
  })

  test("true booleans are switches, false booleans vanish", () => {
    const spec: RegistryToolSpec = {
      ...KATANA_LIKE,
      params: [
        { name: "target", flag: null },
        { name: "deep", flag: "--deep" },
      ],
    }
    expect(buildRegistryArgv(spec, { target: "https://t.example", deep: true })).toEqual([
      "-jsonl",
      "-silent",
      "https://t.example",
      "--deep",
    ])
    expect(buildRegistryArgv(spec, { target: "https://t.example", deep: false })).toEqual([
      "-jsonl",
      "-silent",
      "https://t.example",
    ])
  })

  test("flag-less parameters stay positional", () => {
    const spec: RegistryToolSpec = {
      ...KATANA_LIKE,
      params: [{ name: "target", flag: null }],
    }
    expect(buildRegistryArgv(spec, { target: "10.0.0.5" })).toEqual([
      "-jsonl",
      "-silent",
      "10.0.0.5",
    ])
  })

  test("nikto gains -ssl for https targets only", () => {
    const spec: RegistryToolSpec = {
      ...KATANA_LIKE,
      id: "nikto",
      toolName: "nikto",
      command: "nikto",
      args: [],
    }
    expect(buildRegistryArgv(spec, { target: "https://t.example" })).toContain("-ssl")
    expect(buildRegistryArgv(spec, { target: "http://t.example" })).not.toContain("-ssl")
  })
})

describe("runRegistryInvocation", () => {
  test("missing required env fails fast without spawning", () => {
    const spec: RegistryToolSpec = { ...KATANA_LIKE, requiredEnv: ["ARGUS_TEST_MISSING_KEY_XYZ"] }
    const result = runRegistryInvocation(spec, { target: "https://t.example" })
    expect(result.success).toBe(false)
    expect(result.error).toContain("ARGUS_TEST_MISSING_KEY_XYZ")
  })
})

describe("formatRegistryResult", () => {
  test("success passes data through, failure surfaces the error first", () => {
    const ok = formatRegistryResult("katana", {
      success: true,
      data: "out",
      error: "",
      durationMs: 5,
    })
    expect(ok.title).toBe("katana completed")
    expect(ok.output).toBe("out")
    const bad = formatRegistryResult("katana", {
      success: false,
      data: "partial",
      error: "boom",
      durationMs: 5,
    })
    expect(bad.output).toContain("boom")
    expect(bad.output).toContain("partial")
    expect(bad.metadata.success).toBe(false)
  })
})

describe("generated registry surface", () => {
  test("every executable registry tool has a wrapper with a unique id", () => {
    expect(REGISTRY_GENERATED_TOOLS.length).toBeGreaterThan(50)
    const ids = REGISTRY_TOOL_SPECS.map((s) => s.id)
    expect(new Set(ids).size).toBe(ids.length)
    for (const id of ids) expect(id).toMatch(/^[a-z0-9-]+$/)
  })

  test("every wrapper is addressable by a required target parameter", () => {
    for (const spec of REGISTRY_TOOL_SPECS) {
      const target = spec.params.find((p) => p.name === "target")
      expect(target, `${spec.id} declares no target parameter`).toBeDefined()
    }
  })

  test("phases and risk travel with the spec for role eligibility", () => {
    for (const spec of REGISTRY_TOOL_SPECS) {
      expect(spec.phases.length, `${spec.id} has no phase`).toBeGreaterThan(0)
      expect(["low", "medium", "high", "critical"]).toContain(spec.risk)
    }
  })
})
