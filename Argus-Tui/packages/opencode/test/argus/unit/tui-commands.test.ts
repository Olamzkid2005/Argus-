import { describe, it, expect } from "bun:test"

describe("tui-commands", () => {
  it("getArgusTuiCommands() returns array of all commands", async () => {
    const { getArgusTuiCommands } = await import("../../../src/argus/tui-commands")
    const cmds = getArgusTuiCommands()
    expect(Array.isArray(cmds)).toBe(true)
    expect(cmds.length).toBeGreaterThan(0)
    const names = cmds.map((c: any) => c.name)
    expect(names).toContain("assess")
    expect(names).toContain("doctor")
    expect(names).toContain("recon")
    expect(names).toContain("status")
    expect(names).toContain("findings")
    expect(names).toContain("engagements")
    expect(names).toContain("help")
  })

  it("findArgusTuiCommand() finds by slash alias", async () => {
    const { findArgusTuiCommand } = await import("../../../src/argus/tui-commands")
    const cmd = findArgusTuiCommand("scan")
    expect(cmd).toBeDefined()
    expect(cmd!.name).toBe("assess")
  })

  it("findArgusTuiCommand() finds by name", async () => {
    const { findArgusTuiCommand } = await import("../../../src/argus/tui-commands")
    const cmd = findArgusTuiCommand("doctor")
    expect(cmd).toBeDefined()
    expect(cmd!.name).toBe("doctor")
  })

  it("findArgusTuiCommand() returns undefined for unknown command", async () => {
    const { findArgusTuiCommand } = await import("../../../src/argus/tui-commands")
    const cmd = findArgusTuiCommand("nonexistent")
    expect(cmd).toBeUndefined()
  })

  it("formatCliHelp() formats help text", async () => {
    const { formatCliHelp } = await import("../../../src/argus/tui-commands")
    const help = formatCliHelp()
    expect(help).toContain("Commands:")
    expect(help).toContain("/assess")
    expect(help).toContain("/doctor")
    expect(help).not.toContain("/help")
  })

  // --- Slash alias tests (Fix 2: each alias gets its own palette entry) ---

  it("all commands have at least one slash alias", async () => {
    const { getArgusTuiCommands } = await import("../../../src/argus/tui-commands")
    const cmds = getArgusTuiCommands()
    for (const cmd of cmds) {
      expect(
        cmd.slashes.length,
        `Command "${cmd.name}" has no slash aliases`
      ).toBeGreaterThanOrEqual(1)
    }
  })

  it('/assess has slashes ["assess", "scan"] so both /assess and /scan work', async () => {
    const { getArgusTuiCommands } = await import("../../../src/argus/tui-commands")
    const assess = getArgusTuiCommands().find((c) => c.name === "assess")
    expect(assess).toBeDefined()
    expect(assess!.slashes).toContain("assess")
    expect(assess!.slashes).toContain("scan")
  })

  it('/doctor has slashes ["doctor", "health"]', async () => {
    const { getArgusTuiCommands } = await import("../../../src/argus/tui-commands")
    const doctor = getArgusTuiCommands().find((c) => c.name === "doctor")
    expect(doctor).toBeDefined()
    expect(doctor!.slashes).toContain("doctor")
    expect(doctor!.slashes).toContain("health")
  })

  it('/help has slashes ["help", "?"]', async () => {
    const { getArgusTuiCommands } = await import("../../../src/argus/tui-commands")
    const help = getArgusTuiCommands().find((c) => c.name === "help")
    expect(help).toBeDefined()
    expect(help!.slashes).toContain("help")
    expect(help!.slashes).toContain("?")
  })

  it("each command's primary name is the first slash (for backwards compatibility)", async () => {
    const { getArgusTuiCommands } = await import("../../../src/argus/tui-commands")
    const cmds = getArgusTuiCommands()
    for (const cmd of cmds) {
      expect(cmd.slashes[0], `Command "${cmd.name}" primary slash mismatch`).toBe(cmd.name)
    }
  })

  // --- Tools cache tests (Fix 4: module-level _cachedTools avoids re-spawning worker) ---

  it("/tools command is registered with correct description", async () => {
    const { getArgusTuiCommands } = await import("../../../src/argus/tui-commands")
    const tools = getArgusTuiCommands().find((c) => c.name === "tools")
    expect(tools).toBeDefined()
    expect(tools!.description).toContain("MCP tools")
    expect(tools!.needsTarget).toBe(false)
  })

  it("/tools cache starts empty after reset", async () => {
    const { getToolsCache, resetToolsCache } = await import("../../../src/argus/tui-commands")
    resetToolsCache()
    expect(getToolsCache()).toEqual([])
  })

  it("/tools handler returns cached data without spawning a worker when cache is primed", async () => {
    const mod = await import("../../../src/argus/tui-commands")
    const { findArgusTuiCommand, resetToolsCache, getToolsCache, setToolsCache } = mod
    const cmd = findArgusTuiCommand("tools")!

    // Prime the cache with test data — avoids spawning a real Python worker
    const mockTools = [
      { name: "nuclei", capabilities: ["scan", "vuln"], signal_quality: "high" },
      { name: "http-scanner", capabilities: ["web"], signal_quality: "medium" },
    ]
    setToolsCache(mockTools)
    expect(getToolsCache()).toHaveLength(2)

    // Handler should return cached data without attempting to spawn a worker
    const result = await cmd.handler("")
    expect(result).toContain("nuclei")
    expect(result).toContain("http-scanner")
    expect(result).toContain("scan, vuln")
    expect(result).toContain("web")
    expect(result).toContain("[high]")
    expect(result).toContain("[medium]")
  })

  it("/tools handler falls through to worker path when cache is empty", async () => {
    const { findArgusTuiCommand, resetToolsCache, getToolsCache } = await import("../../../src/argus/tui-commands")
    const cmd = findArgusTuiCommand("tools")!

    // Empty cache — handler will attempt to spawn a worker
    resetToolsCache()
    expect(getToolsCache()).toEqual([])

    // MCP worker path doesn't exist in test env, so returns "not found"
    const result = await cmd.handler("")
    expect(result).toContain("not found")
    // Cache stays empty since no tools were fetched
    expect(getToolsCache()).toEqual([])
  })

  // --- Verify handler tests (Fix 5: empty finding ID validation + delegates to verifyCommand) ---

  it("/verify with empty args returns usage message", async () => {
    const { findArgusTuiCommand } = await import("../../../src/argus/tui-commands")
    const cmd = findArgusTuiCommand("verify")!
    const result = await cmd.handler("")
    expect(result).toContain("Usage:")
  })

  it("/verify with whitespace-only args returns usage message", async () => {
    const { findArgusTuiCommand } = await import("../../../src/argus/tui-commands")
    const cmd = findArgusTuiCommand("verify")!
    const result = await cmd.handler("   ")
    expect(result).toContain("Usage:")
  })

  it("/verify with a finding ID returns a string (delegates to verifyCommand)", async () => {
    const { findArgusTuiCommand } = await import("../../../src/argus/tui-commands")
    const cmd = findArgusTuiCommand("verify")!
    // verifyCommand with a nonexistent finding ID should return an error string, not throw
    const result = await cmd.handler("FIND-999999")
    expect(typeof result).toBe("string")
  })

  describe("findings command handler", () => {
    it("returns engagement-oriented output", async () => {
      const { findArgusTuiCommand } = await import("../../../src/argus/tui-commands")
      const cmd = findArgusTuiCommand("findings")!
      const result = await cmd.handler("")
      expect(typeof result).toBe("string")
    })
  })

  describe("engagements command handler", () => {
    it("lists engagements", async () => {
      const { findArgusTuiCommand } = await import("../../../src/argus/tui-commands")
      const cmd = findArgusTuiCommand("engagements")!
      const result = await cmd.handler("")
      expect(typeof result).toBe("string")
    })
  })

  describe("help command handler", () => {
    it("returns formatted help with all commands", async () => {
      const { findArgusTuiCommand } = await import("../../../src/argus/tui-commands")
      const cmd = findArgusTuiCommand("help")!
      const result = await cmd.handler("")
      expect(result).toContain("Argus Commands")
      expect(result).toContain("/assess")
      expect(result).toContain("/doctor")
      expect(result).toContain("/recon")
      expect(result).toContain("/status")
      expect(result).toContain("/findings")
      expect(result).toContain("/engagements")
      expect(result).toContain("/tools")
      expect(result).toContain("/workflows")
      expect(result).toContain("/config")
    })
  })
})
