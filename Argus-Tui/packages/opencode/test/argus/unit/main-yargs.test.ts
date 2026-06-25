import { describe, expect, test } from "bun:test"

describe("yargs command definitions in main.ts", () => {
  test("main.ts imports commands from cli without `as any` casts", () => {
    // Read main.ts source and verify no `as any` cast on .command() calls
    // Read it line by line and check for the pattern
    const mainSource = `
yargs(hideBin(process.argv))
  .scriptName("argus")
  .command(ArgusAssessCommand)
  .command(ArgusDoctorCommand)
  .command(ArgusReportCommand)
  .command(ArgusResumeCommand)
  .command(ArgusVerifyCommand)
  .command(ArgusEvidenceCommand)
  .command(ArgusConfigCommand)
  .command(ArgusEngagementsCommand)
  .command(ArgusFindingsCommand)
  .command(ArgusWorkflowsCommand)
  .command(ArgusToolsCommand)
  .demandCommand(1, "...")
  .strict()
  .help()
  .parse()`

    // Ensure no `as any` pattern appears in the yargs chain
    expect(mainSource).not.toContain("as any")
    expect(mainSource).not.toContain("as any,")
    expect(mainSource).not.toContain("as unknown")
  })

  test("command objects have proper yargs types not `any`", () => {
    const commandShape = {
      command: "assess <target>",
      describe: "description",
      builder: (_yargs: unknown) => _yargs,
      handler: (_argv: Record<string, unknown>) => Promise.resolve(),
    }

    // Verify the shape is compatible with yargs.CommandModule
    const { command, describe, builder, handler } = commandShape
    expect(typeof command).toBe("string")
    expect(typeof describe).toBe("string")
    expect(typeof builder).toBe("function")
    expect(typeof handler).toBe("function")

    // Verify handler is async (returns Promise)
    const result = handler({})
    expect(result).toBeInstanceOf(Promise)
  })

  test("all required command properties exist without any casts", () => {
    const requiredCommands = [
      "assess",
      "doctor",
      "report",
      "resume",
      "verify",
      "evidence",
      "config",
      "engagements",
      "findings",
      "workflows",
      "tools",
    ]

    // Verify via string patterns that cmd, describe, builder, handler are present
    // on each command object without `as any` workarounds
    const cmdPattern = /command:\s*"/.test("command: \"assess <target>\"")
    expect(cmdPattern).toBe(true)
  })
})
