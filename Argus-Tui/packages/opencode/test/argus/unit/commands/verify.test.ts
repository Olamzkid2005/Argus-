import { describe, expect, test } from "bun:test"

describe("verifyCommand", () => {
  test("returns finding-not-found message for non-existent finding", async () => {
    const { verifyCommand } = await import("../../../../src/argus/commands/verify")
    const output = await verifyCommand("find-nonexistent")
    expect(output).toContain("Finding not found")
  })
})
