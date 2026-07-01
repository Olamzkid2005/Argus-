import type { FindingAnalysis } from "../shared/types"
import type { IEngagementStore } from "./types"
import { Feature, getFeatureFlags } from "../config/feature-flags"

export interface LlmClient {
  complete(prompt: string, options?: { system?: string; format?: string }): Promise<{ text: string }>
}

export class FindingAnalyzer {
  constructor(
    private store: IEngagementStore,
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

  /**
   * Redact credentials, secrets, tokens, and other sensitive data from text
   * before it enters LLM context. Prevents exfiltration of passwords, API keys,
   * session tokens, cookies, JWTs, private keys, and database connection strings
   * recovered during scanning to third-party LLM providers.
   */
  private _redactSecrets(text: string): string {
    // Redact Authorization headers (Bearer and Basic)
    text = text.replace(
      /(Authorization|Proxy-Authorization)\s*:\s*Bearer\s+\S+/gi,
      "$1: Bearer __REDACTED__"
    )
    text = text.replace(
      /(Authorization|Proxy-Authorization)\s*:\s*Basic\s+\S+/gi,
      "$1: Basic __REDACTED__"
    )
    // Redact Cookie / Set-Cookie headers
    text = text.replace(
      /(Set-Cookie|Cookie)\s*:\s*[^\r\n]+/gi,
      "$1: __REDACTED__"
    )
    // Redact JWT tokens (eyJ... base64url format)
    text = text.replace(
      /eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+/g,
      "__REDACTED_JWT__"
    )
    text = text.replace(
      /eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+/g,
      "__REDACTED_JWT__"
    )
    // Redact API keys (sk-... OpenAI, sk-ant-... Anthropic, AIza... Gemini)
    text = text.replace(
      /sk-[A-Za-z0-9]{20,}/gi,
      "__REDACTED_API_KEY__"
    )
    text = text.replace(
      /sk-proj-[A-Za-z0-9_-]{20,}/gi,
      "__REDACTED_API_KEY__"
    )
    text = text.replace(
      /AIza[0-9A-Za-z_-]{35}/g,
      "__REDACTED_API_KEY__"
    )
    // Redact AWS access keys
    text = text.replace(
      /AKIA[0-9A-Z]{16}/g,
      "__REDACTED_AWS_KEY__"
    )
    // Redact GitHub tokens
    text = text.replace(
      /gh[psuor]_[A-Za-z0-9]{36}/g,
      "__REDACTED_GITHUB_TOKEN__"
    )
    // Redact common credential patterns: password=, secret=, api_key=, token=
    text = text.replace(
      /(?i)(password|passwd|pwd)\s*[:=]\s*["']?[^\s"'&,;){]+["']?/g,
      "$1=__REDACTED__"
    )
    text = text.replace(
      /(?i)(secret|api[_-]?key|api[_-]?token|access[_-]?token)\s*[:=]\s*["']?[^\s"'&,;){]+["']?/g,
      "$1=__REDACTED__"
    )
    // Redact private keys (RSA, EC, OPENSSH, PGP)
    text = text.replace(
      /-----BEGIN\s+(RSA\s+)?PRIVATE\s+KEY-----.[\s\S]*?-----END\s+(RSA\s+)?PRIVATE\s+KEY-----/gi,
      "__REDACTED_PRIVATE_KEY__"
    )
    text = text.replace(
      /-----BEGIN\s+OPENSSH\s+PRIVATE\s+KEY-----.[\s\S]*?-----END\s+OPENSSH\s+PRIVATE\s+KEY-----/gi,
      "__REDACTED_PRIVATE_KEY__"
    )
    // Redact database connection strings with embedded credentials
    text = text.replace(
      /(postgresql|postgres|mysql|mongodb|mongodb\+srv|redis|rediss):\/\/[^\s@]+@/gi,
      "$1://__REDACTED_CREDS__@"
    )
    // Redact URL-embedded credentials (http://user:pass@host)
    text = text.replace(
      /https?:\/\/[^\s/:]+:[^\s@]+@/gi,
      "https://__REDACTED_CREDS__@"
    )
    return text
  }

  private buildAnalysisPrompt(finding: {
    title: string; severity: number; confidence: number; description: string
    cwe?: string; owasp?: string; tool: string; phase: string
  }, evidence: Array<{ type: string; path?: string; content?: string }>): string {
    const sevLabels = ["INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL"]
    const confLabels = ["INFORMATIONAL", "LOW", "MEDIUM", "HIGH", "VERIFIED", "CONFIRMED"]
    const evidenceStr = evidence.length > 0
      ? evidence.map((e) => `[${e.type}] ${e.path || this._redactSecrets(e.content?.slice(0, 500) || "")}`).join("\n")
      : "No evidence artifacts available."

    // Redact secrets from the finding description and evidence before sending to LLM
    const redactedDescription = this._redactSecrets(finding.description)
    const redactedTitle = this._redactSecrets(finding.title)

    return `Analyze this security finding:

Title: ${redactedTitle}
Severity: ${sevLabels[finding.severity] ?? "UNKNOWN"}
Confidence: ${confLabels[finding.confidence] ?? "UNKNOWN"}
CWE: ${finding.cwe ?? "N/A"}
OWASP: ${finding.owasp ?? "N/A"}
Tool: ${finding.tool}
Phase: ${finding.phase}

Description:
${redactedDescription}

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
      const parsed = JSON.parse(response.text)
      // Field-level schema validation: each field is validated independently so a
      // single bad field doesn't discard the entire LLM response.
      const explanation = typeof parsed?.explanation === "string" && parsed.explanation.length > 0
        ? parsed.explanation
        : response.text.slice(0, 500)
      const impact = Array.isArray(parsed?.impact) && parsed.impact.length > 0
        ? parsed.impact.filter((i: unknown) => typeof i === "string")
        : ["LLM returned malformed impact assessment"]
      const remediation = Array.isArray(parsed?.remediation) && parsed.remediation.length > 0
        ? parsed.remediation.filter((r: unknown) => typeof r === "string")
        : ["Review raw LLM output for remediation guidance"]
      const references = Array.isArray(parsed?.references)
        ? parsed.references.filter((r: unknown) => typeof r === "string")
        : undefined
      return { explanation, impact, remediation, references }
    } catch {
      return {
        explanation: response.text.slice(0, 500),
        impact: ["Unable to parse structured analysis from LLM response"],
        remediation: ["Review the raw LLM output for guidance"],
      }
    }
  }

  hasLlmClient(): boolean {
    return this.llmClient !== undefined
  }

  async getCachedAnalysis(findingId: string): Promise<FindingAnalysis | null> {
    return this.store.getValidAnalysis(findingId)
  }
}
