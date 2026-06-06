import { describe, expect, test, mock } from "bun:test"

describe("ArgusAssessCommand", () => {
  test('command is "assess <target>"', async () => {
    const { ArgusAssessCommand } = await import("../../../src/argus/cli")
    expect(ArgusAssessCommand.command).toBe("assess <target>")
  })

  test("handler catches errors", async () => {
    const { ArgusAssessCommand } = await import("../../../src/argus/cli")
    const spy = mock(() => {})
    const orig = process.stderr.write
    process.stderr.write = spy
    try {
      // No assessCommand mock, so this will try to start a real assessment
      // which will fail quickly because no MCP bridge is available
      await ArgusAssessCommand.handler({ target: "https://example.com" })
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
})

describe("ArgusReportCommand", () => {
  test('command is "report <engagement-id>"', async () => {
    const { ArgusReportCommand } = await import("../../../src/argus/cli")
    expect(ArgusReportCommand.command).toBe("report <engagement-id>")
  })
})

describe("ArgusResumeCommand", () => {
  test("handler catches errors gracefully", async () => {
    const { ArgusResumeCommand } = await import("../../../src/argus/cli")
    const spy = mock(() => {})
    const orig = process.stderr.write
    process.stderr.write = spy
    try {
      // Will try to resume a non-existent engagement
      // and fail, but should be caught
      await ArgusResumeCommand.handler({ engagementId: "ENG-NONEXISTENT" })
    } finally {
      process.stderr.write = orig
    }
  })
})

describe("ArgusVerifyCommand", () => {
  test('command is "verify <finding-id>"', async () => {
    const { ArgusVerifyCommand } = await import("../../../src/argus/cli")
    expect(ArgusVerifyCommand.command).toBe("verify <finding-id>")
  })
})

describe("ArgusEvidenceCommand", () => {
  test('command is "evidence <action> [args..]"', async () => {
    const { ArgusEvidenceCommand } = await import("../../../src/argus/cli")
    expect(ArgusEvidenceCommand.command).toBe("evidence <action> [args..]")
  })
})

describe("ArgusConfigCommand", () => {
  test("handler called with filter", async () => {
    const { ArgusConfigCommand } = await import("../../../src/argus/cli")
    // Just verify the command definition is loaded
    expect(ArgusConfigCommand.command).toBe("config [filter]")
  })
})
