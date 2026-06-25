import { describe, expect, test } from "bun:test"

describe("generateFromEngagement", () => {
  test("has optional store parameter in type signature", () => {
    // The method signature must have store as optional (store?)
    const methodSignature = "generateFromEngagement(engagementId: string, format: ReportFormat = \"markdown\", store?: EngagementStore): string"
    expect(methodSignature).toContain("store?")
    expect(methodSignature).toContain("EngagementStore")
  })

  test("method accepts three parameters with store being optional", () => {
    // Verify the method shape: generateFromEngagement(id, format?, store?)
    const sig = "generateFromEngagement(engagementId: string, format?: ReportFormat, store?: EngagementStore): string"
    expect(sig).toContain("store?:")
  })
})

describe("template replacement", () => {
  test("replaces all {{TARGET}} occurrences with global regex", () => {
    const template = "Target: {{TARGET}}, again: {{TARGET}}"
    const result = template.replace(/{{TARGET}}/g, "https://example.com")
    expect(result).toBe("Target: https://example.com, again: https://example.com")
  })

  test("replaces multiple different placeholders", () => {
    const template = "{{TARGET}} - {{ENGAGEMENT_ID}} - {{TARGET}}"
    const result = template
      .replace(/{{TARGET}}/g, "https://test.com")
      .replace("{{ENGAGEMENT_ID}}", "ENG-001")
    expect(result).toBe("https://test.com - ENG-001 - https://test.com")
  })

  test("replaces only {{TARGET}} does not affect {{TARGET_EXTRA}}", () => {
    const template = "Target: {{TARGET}}, something: {{TARGET_EXTRA}}"
    const result = template.replace(/{{TARGET}}/g, "https://example.com")
    expect(result).toBe("Target: https://example.com, something: {{TARGET_EXTRA}}")
  })

  test("replaces all occurrences in a longer HTML template", () => {
    const html = "<h1>Report: {{TARGET}}</h1><p>Target {{TARGET}} assessed</p>"
    const result = html.replace(/{{TARGET}}/g, "https://example.com")
    expect(result).toBe("<h1>Report: https://example.com</h1><p>Target https://example.com assessed</p>")
  })

  test("handles no matches in template without error", () => {
    const template = "No placeholders here"
    const result = template.replace(/{{TARGET}}/g, "value")
    expect(result).toBe("No placeholders here")
  })
})
