import { describe, expect, test, mock, beforeEach } from "bun:test"

const mockAssessCommand = mock(() => Promise.resolve())
const mockDoctorCommand = mock(() => Promise.resolve([]))
const mockReportCommand = mock(() => Promise.resolve(""))
const mockResumeCommand = mock(() => Promise.resolve("resumed"))
const mockVerifyCommand = mock(() => Promise.resolve("verified"))
const mockEvidenceCommand = mock(() => Promise.resolve("evidence done"))
const mockConfigCommand = mock(() => Promise.resolve("config output"))

mock.module("../../../src/argus/commands/assess", () => ({ assessCommand: mockAssessCommand }))
mock.module("../../../src/argus/commands/doctor", () => ({ doctorCommand: mockDoctorCommand }))
mock.module("../../../src/argus/commands/report", () => ({ reportCommand: mockReportCommand }))
mock.module("../../../src/argus/commands/resume", () => ({ resumeCommand: mockResumeCommand }))
mock.module("../../../src/argus/commands/verify", () => ({ verifyCommand: mockVerifyCommand }))
mock.module("../../../src/argus/commands/evidence", () => ({ evidenceCommand: mockEvidenceCommand }))
mock.module("../../../src/argus/commands/config", () => ({ configCommand: mockConfigCommand }))

beforeEach(() => {
  mockAssessCommand.mockClear()
  mockDoctorCommand.mockClear()
  mockReportCommand.mockClear()
  mockResumeCommand.mockClear()
  mockVerifyCommand.mockClear()
  mockEvidenceCommand.mockClear()
  mockConfigCommand.mockClear()
})

describe("ArgusAssessCommand", () => {
  test('command is "assess <target>"', async () => {
    const { ArgusAssessCommand } = await import("../../../src/argus/cli")
    expect(ArgusAssessCommand.command).toBe("assess <target>")
  })

  test("handler calls assessCommand with correct args", async () => {
    const { ArgusAssessCommand } = await import("../../../src/argus/cli")
    await ArgusAssessCommand.handler({
      target: "https://example.com",
      deterministic: false,
    })
    expect(mockAssessCommand).toHaveBeenCalledWith("https://example.com", {
      useLLM: true,
      credsPath: undefined,
      features: {},
    })
  })

  test("handler maps CLI feature flags to Feature enum", async () => {
    const { ArgusAssessCommand } = await import("../../../src/argus/cli")
    await ArgusAssessCommand.handler({
      target: "https://example.com",
      "enable-browser": true,
      "enable-workflow-registry": false,
      "enable-engagement-store": true,
      "enable-approval-gates": false,
    })
    expect(mockAssessCommand).toHaveBeenCalledWith("https://example.com", {
      useLLM: true,
      credsPath: undefined,
      features: {
        browser_verification: true,
        workflow_registry: false,
        engagement_store: true,
        approval_gates: false,
      },
    })
  })

  test("handler catches errors", async () => {
    mockAssessCommand.mockRejectedValue(new Error("something broke"))
    const { ArgusAssessCommand } = await import("../../../src/argus/cli")
    const spy = mock(() => {})
    const orig = process.stderr.write
    process.stderr.write = spy
    try {
      await ArgusAssessCommand.handler({ target: "https://example.com" })
      expect(spy).toHaveBeenCalledWith("[Argus] assess error: something broke\n")
    } finally {
      process.stderr.write = orig
    }
  })
})

describe("ArgusDoctorCommand", () => {
  test('command is "doctor"', async () => {
    const { ArgusDoctorCommand } = await import("../../../src/argus/cli")
    expect(ArgusDoctorCommand.command).toBe("doctor")
  })

  test("handler calls doctorCommand", async () => {
    mockDoctorCommand.mockResolvedValue([])
    const { ArgusDoctorCommand } = await import("../../../src/argus/cli")
    await ArgusDoctorCommand.handler({ online: true })
    expect(mockDoctorCommand).toHaveBeenCalledWith({ online: true })
  })

  test("handler counts pass/warn/fail", async () => {
    mockDoctorCommand.mockResolvedValue([
      { name: "Network", status: "PASS", message: "Connected" },
      { name: "Config", status: "WARN", message: "Missing key" },
      { name: "Deps", status: "FAIL", message: "Not found" },
    ])
    const { ArgusDoctorCommand } = await import("../../../src/argus/cli")
    const spy = mock(() => {})
    const orig = process.stdout.write
    process.stdout.write = spy
    const origExitCode = process.exitCode
    process.exitCode = 0
    try {
      await ArgusDoctorCommand.handler({ online: false })
      expect(spy).toHaveBeenCalledWith("\n1 passed, 1 warnings, 1 failed\n")
      expect(process.exitCode).toBe(1)
    } finally {
      process.stdout.write = orig
      process.exitCode = origExitCode
    }
  })
})

describe("ArgusReportCommand", () => {
  test('command is "report <engagement-id>"', async () => {
    const { ArgusReportCommand } = await import("../../../src/argus/cli")
    expect(ArgusReportCommand.command).toBe("report <engagement-id>")
  })

  test("handler calls reportCommand with format", async () => {
    const { ArgusReportCommand } = await import("../../../src/argus/cli")
    await ArgusReportCommand.handler({ engagementId: "eng-123", format: "json" })
    expect(mockReportCommand).toHaveBeenCalledWith("eng-123", "json")
  })
})

describe("ArgusResumeCommand", () => {
  test("handler calls resumeCommand", async () => {
    const { ArgusResumeCommand } = await import("../../../src/argus/cli")
    await ArgusResumeCommand.handler({ engagementId: "eng-1" })
    expect(mockResumeCommand).toHaveBeenCalledWith("eng-1")
  })
})

describe("ArgusVerifyCommand", () => {
  test("handler calls verifyCommand", async () => {
    const { ArgusVerifyCommand } = await import("../../../src/argus/cli")
    await ArgusVerifyCommand.handler({
      findingId: "find-1",
      target: "https://example.com",
      creds: "/path/creds.json",
    })
    expect(mockVerifyCommand).toHaveBeenCalledWith("find-1", {
      targetUrl: "https://example.com",
      credsPath: "/path/creds.json",
    })
  })
})

describe("ArgusEvidenceCommand", () => {
  test("handler calls evidenceCommand with action", async () => {
    const { ArgusEvidenceCommand } = await import("../../../src/argus/cli")
    await ArgusEvidenceCommand.handler({ action: "list", args: [] })
    expect(mockEvidenceCommand).toHaveBeenCalledWith("list", [])
  })
})

describe("ArgusConfigCommand", () => {
  test("handler calls configCommand with filter", async () => {
    const { ArgusConfigCommand } = await import("../../../src/argus/cli")
    await ArgusConfigCommand.handler({ filter: "db" })
    expect(mockConfigCommand).toHaveBeenCalledWith("db")
  })
})
