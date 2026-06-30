/**
 * HAR Parser — reads Playwright HAR (HTTP Archive) files and extracts
 * request/response data for persistence through the EvidenceCollector.
 *
 * Playwright's `recordHar` option produces HAR files with the following structure:
 * {
 *   log: {
 *     entries: [{
 *       request:  { method, url, httpVersion, headers: [{ name, value }], postData: { text } },
 *       response: { status, statusText, httpVersion, headers: [{ name, value }], content: { text, mimeType, size } },
 *       startedDateTime, time
 *     }]
 *   }
 * }
 */

import { readFileSync } from "fs"
import { readdirSync } from "fs"
import { join } from "path"

/** A single parsed HAR entry with structured request/response data. */
export interface HarEntry {
  /** HTTP method (GET, POST, etc.) */
  method: string
  /** Full request URL */
  url: string
  /** HTTP version (e.g., "HTTP/1.1") */
  httpVersion: string
  /** Request headers as key-value pairs */
  requestHeaders: Record<string, string>
  /** Request body (empty string if no body) */
  requestBody: string
  /** Response status code */
  statusCode: number
  /** Response status text */
  statusText: string
  /** Response headers as key-value pairs */
  responseHeaders: Record<string, string>
  /** Response body content (empty string if not embedded) */
  responseBody: string
  /** Response MIME type */
  mimeType: string
  /** Time the request took in milliseconds */
  timeMs: number
  /** ISO timestamp of when the request started */
  startedAt: string
}

/**
 * Parse a single HAR file and extract all request/response entries.
 * Returns an empty array if the file is invalid or unreadable.
 */
export function parseHarFile(filePath: string): HarEntry[] {
  try {
    const raw = readFileSync(filePath, "utf-8")
    const har = JSON.parse(raw)

    if (!har?.log?.entries || !Array.isArray(har.log.entries)) {
      return []
    }

    return har.log.entries.map((entry: any): HarEntry => {
      const req = entry.request ?? {}
      const res = entry.response ?? {}

      return {
        method: req.method ?? "GET",
        url: req.url ?? "",
        httpVersion: req.httpVersion ?? res.httpVersion ?? "HTTP/1.1",
        requestHeaders: normalizeHeaders(req.headers),
        requestBody: req.postData?.text ?? "",
        statusCode: res.status ?? 0,
        statusText: res.statusText ?? "",
        responseHeaders: normalizeHeaders(res.headers),
        responseBody: res.content?.text ?? "",
        mimeType: res.content?.mimeType ?? "",
        timeMs: entry.time ?? 0,
        startedAt: entry.startedDateTime ?? new Date().toISOString(),
      }
    })
  } catch {
    // Invalid or unreadable HAR file
    return []
  }
}

/**
 * Scan a directory for all .har files and parse each one.
 * Returns a flat array of all entries found across all HAR files.
 */
export function parseHarDirectory(harDir: string): HarEntry[] {
  try {
    const files = readdirSync(harDir).filter((f) => f.endsWith(".har"))
    const allEntries: HarEntry[] = []
    for (const file of files) {
      const entries = parseHarFile(join(harDir, file))
      allEntries.push(...entries)
    }
    return allEntries
  } catch {
    return []
  }
}

/**
 * Format a HAR entry as a human-readable request string suitable for
 * EvidenceCollector.saveRequest(). Includes method, URL, headers, and body.
 */
export function formatRequest(entry: HarEntry): string {
  const lines: string[] = [
    `${entry.method} ${entry.url} ${entry.httpVersion}`,
  ]
  for (const [key, value] of Object.entries(entry.requestHeaders)) {
    lines.push(`${key}: ${value}`)
  }
  if (entry.requestBody) {
    lines.push("")
    lines.push(entry.requestBody)
  }
  return lines.join("\n")
}

/**
 * Format a HAR entry as a human-readable response string suitable for
 * EvidenceCollector.saveResponse(). Includes status, headers, and body.
 */
export function formatResponse(entry: HarEntry): string {
  const lines: string[] = [
    `${entry.httpVersion} ${entry.statusCode} ${entry.statusText}`,
  ]
  for (const [key, value] of Object.entries(entry.responseHeaders)) {
    lines.push(`${key}: ${value}`)
  }
  if (entry.responseBody) {
    lines.push("")
    lines.push(entry.responseBody)
  }
  return lines.join("\n")
}

/**
 * Convert an array of [{ name, value }] header objects to a Record<string, string>.
 * Header names are lowercased for consistent access.
 */
function normalizeHeaders(headers: Array<{ name: string; value: string }> | undefined): Record<string, string> {
  const result: Record<string, string> = {}
  if (!headers) return result
  for (const h of headers) {
    result[h.name.toLowerCase()] = h.value
  }
  return result
}
