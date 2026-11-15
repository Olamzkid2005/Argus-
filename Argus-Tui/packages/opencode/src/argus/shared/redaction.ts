/**
 * Shared secret redaction for exported text.
 *
 * The same sanitizer protects LLM prompts and emitted reports: credentials,
 * tokens, cookies, private keys, and embedded database/URL credentials are
 * replaced before they can leave the local engagement boundary.
 */
export function redactSecrets(text: string): string {
  // Redact Authorization headers (Bearer and Basic)
  text = text.replace(
    /(Authorization|Proxy-Authorization)\s*:\s*Bearer\s+\S+/gi,
    "$1: Bearer __REDACTED__"
  )
  text = text.replace(
    /(Authorization|Proxy-Authorization)\s*:\s*Basic\s+\S+/gi,
    "$1: Basic __REDACTED__"
  )
  // Redact Cookie / Set-Cookie headers without consuming unrelated text that
  // happens to follow the header on the same line.
  text = text.replace(
    /\b((?:Set-Cookie|Cookie)\s*:\s*)([^\r\n]+)/gi,
    (_match: string, prefix: string, cookies: string) => {
      const pairs = cookies.match(/(?:^|;\s*)[^=;\s]+=[^\s;]*/g)
      if (pairs) {
        return prefix + cookies.replace(
          /(?:^|;\s*)[^=;\s]+=[^\s;]*/g,
          (pair: string) => pair.replace(/=.*$/, "=__REDACTED__"),
        )
      }
      const [first, ...rest] = cookies.split(/\s+/)
      if (first) return `${prefix}__REDACTED__${rest.length > 0 ? ` ${rest.join(" ")}` : ""}`
      return `${prefix}__REDACTED__`
    },
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
    /(password|passwd|pwd)\s*[:=]\s*["']?[^\s"'&,;){]+["']?/gi,
    "$1=__REDACTED__"
  )
  text = text.replace(
    /(secret|api[_-]?key|api[_-]?token|access[_-]?token)\s*[:=]\s*["']?[^\s"'&,;){]+["']?/gi,
    "$1=__REDACTED__"
  )
  // Redact private keys (RSA, EC, OPENSSH, PGP)
  text = text.replace(
    /-----BEGIN\s+(RSA\s+)?PRIVATE\s+KEY-----[\s\S]*?-----END\s+(RSA\s+)?PRIVATE\s+KEY-----/gi,
    "__REDACTED_PRIVATE_KEY__"
  )
  text = text.replace(
    /-----BEGIN\s+OPENSSH\s+PRIVATE\s+KEY-----[\s\S]*?-----END\s+OPENSSH\s+PRIVATE\s+KEY-----/gi,
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
