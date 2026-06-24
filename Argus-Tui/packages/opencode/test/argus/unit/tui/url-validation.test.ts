/**
 * URL Validation Tests
 *
 * These tests verify the `new URL()` validation pattern used in dashboard.tsx
 * to prevent navigation to the scan route with malformed or invalid targets.
 *
 * The fix wraps `new URL(eng.target)` in a try/catch — valid URLs proceed
 * to the scan dashboard, invalid ones show a toast error and return early.
 */
import { describe, it, expect } from "bun:test"

describe("URL validation for dashboard scan navigation", () => {
  // --- Valid URLs (should NOT throw) ---

  it("accepts valid https URLs", () => {
    expect(() => new URL("https://example.com")).not.toThrow()
    expect(() => new URL("https://192.168.1.1:8080")).not.toThrow()
    expect(() => new URL("https://example.com/path?query=string")).not.toThrow()
    expect(() => new URL("https://sub.domain.org:8443/api/v1")).not.toThrow()
  })

  it("accepts valid http URLs", () => {
    expect(() => new URL("http://localhost:3000")).not.toThrow()
    expect(() => new URL("http://127.0.0.1")).not.toThrow()
    expect(() => new URL("http://example.com")).not.toThrow()
  })

  it("accepts URLs with ports, paths, and query strings", () => {
    expect(() => new URL("https://example.com:8080/api/v1?test=true&debug=false")).not.toThrow()
    expect(() => new URL("http://localhost:3000/health")).not.toThrow()
    expect(() => new URL("https://api.example.com/v1/users?id=42&page=1")).not.toThrow()
  })

  it("accepts IPv6 URLs", () => {
    expect(() => new URL("http://[::1]:8080")).not.toThrow()
    expect(() => new URL("https://[::1]")).not.toThrow()
    expect(() => new URL("http://[2001:db8::1]")).not.toThrow()
  })

  // --- Invalid URLs (SHOULD throw) ---

  it("rejects empty strings", () => {
    expect(() => new URL("")).toThrow()
  })

  it("rejects malformed bare words like 'foo' or 'not-a-url'", () => {
    expect(() => new URL("foo")).toThrow()
    expect(() => new URL("not-a-url")).toThrow()
    expect(() => new URL("just-some-text")).toThrow()
  })

  it("rejects bare IP addresses without scheme", () => {
    expect(() => new URL("192.168.1.1")).toThrow()
    expect(() => new URL("10.0.0.1")).toThrow()
  })

  it("rejects hostnames with spaces (space is not valid in host)", () => {
    expect(() => new URL("https://example .com")).toThrow()
  })

  it("accepts URLs with spaces in path (URL constructor auto-encodes them)", () => {
    // Spaces in paths are URL-encoded to %20, so this is a valid URL
    expect(() => new URL("https://example.com/path with/spaces")).not.toThrow()
    const url = new URL("https://example.com/path with/spaces")
    expect(url.pathname).toBe("/path%20with/spaces")
  })

  it("rejects bare domain names without scheme", () => {
    expect(() => new URL("example.com")).toThrow()
    expect(() => new URL("subdomain.example.org")).toThrow()
  })
})
