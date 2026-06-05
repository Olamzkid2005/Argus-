import { describe, it, expect, mock, afterEach } from "bun:test"

const assessMock = mock()
const doctorMock = mock()

mock.module("../../../src/argus/commands/assess", () => ({
  assessCommand: assessMock,
}))

mock.module("../../../src/argus/commands/doctor", () => ({
  doctorCommand: doctorMock,
}))

const engagementStoreListMock = mock(() => [])
const engagementStoreGetFindingsMock = mock(() => [])

mock.module("../../../src/argus/engagement/store", () => ({
  EngagementStore: mock(() => ({
    listEngagements: engagementStoreListMock,
    getFindings: engagementStoreGetFindingsMock,
  })),
}))

const {
  getArgusTuiCommands,
  findArgusTuiCommand,
  formatCliHelp,
} = await import("../../../src/argus/tui-commands")

describe("tui-commands", () => {
  afterEach(() => {
    assessMock.mockReset()
    doctorMock.mockReset()
  })

  it("getArgusTuiCommands() returns array of all commands", () => {
    const cmds = getArgusTuiCommands()
    expect(Array.isArray(cmds)).toBe(true)
    expect(cmds.length).toBeGreaterThan(0)
    const names = cmds.map((c) => c.name)
    expect(names).toContain("assess")
    expect(names).toContain("doctor")
    expect(names).toContain("recon")
    expect(names).toContain("status")
    expect(names).toContain("findings")
    expect(names).toContain("engagements")
    expect(names).toContain("help")
  })

  it("findArgusTuiCommand() finds by slash alias", () => {
    const cmd = findArgusTuiCommand("scan")
    expect(cmd).toBeDefined()
    expect(cmd!.name).toBe("assess")
  })

  it("findArgusTuiCommand() finds by name", () => {
    const cmd = findArgusTuiCommand("doctor")
    expect(cmd).toBeDefined()
    expect(cmd!.name).toBe("doctor")
  })

  it("findArgusTuiCommand() returns undefined for unknown command", () => {
    const cmd = findArgusTuiCommand("nonexistent")
    expect(cmd).toBeUndefined()
  })

  it("formatCliHelp() formats help text", () => {
    const help = formatCliHelp()
    expect(help).toContain("Commands:")
    expect(help).toContain("/assess")
    expect(help).toContain("/doctor")
    expect(help).not.toContain("/help")
  })

  describe("assess command handler", () => {
    it("calls assessCommand and returns message", async () => {
      assessMock.mockResolvedValue(undefined)
      const cmd = findArgusTuiCommand("assess")!
      const result = await cmd.handler("https://test.com")
      expect(assessMock).toHaveBeenCalledWith("https://test.com", { useLLM: true })
      expect(result).toBe("Assessment completed against https://test.com")
    })
  })

  describe("doctor command handler", () => {
    it("calls doctorCommand and formats results", async () => {
      doctorMock.mockResolvedValue([
        { name: "Runtime", status: "PASS", message: "Node.js v20" },
        { name: "Database", status: "PASS", message: "SQLite ready" },
        { name: "Python Runtime", status: "FAIL", message: "No Python" },
      ])
      const cmd = findArgusTuiCommand("doctor")!
      const result = await cmd.handler("")
      expect(doctorMock).toHaveBeenCalled()
      expect(result).toContain("[Runtime]")
      expect(result).toContain("[Database]")
      expect(result).toContain("[Python Runtime]")
      expect(result).toContain("2 passed")
      expect(result).toContain("0 warnings")
      expect(result).toContain("1 failed")
    })
  })

  describe("recon command handler", () => {
    it("calls assessCommand with useLLM=false", async () => {
      assessMock.mockResolvedValue(undefined)
      const cmd = findArgusTuiCommand("recon")!
      const result = await cmd.handler("https://test.com")
      expect(assessMock).toHaveBeenCalledWith("https://test.com", { useLLM: false })
      expect(result).toBe("Recon completed against https://test.com")
    })
  })

  describe("status command handler", () => {
    it("formats status from doctor results", async () => {
      doctorMock.mockResolvedValue([
        { name: "MCP Worker", status: "PASS", message: "Connected" },
        { name: "Toolchain", status: "PASS", message: "5 tools found" },
        { name: "Database", status: "PASS", message: "SQLite ready" },
      ])
      const cmd = findArgusTuiCommand("status")!
      const result = await cmd.handler("")
      expect(result).toContain("ARGUS System Status")
      expect(result).toContain("Connected")
      expect(result).toContain("5 tools found")
      expect(result).toContain("SQLite ready")
    })
  })

  describe("findings command handler", () => {
    it("returns No engagements found when empty", async () => {
      const cmd = findArgusTuiCommand("findings")!
      const result = await cmd.handler("")
      expect(result).toBe("No engagements found.")
    })
  })

  describe("engagements command handler", () => {
    it("lists engagements", async () => {
      const cmd = findArgusTuiCommand("engagements")!
      const result = await cmd.handler("")
      expect(result).toBe("No engagements found.")
    })
  })

  describe("help command handler", () => {
    it("returns formatted help with all commands", async () => {
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
