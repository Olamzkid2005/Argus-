/**
 * LlmClient — Concrete implementation of the LlmClient interface.
 *
 * Reads API keys and provider configuration from environment variables,
 * auto-detects the provider from key prefix, and makes HTTP calls to
 * the appropriate chat completion endpoint.
 *
 * Environment variables:
 *   LLM_API_KEY | OPENAI_API_KEY | ANTHROPIC_API_KEY — API key
 *   LLM_API_URL — Base URL override (defaults to OpenAI or provider default)
 *   LLM_MODEL      — Model name (defaults to "gpt-4o-mini")
 *   LLM_TIMEOUT_MS — Request timeout in milliseconds (defaults to 30000)
 *
 * Provider auto-detection from key prefix:
 *   sk-or- → OpenRouter (https://openrouter.ai/api/v1/chat/completions)
 *   AIzaSy | AQ. → Google Gemini (generativelanguage.googleapis.com)
 *   sk-anthropic → Anthropic (api.anthropic.com)
 *   sk- → OpenAI (api.openai.com)
 */

import type { LlmClient } from "./finding-analyzer"

interface ChatCompletionResponse {
  choices?: Array<{ message: { content: string } }>
  content?: string
}

export class LlmClientImpl implements LlmClient {
  private apiKey: string
  private apiUrl: string
  private model: string
  private provider: string
  private timeoutMs: number

  constructor() {
    this.apiKey = process.env.LLM_API_KEY
      ?? process.env.OPENAI_API_KEY
      ?? process.env.ANTHROPIC_API_KEY
      ?? ""

    this.model = process.env.LLM_MODEL ?? "gpt-4o-mini"
    this.timeoutMs = Number(process.env.LLM_TIMEOUT_MS) || 30000

    // Auto-detect provider from key prefix
    if (this.apiKey.startsWith("sk-or-")) {
      // OpenRouter
      this.provider = "openrouter"
      this.apiUrl = process.env.LLM_API_URL ?? "https://openrouter.ai/api/v1/chat/completions"
    } else if (this.apiKey.startsWith("AIzaSy") || this.apiKey.startsWith("AQ.")) {
      // Google Gemini
      this.provider = "gemini"
      this.apiUrl = process.env.LLM_API_URL ?? "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
      if (!process.env.LLM_MODEL) this.model = "gemini-2.0-flash"
    } else if (this.apiKey.startsWith("sk-ant")) {
      // Anthropic
      this.provider = "anthropic"
      this.apiUrl = process.env.LLM_API_URL ?? "https://api.anthropic.com/v1/messages"
    } else {
      // Default: OpenAI-compatible
      this.provider = "openai"
      this.apiUrl = process.env.LLM_API_URL ?? "https://api.openai.com/v1/chat/completions"
    }
  }

  isConfigured(): boolean {
    return this.apiKey.length > 0 && this.apiUrl.length > 0
  }

  async complete(
    prompt: string,
    options?: { system?: string; format?: string },
  ): Promise<{ text: string }> {
    const systemPrompt = options?.system ?? "You are a helpful assistant."
    const isJsonMode = options?.format === "json"

    const messages: Array<{ role: string; content: string }> = [
      { role: "system", content: systemPrompt },
      { role: "user", content: prompt },
    ]

    if (this.provider === "anthropic") {
      return this.callAnthropic(prompt, systemPrompt, isJsonMode)
    }

    return this.callOpenAICompatible(messages, isJsonMode)
  }

  /**
   * Fetch with 30s timeout and exponential backoff retries for transient failures.
   * Retries on 429 (rate limited) and 5xx (server errors). Does not retry on
   * non-transient 4xx errors or abort errors (timeouts).
   */
  private async fetchWithRetry(
    url: string,
    options: Omit<RequestInit, "signal">,
    retries = 3,
  ): Promise<Response> {
    for (let attempt = 0; attempt <= retries; attempt++) {
      const controller = new AbortController()
      const timeoutId = setTimeout(() => controller.abort(), this.timeoutMs)
      try {
        const response = await fetch(url, { ...options, signal: controller.signal })

        // Success or non-transient client error (not 429) — return immediately
        if (response.ok || (response.status < 500 && response.status !== 429)) {
          return response
        }

        // Transient: 429 or 5xx — retry if attempts remain
        if (attempt >= retries) return response

        const delayMs = Math.pow(2, attempt) * 1000
        await new Promise((resolve) => setTimeout(resolve, delayMs))
        continue
      } catch (err) {
        // Don't retry abort errors (timeouts) — propagate immediately
        if (err instanceof DOMException && err.name === "AbortError") throw err

        // Network errors (TypeError) — retry if attempts remain
        if (attempt >= retries) throw err

        const delayMs = Math.pow(2, attempt) * 1000
        await new Promise((resolve) => setTimeout(resolve, delayMs))
        continue
      } finally {
        clearTimeout(timeoutId)
      }
    }
    throw new Error("Unreachable")
  }

  private async callOpenAICompatible(
    messages: Array<{ role: string; content: string }>,
    isJsonMode: boolean,
  ): Promise<{ text: string }> {
    const payload: Record<string, unknown> = {
      model: this.model,
      messages,
      temperature: 0.3,
      max_tokens: 1000,
    }

    if (isJsonMode) {
      payload.response_format = { type: "json_object" }
    }

    const headers: Record<string, string> = {
      "Content-Type": "application/json",
    }
    if (this.apiKey) {
      headers["Authorization"] = `Bearer ${this.apiKey}`
    }

    const response = await this.fetchWithRetry(this.apiUrl, {
      method: "POST",
      headers,
      body: JSON.stringify(payload),
    })

    if (!response.ok) {
      const errorText = await response.text().catch(() => "Unknown error")
      throw new Error(`LLM API error ${response.status}: ${errorText}`)
    }

    const data = (await response.json()) as ChatCompletionResponse

    // Try common response formats
    if (data.choices?.[0]?.message?.content) {
      return { text: data.choices[0].message.content }
    }
    if (data.content) {
      return { text: data.content }
    }

    return { text: JSON.stringify(data) }
  }

  private async callAnthropic(
    userPrompt: string,
    systemPrompt: string,
    _isJsonMode: boolean,
  ): Promise<{ text: string }> {
    const payload = {
      model: this.model,
      system: systemPrompt,
      messages: [{ role: "user" as const, content: userPrompt }],
      max_tokens: 1000,
      temperature: 0.3,
    }

    const response = await this.fetchWithRetry(this.apiUrl, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "x-api-key": this.apiKey,
        "anthropic-version": "2023-06-01",
      },
      body: JSON.stringify(payload),
    })

    if (!response.ok) {
      const errorText = await response.text().catch(() => "Unknown error")
      throw new Error(`Anthropic API error ${response.status}: ${errorText}`)
    }

    const data = (await response.json()) as { content?: Array<{ text: string }> }
    const text = data.content?.map((c) => c.text).join("") ?? ""
    return { text }
  }
}

/** Singleton for reuse across the app */
let _instance: LlmClientImpl | null = null

export function getLlmClient(): LlmClientImpl {
  if (!_instance) {
    _instance = new LlmClientImpl()
  }
  return _instance
}
