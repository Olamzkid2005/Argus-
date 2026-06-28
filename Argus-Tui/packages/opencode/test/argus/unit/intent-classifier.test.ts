import { describe, expect, test } from "bun:test"
import { classify, detectSlashCommand, SLASH_COMMANDS } from "../../../src/argus/intent-classifier"
import type { ClassifiedIntent } from "../../../src/argus/intent-classifier"

// ── Helpers ──────────────────────────────────────────────────────────

function isSlashCommand(i: ClassifiedIntent): i is { type: "slash_command"; command: string; args: string } {
  return i.type === "slash_command"
}

function isAssessment(i: ClassifiedIntent): i is { type: "assessment"; target: string; useLLM: boolean } {
  return i.type === "assessment"
}

// ── Stage 1: Slash Command Detection ─────────────────────────────────

describe("detectSlashCommand", () => {
  test("recognises /assess with target", () => {
    const result = detectSlashCommand("/assess https://example.com")
    expect(result).toEqual({ type: "slash_command", command: "assess", args: "https://example.com" })
  })

  test("recognises /scan without arguments", () => {
    const result = detectSlashCommand("/scan")
    expect(result).toEqual({ type: "slash_command", command: "scan", args: "" })
  })

  test("recognises /recon with target", () => {
    const result = detectSlashCommand("/recon testphp.vulnweb.com")
    expect(result).toEqual({ type: "slash_command", command: "recon", args: "testphp.vulnweb.com" })
  })

  test("recognises /doctor", () => {
    const result = detectSlashCommand("/doctor")
    expect(result).toEqual({ type: "slash_command", command: "doctor", args: "" })
  })

  test("recognises /status", () => {
    const result = detectSlashCommand("/status")
    expect(result).toEqual({ type: "slash_command", command: "status", args: "" })
  })

  test("returns null for unknown slash command", () => {
    const result = detectSlashCommand("/foobar")
    expect(result).toBeNull()
  })

  test("returns null for text without slash", () => {
    const result = detectSlashCommand("assess example.com")
    expect(result).toBeNull()
  })

  test("handles multi-line input with slash command on first line", () => {
    const result = detectSlashCommand("/assess example.com\nsome extra text")
    expect(result).toEqual({ type: "slash_command", command: "assess", args: "example.com" })
  })

  test("trims leading whitespace before slash detection", () => {
    const result = detectSlashCommand("  /status")
    expect(result).toEqual({ type: "slash_command", command: "status", args: "" })
  })

  test("returns null for bare slash alone", () => {
    const result = detectSlashCommand("/")
    // parts[0] after slice(1) is "", cmd is "" -> not in SLASH_COMMANDS
    expect(result).toBeNull()
  })

  test("case-insensitive command matching", () => {
    const result = detectSlashCommand("/ASSESS example.com")
    expect(result).toEqual({ type: "slash_command", command: "assess", args: "example.com" })
  })
})

// ── Stage 2: NL Passthrough (LLM patterns) ───────────────────────────

describe("classify — LLM passthrough", () => {
  test("greetings go to chat", () => {
    expect(classify("hello")).toEqual({ type: "chat" })
    expect(classify("hi")).toEqual({ type: "chat" })
    expect(classify("hey there")).toEqual({ type: "chat" })
    expect(classify("good morning")).toEqual({ type: "chat" })
  })

  test("help and identity questions go to chat", () => {
    expect(classify("what can you do")).toEqual({ type: "chat" })
    expect(classify("help")).toEqual({ type: "chat" })
    expect(classify("how do you work")).toEqual({ type: "chat" })
    expect(classify("who are you")).toEqual({ type: "chat" })
    expect(classify("what are you")).toEqual({ type: "chat" })
  })

  test("knowledge questions go to chat", () => {
    expect(classify("explain SQL injection")).toEqual({ type: "chat" })
    expect(classify("what is XSS")).toEqual({ type: "chat" })
    expect(classify("how does OAuth work")).toEqual({ type: "chat" })
    expect(classify("describe the architecture")).toEqual({ type: "chat" })
  })

  test("write/code requests go to chat", () => {
    expect(classify("write a python script")).toEqual({ type: "chat" })
    expect(classify("create a REST API")).toEqual({ type: "chat" })
    expect(classify("build a login form")).toEqual({ type: "chat" })
    expect(classify("implement fibonacci in Rust")).toEqual({ type: "chat" })
    expect(classify("code a websocket server")).toEqual({ type: "chat" })
    expect(classify("program a CLI tool")).toEqual({ type: "chat" })
  })

  test("fix/debug requests go to chat", () => {
    expect(classify("fix the login bug")).toEqual({ type: "chat" })
    expect(classify("debug this error")).toEqual({ type: "chat" })
    expect(classify("optimize this query")).toEqual({ type: "chat" })
  })

  test("gratitude and farewells go to chat", () => {
    expect(classify("thanks")).toEqual({ type: "chat" })
    expect(classify("thank you")).toEqual({ type: "chat" })
    expect(classify("bye")).toEqual({ type: "chat" })
    expect(classify("goodbye")).toEqual({ type: "chat" })
  })
})

// ── Stage 2: NL Assessment Detection ─────────────────────────────────

describe("classify — assessment detection (NL)", () => {
  test("'assess <url>' triggers assessment with useLLM=true", () => {
    const result = classify("assess https://example.com")
    expect(isAssessment(result)).toBe(true)
    if (isAssessment(result)) {
      expect(result.target).toBe("https://example.com/")
      expect(result.useLLM).toBe(true)
    }
  })

  test("'scan <url>' triggers assessment with useLLM=false", () => {
    const result = classify("scan https://example.com")
    expect(isAssessment(result)).toBe(true)
    if (isAssessment(result)) {
      expect(result.target).toBe("https://example.com/")
      expect(result.useLLM).toBe(false)
    }
  })

  test("'recon <url>' triggers assessment with useLLM=false", () => {
    const result = classify("recon example.com")
    expect(isAssessment(result)).toBe(true)
    if (isAssessment(result)) {
      expect(result.target).toBe("https://example.com/")
      expect(result.useLLM).toBe(false)
    }
  })

  test("'please run assess <url>' works (useLLM=false because input doesn't start with bare 'assess')", () => {
    const result = classify("please run assess https://example.com")
    expect(isAssessment(result)).toBe(true)
    if (isAssessment(result)) {
      expect(result.target).toBe("https://example.com/")
      // useLLM is only true when input starts with bare "assess " (without prefix)
      expect(result.useLLM).toBe(false)
    }
  })

  test("'find vulnerabilities in <url>' works", () => {
    const result = classify("find vulnerabilities in example.com")
    expect(isAssessment(result)).toBe(true)
    if (isAssessment(result)) {
      expect(result.target).toBe("https://example.com/")
      expect(result.useLLM).toBe(false)
    }
  })

  test("'test <url> for vulnerabilities' works", () => {
    const result = classify("test example.com for vulnerabilities")
    expect(isAssessment(result)).toBe(true)
  })

  test("'check security of <url>' works", () => {
    const result = classify("check security of https://example.com")
    expect(isAssessment(result)).toBe(true)
  })

  test("'run assessment on <url>' works", () => {
    const result = classify("run assessment on example.com")
    expect(isAssessment(result)).toBe(true)
  })

  test("'perform security assessment on <url>' works", () => {
    const result = classify("perform a security assessment on example.com")
    expect(isAssessment(result)).toBe(true)
  })

  test("'what vulnerabilities does <url> have' works", () => {
    const result = classify("what vulnerabilities does example.com have")
    expect(isAssessment(result)).toBe(true)
  })

  test("'is <url> vulnerable' works", () => {
    const result = classify("is example.com vulnerable")
    expect(isAssessment(result)).toBe(true)
  })

  test("'pentest <url>' works", () => {
    const result = classify("pentest https://example.com")
    expect(isAssessment(result)).toBe(true)
  })

  test("'security audit <url>' works", () => {
    const result = classify("security audit example.com")
    expect(isAssessment(result)).toBe(true)
  })

  test("'audit <url>' works", () => {
    const result = classify("audit https://example.com")
    expect(isAssessment(result)).toBe(true)
  })
})

// ── Edge Cases ───────────────────────────────────────────────────────

describe("classify — edge cases", () => {
  test("empty string returns chat", () => {
    expect(classify("")).toEqual({ type: "chat" })
  })

  test("whitespace-only returns chat", () => {
    expect(classify("   ")).toEqual({ type: "chat" })
  })

  test("'scan my code' is routed to chat (no URL target)", () => {
    // "scan my code for bugs" matches ASSESSMENT_PATTERNS but no URL found
    expect(classify("scan my code for bugs")).toEqual({ type: "chat" })
  })

  test("'assess' alone is routed to chat (no target)", () => {
    expect(classify("assess")).toEqual({ type: "chat" })
  })

  test("'scan' alone is routed to chat (no target)", () => {
    expect(classify("scan")).toEqual({ type: "chat" })
  })

  test("slash command takes priority over NL assessment", () => {
    // /assess should be caught by Stage 1 before NL patterns
    const result = classify("/assess example.com")
    expect(isSlashCommand(result)).toBe(true)
    if (isSlashCommand(result)) {
      expect(result.command).toBe("assess")
    }
  })

  test("mixed content without clear intent goes to chat", () => {
    expect(classify("what do you think about security")).toEqual({ type: "chat" })
  })

  test("URL with port number is detected (with dot-separated domain)", () => {
    const result = classify("scan example.com:8080")
    expect(isAssessment(result)).toBe(true)
    if (isAssessment(result)) {
      expect(result.target).toBe("https://example.com:8080/")
    }
  })

  test("bare localhost without dot is not extractable as URL → chat", () => {
    // The domain regex requires at least one dot, so localhost:8080 won't match
    expect(classify("scan localhost:8080")).toEqual({ type: "chat" })
  })

  test("URL with path is detected", () => {
    const result = classify("assess https://example.com/api/v1/users")
    expect(isAssessment(result)).toBe(true)
    if (isAssessment(result)) {
      expect(result.target).toBe("https://example.com/api/v1/users")
    }
  })

  test("subdomain URL is detected", () => {
    const result = classify("recon sub.domain.example.com")
    expect(isAssessment(result)).toBe(true)
    if (isAssessment(result)) {
      expect(result.target).toBe("https://sub.domain.example.com/")
    }
  })

  test("'please assess <url>' works (useLLM=false because input doesn't start with bare 'assess')", () => {
    const result = classify("please assess https://testphp.vulnweb.com")
    expect(isAssessment(result)).toBe(true)
    if (isAssessment(result)) {
      expect(result.target).toBe("https://testphp.vulnweb.com/")
      // useLLM is only true when input starts with bare "assess " (no prefix)
      expect(result.useLLM).toBe(false)
    }
  })

  test("domain with trailing slash", () => {
    const result = classify("scan example.com/")
    expect(isAssessment(result)).toBe(true)
    if (isAssessment(result)) {
      expect(result.target).toBe("https://example.com/")
    }
  })
})

// ── SLASH_COMMANDS set integrity ────────────────────────────────────

describe("SLASH_COMMANDS set", () => {
  test("contains all expected commands", () => {
    const expected = [
      "assess", "scan", "doctor", "health", "recon", "verify",
      "report", "resume", "evidence", "findings", "engagements",
      "tools", "workflows", "config", "status",
    ]
    for (const cmd of expected) {
      expect(SLASH_COMMANDS.has(cmd)).toBe(true)
    }
  })

  test("size matches expected count", () => {
    expect(SLASH_COMMANDS.size).toBe(21)
  })
})
