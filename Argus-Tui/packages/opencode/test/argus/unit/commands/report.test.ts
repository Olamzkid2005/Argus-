import { describe, expect, test, mock, beforeEach } from "bun:test"

const mockGetEngagement = mock(() => ({ id: "eng-1", target: "https://example.com", workflow: [] }))
const mockGetFindings = mock(() => [{ type: "XSS", severity: "HIGH" }])

mock.module("../../../../src/argus/engagement/store", () => ({
  EngagementStore: mock(() => ({
    getEngagement: mockGetEngagement,
    getFindings: mockGetFindings,
  })),
}))

const mockGenerateMarkdown = mock(() => "# Report")
const mockGenerateJSON = mock(() => '{"findings":[]}')
const mockGenerateSARIF = mock(() => '{"version":"2.1.0"}')
const mockGenerateHTML = mock(() => "<html></html>")

mock.module("../../../../src/argus/reporting/generator", () => ({
  ReportGenerator: mock(() => ({
    generateMarkdown: mockGenerateMarkdown,
    generateJSON: mockGenerateJSON,
    generateSARIF: mockGenerateSARIF,
    generateHTML: mockGenerateHTML,
  })),
}))

beforeEach(() => {
  mockGetEngagement.mockClear()
  mockGetFindings.mockClear()
  mockGenerateMarkdown.mockClear()
  mockGenerateJSON.mockClear()
  mockGenerateSARIF.mockClear()
  mockGenerateHTML.mockClear()
  mockGetEngagement.mockImplementation(() => ({ id: "eng-1", target: "https://example.com", workflow: [] }))
})

describe("reportCommand", () => {
  test('returns "Engagement not found" when engagement doesn\'t exist', async () => {
    mockGetEngagement.mockImplementation(() => undefined)
    const { reportCommand } = await import("../../../../src/argus/commands/report")
    const result = await reportCommand("eng-missing")
    expect(result).toBe("Engagement not found: eng-missing")
  })

  test("generates markdown by default", async () => {
    const { reportCommand } = await import("../../../../src/argus/commands/report")
    const result = await reportCommand("eng-1")
    expect(result).toBe("# Report")
    expect(mockGenerateMarkdown).toHaveBeenCalled()
  })

  test('generates JSON when format="json"', async () => {
    const { reportCommand } = await import("../../../../src/argus/commands/report")
    const result = await reportCommand("eng-1", "json")
    expect(result).toBe('{"findings":[]}')
    expect(mockGenerateJSON).toHaveBeenCalled()
  })

  test('generates SARIF when format="sarif"', async () => {
    const { reportCommand } = await import("../../../../src/argus/commands/report")
    const result = await reportCommand("eng-1", "sarif")
    expect(result).toBe('{"version":"2.1.0"}')
    expect(mockGenerateSARIF).toHaveBeenCalled()
  })

  test('generates HTML when format="html"', async () => {
    const { reportCommand } = await import("../../../../src/argus/commands/report")
    const result = await reportCommand("eng-1", "html")
    expect(result).toBe("<html></html>")
    expect(mockGenerateHTML).toHaveBeenCalled()
  })
})
