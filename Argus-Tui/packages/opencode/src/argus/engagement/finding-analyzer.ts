import type { FindingAnalysis } from "../shared/types"
import type { EngagementStore } from "./store"
import { Feature, getFeatureFlags } from "../config/feature-flags"

export interface LlmClient {
  complete(prompt: string, options?: { system?: string; format?: string }): Promise<{ text: string }>
}

export class FindingAnalyzer {
  constructor(
    private store: EngagementStore,
    private llmClient?: LlmClient,
  ) {}

  async analyze(finding: {
    id: string
    title: string
    severity: number
    confidence: number
    description: string
    cwe?: string
    owasp?: string
    tool: string
    phase: string
    updated_at?: string
  }, evidence: Array<{ type: string; path?: string; content?: string }>): Promise<FindingAnalysis | null> {
    const cached = this.store.getValidAnalysis(finding.id)
    if (cached) return cached

    if (!this.llmClient) return null

    if (!getFeatureFlags().isEnabled(Feature.LLM_FINDING_ANALYSIS)) {
      return {
        findingId: finding.id,
        explanation: "LLM analysis disabled. Enable with `features.llm_finding_analysis: true` in config and configure an LLM provider.",
        impact: ["Enable LLM analysis to see impact assessment"],
        remediation: ["Configure an LLM provider in settings", "Set `features.llm_finding_analysis: true` in config"],
        model: "none",
        generatedAt: Date.now(),
        findingUpdatedAt: finding.updated_at ? new Date(finding.updated_at).getTime() : Date.now(),
      }
    }

    const prompt = this.buildAnalysisPrompt(finding, evidence)
    const response = await this.callLLM(prompt)
    const result: FindingAnalysis = {
      findingId: finding.id,
      explanation: response.explanation,
      impact: response.impact,
      remediation: response.remediation,
      references: response.references,
      model: "llm",
      generatedAt: Date.now(),
      findingUpdatedAt: finding.updated_at ? new Date(finding.updated_at).getTime() : Date.now(),
    }

    this.store.saveFindingAnalysis(result)
    return result
  }

  private buildAnalysisPrompt(finding: {
    title: string; severity: number; confidence: number; description: string
    cwe?: string; owasp?: string; tool: string; phase: string
  }, evidence: Array<{ type: string; path?: string; content?: string }>): string {
    const sevLabels = ["INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL"]
    const confLabels = ["INFORMATIONAL", "LOW", "MEDIUM", "HIGH", "VERIFIED", "CONFIRMED"]
    const evidenceStr = evidence.length > 0
      ? evidence.map((e) => `[${e.type}] ${e.path || e.content?.slice(0, 500) || ""}`).join("\n")
      : "No evidence artifacts available."

    return `Analyze this security finding:

Title: ${finding.title}
Severity: ${sevLabels[finding.severity] ?? "UNKNOWN"}
Confidence: ${confLabels[finding.confidence] ?? "UNKNOWN"}
CWE: ${finding.cwe ?? "N/A"}
OWASP: ${finding.owasp ?? "N/A"}
Tool: ${finding.tool}
Phase: ${finding.phase}

Description:
${finding.description}

Evidence:
${evidenceStr}

Provide a JSON response with:
1. explanation — what the vulnerability is and why it exists (2-3 sentences)
2. impact — array of concrete consequences of exploitation (3-5 items)
3. remediation — array of specific, actionable fix steps (3-5 items)
4. references — array of relevant CWE/OWASP/URL references`
  }

  private async callLLM(prompt: string): Promise<{
    explanation: string; impact: string[]; remediation: string[]; references?: string[]
  }> {
    if (!this.llmClient) {
      return {
        explanation: "LLM analysis unavailable. No LLM client configured.",
        impact: ["Configure an LLM provider to see impact assessment"],
        remediation: ["Configure an LLM provider in settings"],
      }
    }

    const response = await this.llmClient.complete(prompt, {
      system: "You are a senior security analyst reviewing findings from automated security tools. Your role is to translate raw tool output into clear, actionable analysis for developers.\n\nRules:\n- NEVER invent findings. Only analyze what the tools reported.\n- Base your analysis on the evidence provided.\n- If evidence is insufficient, say so rather than guessing.\n- Reference the specific CWE/OWASP IDs from the finding.\n- Keep remediation actionable — include code snippets where appropriate.\n- Output valid JSON only.",
      format: "json",
    })

    try {
      return JSON.parse(response.text)
    } catch {
      return {
        explanation: response.text.slice(0, 500),
        impact: ["Unable to parse structured analysis from LLM response"],
        remediation: ["Review the raw LLM output for guidance"],
      }
    }
  }

  async getCachedAnalysis(findingId: string): Promise<FindingAnalysis | null> {
    return this.store.getValidAnalysis(findingId)
  }
}
