import { describe, expect, test } from "bun:test"

describe("verifyCommand", () => {
  test("returns finding-not-found message for non-existent finding", async () => {
    const { verifyCommand } = await import("../../../../src/argus/commands/verify")
    const output = await verifyCommand("find-nonexistent")
    expect(output).toContain("Finding not found")
    expect(output).toContain("find-nonexistent")
  })

  test("handles missing findingId gracefully", async () => {
    const { verifyCommand } = await import("../../../../src/argus/commands/verify")
    const output = await verifyCommand(undefined as unknown as string)
    expect(typeof output).toBe("string")
  })

  test("never throws for arbitrary inputs", async () => {
    const { verifyCommand } = await import("../../../../src/argus/commands/verify")
    const output = await verifyCommand("")
    expect(typeof output).toBe("string")
  })
})
