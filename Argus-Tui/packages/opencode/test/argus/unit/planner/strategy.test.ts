import { describe, expect, test } from "bun:test"
import { detectTargetType, detectAuthState, determineRequiredCapabilities } from "@argus/planner/strategy"
import { Capability } from "@argus/planner/capabilities"

describe("strategy", () => {
  describe("detectTargetType", () => {
    test("detects api from /api path", () => {
      expect(detectTargetType("https://example.com/api/v1/users")).toBe("api")
    })

    test("detects api from /graphql path", () => {
      expect(detectTargetType("https://example.com/graphql")).toBe("api")
    })

    test("detects api from .json endpoint", () => {
      expect(detectTargetType("https://api.example.com/data.json")).toBe("api")
    })

    test("detects spa from tech stack", () => {
      expect(detectTargetType("https://app.example.com", ["react"])).toBe("spa")
      expect(detectTargetType("https://app.example.com", ["vue"])).toBe("spa")
      expect(detectTargetType("https://app.example.com", ["angular"])).toBe("spa")
      expect(detectTargetType("https://app.example.com", ["svelte"])).toBe("spa")
    })

    test("detects web_app from http url", () => {
      expect(detectTargetType("https://example.com")).toBe("web_app")
      expect(detectTargetType("http://example.com/page")).toBe("web_app")
    })

    test("returns unknown for unrecognized input", () => {
      expect(detectTargetType("")).toBe("unknown")
      expect(detectTargetType("localhost")).toBe("unknown")
      expect(detectTargetType("192.168.1.1")).toBe("unknown")
    })

    test("is case insensitive", () => {
      expect(detectTargetType("HTTPS://EXAMPLE.COM/API/USERS")).toBe("api")
      expect(detectTargetType("https://example.com/GraphQL")).toBe("api")
    })

    test("prefers api over web_app when both match", () => {
      expect(detectTargetType("https://example.com/api/dashboard")).toBe("api")
    })
  })

  describe("detectAuthState", () => {
    test("detects oauth from url keywords", () => {
      expect(detectAuthState("https://example.com/oauth/callback")).toBe("oauth")
      expect(detectAuthState("https://auth.example.com/login")).toBe("oauth")
    })

    test("detects jwt from url keywords", () => {
      expect(detectAuthState("https://example.com/jwt/token")).toBe("jwt")
      expect(detectAuthState("https://example.com/api/token/refresh")).toBe("jwt")
    })

    test("detects session from url", () => {
      expect(detectAuthState("https://example.com/session/check")).toBe("session")
    })

    test("returns basic for http urls without auth keywords", () => {
      expect(detectAuthState("https://example.com")).toBe("basic")
      expect(detectAuthState("http://example.com/page")).toBe("basic")
    })

    test("returns none for non-http targets", () => {
      expect(detectAuthState("localhost:3000")).toBe("none")
      expect(detectAuthState("192.168.1.1")).toBe("none")
      expect(detectAuthState("")).toBe("none")
    })
  })

  describe("determineRequiredCapabilities", () => {
    test("includes web_recon for all target types", () => {
      const caps = determineRequiredCapabilities("web_app", "none")
      expect(caps).toContain(Capability.WEB_RECON)
    })

    test("includes scanning capabilities for web_app", () => {
      const caps = determineRequiredCapabilities("web_app", "none")
      expect(caps).toContain(Capability.PORT_SCANNING)
      expect(caps).toContain(Capability.TECHNOLOGY_DETECTION)
      expect(caps).toContain(Capability.CONTENT_DISCOVERY)
      expect(caps).toContain(Capability.VULNERABILITY_SCANNING)
      expect(caps).toContain(Capability.TEMPLATE_SCANNING)
      expect(caps).toContain(Capability.HTTP_PROBE)
    })

    test("includes api probing for api targets", () => {
      const caps = determineRequiredCapabilities("api", "none")
      expect(caps).toContain(Capability.API_PROBING)
      expect(caps).toContain(Capability.CONTENT_DISCOVERY)
      expect(caps).toContain(Capability.VULNERABILITY_SCANNING)
    })

    test("includes auth capabilities when auth state is not none", () => {
      for (const auth of ["basic", "oauth", "jwt", "session"] as const) {
        const caps = determineRequiredCapabilities("web_app", auth)
        expect(caps).toContain(Capability.AUTH_DETECTION)
        expect(caps).toContain(Capability.CREDENTIAL_ANALYSIS)
      }
    })

    test("does not include auth capabilities when auth is none", () => {
      const caps = determineRequiredCapabilities("web_app", "none")
      expect(caps).not.toContain(Capability.AUTH_DETECTION)
      expect(caps).not.toContain(Capability.CREDENTIAL_ANALYSIS)
    })

    test("adds graphql assessment when tech stack includes graphql", () => {
      const caps = determineRequiredCapabilities("api", "none", ["graphql"])
      expect(caps).toContain(Capability.GRAPHQL_ASSESSMENT)
    })

    test("adds vulnerability_scanning when tech stack includes express (no dedicated Express CVE scanner)", () => {
      const caps = determineRequiredCapabilities("web_app", "none", ["express"])
      expect(caps).toContain(Capability.VULNERABILITY_SCANNING)
    })

    test("adds api docs analysis for swagger/openapi", () => {
      const swagger = determineRequiredCapabilities("api", "none", ["swagger"])
      expect(swagger).toContain(Capability.API_DOCS_ANALYSIS)
      const openapi = determineRequiredCapabilities("api", "none", ["openapi"])
      expect(openapi).toContain(Capability.API_DOCS_ANALYSIS)
    })

    test("adds jwt analysis when tech stack includes jwt", () => {
      const caps = determineRequiredCapabilities("api", "jwt", ["jwt"])
      expect(caps).toContain(Capability.JWT_ANALYSIS)
    })

    test("always includes browser_verification and report_generation", () => {
      const caps = determineRequiredCapabilities("unknown", "none")
      expect(caps).toContain(Capability.BROWSER_VERIFICATION)
      expect(caps).toContain(Capability.REPORT_GENERATION)
    })

    test("handles unknown target type gracefully", () => {
      const caps = determineRequiredCapabilities("unknown", "none")
      expect(caps).toContain(Capability.WEB_RECON)
      expect(caps).not.toContain(Capability.VULNERABILITY_SCANNING)
    })

    test("handles undefined techStack", () => {
      const caps = determineRequiredCapabilities("web_app", "none", undefined)
      expect(caps.length).toBeGreaterThan(0)
    })

    test("is case insensitive for tech stack", () => {
      const caps = determineRequiredCapabilities("api", "none", ["GraphQL", "Express"])
      expect(caps).toContain(Capability.GRAPHQL_ASSESSMENT)
      expect(caps).toContain(Capability.VULNERABILITY_SCANNING)
    })
  })
})
