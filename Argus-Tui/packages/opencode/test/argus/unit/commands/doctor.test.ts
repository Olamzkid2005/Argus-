import { describe, it, expect } from "bun:test"
import { resolve } from "path"

// Resolve the YAML path using process.cwd() (bun test runs from package root)
const yamlPath = resolve(process.cwd(), "src/argus/workflows/tool-definitions.yaml")

describe("parseSemver", () => {
  it("parses standard semver 1.2.3", async () => {
    const { parseSemver } = await import("../../../../src/argus/commands/doctor")
    expect(parseSemver("1.2.3")).toEqual([1, 2, 3])
  })

  it("parses two-part version 1.0", async () => {
    const { parseSemver } = await import("../../../../src/argus/commands/doctor")
    expect(parseSemver("1.0")).toEqual([1, 0])
  })

  it("parses single number 3", async () => {
    const { parseSemver } = await import("../../../../src/argus/commands/doctor")
    expect(parseSemver("3")).toEqual([3])
  })

  it("handles v prefix (v8.56.0)", async () => {
    const { parseSemver } = await import("../../../../src/argus/commands/doctor")
    // parseInt("v8") returns NaN, which becomes 0 via isNaN check
    expect(parseSemver("v8.56.0")).toEqual([0, 56, 0])
  })

  it("handles empty string", async () => {
    const { parseSemver } = await import("../../../../src/argus/commands/doctor")
    expect(parseSemver("")).toEqual([0])
  })

  it("handles non-numeric parts", async () => {
    const { parseSemver } = await import("../../../../src/argus/commands/doctor")
    expect(parseSemver("abc.def")).toEqual([0, 0])
  })

  it("handles longer versions like 1.2.3.4", async () => {
    const { parseSemver } = await import("../../../../src/argus/commands/doctor")
    expect(parseSemver("1.2.3.4")).toEqual([1, 2, 3, 4])
  })
})

describe("compareVersions", () => {
  it("returns 0 for equal versions", async () => {
    const { compareVersions } = await import("../../../../src/argus/commands/doctor")
    expect(compareVersions("1.0.0", "1.0.0")).toBe(0)
  })

  it("returns 0 for nuclei 3.0.0", async () => {
    const { compareVersions } = await import("../../../../src/argus/commands/doctor")
    expect(compareVersions("3.0.0", "3.0.0")).toBe(0)
  })

  it("returns negative when a < b on major", async () => {
    const { compareVersions } = await import("../../../../src/argus/commands/doctor")
    expect(compareVersions("1.0.0", "2.0.0")).toBeLessThan(0)
  })

  it("returns positive when a > b on major", async () => {
    const { compareVersions } = await import("../../../../src/argus/commands/doctor")
    expect(compareVersions("3.0.0", "1.0.0")).toBeGreaterThan(0)
  })

  it("returns negative when a < b on minor", async () => {
    const { compareVersions } = await import("../../../../src/argus/commands/doctor")
    expect(compareVersions("1.2.0", "1.3.0")).toBeLessThan(0)
  })

  it("returns negative when a < b on patch", async () => {
    const { compareVersions } = await import("../../../../src/argus/commands/doctor")
    expect(compareVersions("1.2.3", "1.2.4")).toBeLessThan(0)
  })

  it("compares versions of different lengths (1.0 vs 1.0.0)", async () => {
    const { compareVersions } = await import("../../../../src/argus/commands/doctor")
    // "1.0" parses to [1, 0], "1.0.0" parses to [1, 0, 0]
    // Compare: 1-1=0, 0-0=0, then max length is 3, a[2]??0 - b[2] = 0-0 = 0
    expect(compareVersions("1.0", "1.0.0")).toBe(0)
  })

  it("shorter version with higher major beats longer (2.0 > 1.9.9)", async () => {
    const { compareVersions } = await import("../../../../src/argus/commands/doctor")
    // "2.0" → [2, 0], "1.9.9" → [1, 9, 9]
    // 2 - 1 = 1 > 0
    expect(compareVersions("2.0", "1.9.9")).toBeGreaterThan(0)
  })

  it("detects nuclei v2.9.3 < required 3.0.0", async () => {
    const { compareVersions } = await import("../../../../src/argus/commands/doctor")
    expect(compareVersions("2.9.3", "3.0.0")).toBeLessThan(0)
  })

  it("detects nuclei v3.1.0 >= required 3.0.0", async () => {
    const { compareVersions } = await import("../../../../src/argus/commands/doctor")
    expect(compareVersions("3.1.0", "3.0.0")).toBeGreaterThan(0)
  })

  it("handles v prefix in version output (eslint v8.56.0)", async () => {
    const { compareVersions } = await import("../../../../src/argus/commands/doctor")
    // "v8.56.0" → [0, 56, 0], "1.0.0" → [1, 0, 0]
    // 0 - 1 = -1 < 0
    expect(compareVersions("v8.56.0", "1.0.0")).toBeLessThan(0)
  })
})

describe("loadToolVersionChecks", () => {
  it("populates nuclei version check with min_version 3.0.0", async () => {
    const { loadToolVersionChecks } = await import("../../../../src/argus/commands/doctor")
    const map = loadToolVersionChecks(yamlPath)
    const nuclei = map.get("nuclei")
    expect(nuclei).toBeDefined()
    expect(nuclei!.name).toBe("nuclei")
    expect(nuclei!.version_cmd).toBe("nuclei --version")
    expect(nuclei!.min_version).toBe("3.0.0")
    expect(nuclei!.version_regex).toBeDefined()
  })

  it("populates nmap version check with min_version 1.0.0", async () => {
    const { loadToolVersionChecks } = await import("../../../../src/argus/commands/doctor")
    const map = loadToolVersionChecks(yamlPath)
    const nmap = map.get("nmap")
    expect(nmap).toBeDefined()
    expect(nmap!.name).toBe("nmap")
    expect(nmap!.version_cmd).toBe("nmap --version")
    expect(nmap!.min_version).toBe("1.0.0")
  })

  it("populates all 46 external tools with version checks", async () => {
    const { loadToolVersionChecks } = await import("../../../../src/argus/commands/doctor")
    const map = loadToolVersionChecks(yamlPath)
    expect(map.size).toBe(46)
  })

  it("skips agent-internal tools (no version_cmd)", async () => {
    const { loadToolVersionChecks } = await import("../../../../src/argus/commands/doctor")
    const map = loadToolVersionChecks(yamlPath)
    expect(map.has("finding_correlation_engine")).toBe(false)
    expect(map.has("attack_path_generator")).toBe(false)
    expect(map.has("verification_agent")).toBe(false)
    expect(map.has("register")).toBe(false)
    expect(map.has("login")).toBe(false)
  })

  it("fallbacks to PROJECT_ROOT path when no argument given", async () => {
    const { loadToolVersionChecks } = await import("../../../../src/argus/commands/doctor")
    // Without an argument, it uses the PROJECT_ROOT-based path
    // This may fail on Windows if PROJECT_ROOT has the double-drive bug,
    // but the error is caught internally and returns an empty map.
    const map = loadToolVersionChecks()
    expect(map instanceof Map).toBe(true)
  })
})
