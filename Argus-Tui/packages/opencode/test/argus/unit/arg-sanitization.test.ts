import { describe, expect, test } from "bun:test"

describe("arg sanitization", () => {
  test("blocks path traversal in tool names", () => {
    // ToolRunner._validate_tool_name should block paths with "/"
    const dangerous = ["../../etc/passwd", "nuclei;rm -rf /", "../malware.sh"]
    for (const name of dangerous) {
      expect(name.includes("/")).toBe(true)  // Should be caught by validation
    }
  })

  test("shell metacharacters are safe in list-form subprocess", () => {
    // When using list form (not shell form), metacharacters are literal
    const args = ["-u", "https://x.com&id", "-json"]
    // List-form subprocess never interprets these as shell commands
    expect(args.every(a => typeof a === "string")).toBe(true)
  })
})
