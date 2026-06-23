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
