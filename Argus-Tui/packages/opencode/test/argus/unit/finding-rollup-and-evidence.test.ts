/**
 * Two things the first CONTAINED run (www.hisdayspringfamily.org) showed.
 *
 * 1. Volume. gospider reported one finding per crawled URL and katana did the
 *    same, so 824 of the engagement's 877 findings were page inventory at INFO
 *    — a list of pages, not a list of problems. Inventory now collapses to one
 *    row per tool and type; anything a scanner rated LOW or above is untouched.
 *
 * 2. Evidence. A MEDIUM+ finding must carry the response it came from, and the
 *    response must survive the write. It used to be dropped by the store, so a
 *    report could only repeat the severity label.
 */
import { afterAll, describe, expect, test } from "bun:test"
import { mkdtempSync, rmSync } from "fs"
import { join } from "path"
import { tmpdir } from "os"
import { Database } from "bun:sqlite"
import {
  EngagementStore,
  mergeDuplicateFindings,
  rollupInventoryFindings,
} from "../../../src/argus/engagement/store"
import { StoragePaths } from "../../../src/argus/storage/paths"
import { normalizeFinding } from "../../../src/argus/reporting/normalizer"
import { Severity } from "../../../src/argus/shared/types"
import type { NormalizedFinding } from "../../../src/argus/shared/types"

const dbDir = mkdtempSync(join(tmpdir(), "argus-rollup-test-"))
let counter = 0

afterAll(() => {
  try { rmSync(dbDir, { recursive: true, force: true }) } catch {}
})

function makeStore(): EngagementStore {
  counter += 1
  return new EngagementStore(join(dbDir, `rollup-${counter}.db`))
}

function finding(overrides: Partial<NormalizedFinding>): NormalizedFinding {
  return {
    id: `find-${Math.random().toString(36).slice(2)}`,
    title: "Finding",
    severity: Severity.INFO,
    confidence: 2,
    status: "PENDING",
    description: "",
    tool: "web_scanner",
    phase: "phase-0-recon",
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    ...overrides,
  }
}

function inventory(tool: string, subtype: string, count: number): NormalizedFinding[] {
  return Array.from({ length: count }, (_, i) =>
    finding({
      title: `${subtype}: /page-${i}`,
      subtype,
      tool,
      url: `https://www.hisdayspringfamily.org/page-${i}`,
    }),
  )
}

/** The engagement's real distribution, cut down to what matters here. */
function churchSiteFindings(): NormalizedFinding[] {
  return [
    ...inventory("gospider", "DISCOVERED_ENDPOINT", 782),
    ...inventory("katana", "CRAWLED_ENDPOINT", 42),
    finding({
      title: "Missing Content-Security-Policy",
      subtype: "MISSING_CSP",
      severity: Severity.MEDIUM,
      confidence: 3,
    }),
    finding({
      title: "Missing security headers",
      subtype: "MISSING_SECURITY_HEADERS",
      severity: Severity.MEDIUM,
      confidence: 3,
    }),
    finding({
      title: "Prototype pollution",
      subtype: "PROTOTYPE_POLLUTION",
      severity: Severity.MEDIUM,
      confidence: 2,
    }),
  ]
}

describe("inventory rollup", () => {
  test("824 per-URL findings become two inventory rows", () => {
    const rolled = rollupInventoryFindings(churchSiteFindings())

    const inventoryRows = rolled.filter((f) => f.title.includes("inventory"))
    expect(inventoryRows).toHaveLength(2)
    expect(rolled).toHaveLength(5)

    const endpoints = inventoryRows.find((f) => f.tool === "gospider")!
    expect(endpoints.title).toBe("Endpoint inventory — gospider")
    expect(endpoints.severity).toBe(Severity.INFO)
    expect(endpoints.description).toContain("782 endpoints observed by gospider")
    expect(endpoints.description).toContain("https://www.hisdayspringfamily.org/page-0")

    const crawled = inventoryRows.find((f) => f.tool === "katana")!
    expect(crawled.description).toContain("42 endpoints observed by katana")
  })

  test("findings at LOW or above are never folded away", () => {
    const reported = finding({
      title: "Exposed sensitive file",
      subtype: "DISCOVERED_ENDPOINT",
      severity: Severity.HIGH,
      tool: "gospider",
    })

    const rolled = rollupInventoryFindings([reported])

    expect(rolled).toHaveLength(1)
    expect(rolled[0].severity).toBe(Severity.HIGH)
    expect(rolled[0].title).toBe("Exposed sensitive file")
  })

  test("non-inventory INFO findings keep their own row", () => {
    const rolled = rollupInventoryFindings(churchSiteFindings())
    const csp = rolled.find((f) => f.subtype === "MISSING_CSP")!

    expect(csp.title).toBe("Missing Content-Security-Policy")
    expect(csp.severity).toBe(Severity.MEDIUM)
  })
})

describe("EngagementStore — inventory rows and response evidence", () => {
  test("a full crawl writes five rows, not 829", () => {
    const store = makeStore()
    const eng = store.createEngagement("https://www.hisdayspringfamily.org", "assessment")

    store.saveFindings(eng.id, churchSiteFindings())

    expect(store.getFindings(eng.id)).toHaveLength(5)
  })

  test("re-saving a partial then a complete crawl updates one inventory row", () => {
    const store = makeStore()
    const eng = store.createEngagement("https://www.hisdayspringfamily.org", "assessment")

    store.saveFindings(eng.id, inventory("gospider", "DISCOVERED_ENDPOINT", 20))
    store.saveFindings(eng.id, inventory("gospider", "DISCOVERED_ENDPOINT", 782))

    const rows = store.getFindings(eng.id)
    expect(rows).toHaveLength(1)
    expect(rows[0].description).toContain("782 endpoints")
  })

  test("MEDIUM finding round-trips its observed response", () => {
    const store = makeStore()
    const eng = store.createEngagement("https://www.hisdayspringfamily.org", "assessment")
    const observed = {
      url: "https://www.hisdayspringfamily.org/",
      statusCode: 200,
      headers: { server: "Caddy", "x-frame-options": "DENY" },
      bodyBytes: 42,
      bodySha256: "a".repeat(64),
      preview: "&lt;!doctype html&gt;",
    }

    store.saveFindings(eng.id, [
      finding({
        id: "csp-1",
        title: "Missing Content-Security-Policy",
        subtype: "MISSING_CSP",
        severity: Severity.MEDIUM,
        responseEvidence: observed,
      }),
    ])

    const [saved] = store.getFindings(eng.id)
    expect(saved.responseEvidence).toEqual(observed)
  })

  test("normalizer lifts http_response out of worker evidence", () => {
    const normalized = normalizeFinding({
      title: "Missing Content-Security-Policy",
      severity: 2,
      confidence: 3,
      tool: "web_scanner",
      evidence: [
        { message: "No Content-Security-Policy header found" },
        {
          http_response: {
            url: "https://www.hisdayspringfamily.org/",
            status_code: 200,
            headers: { server: "Caddy" },
            body_bytes: 12,
            body_sha256: "b".repeat(64),
            body_preview: "hello",
          },
        },
      ],
    })

    expect(normalized.responseEvidence).toEqual({
      url: "https://www.hisdayspringfamily.org/",
      statusCode: 200,
      headers: { server: "Caddy" },
      bodyBytes: 12,
      bodySha256: "b".repeat(64),
      preview: "hello",
    })
  })

  test("an engagement DB written before response_evidence existed still opens", () => {
    const rootPath = join(dbDir, "legacy-root.db")
    const observed = {
      url: "https://www.hisdayspringfamily.org/",
      statusCode: 200,
      headers: { server: "Caddy" },
      bodyBytes: 128,
      bodySha256: "c".repeat(64),
      preview: "&lt;html&gt;",
    }

    const store = new EngagementStore(rootPath)
    const eng = store.createEngagement("https://www.hisdayspringfamily.org", "assessment")
    store.saveFindings(eng.id, [
      finding({ id: "legacy-1", title: "Missing security headers", severity: Severity.MEDIUM }),
    ])
    store.close()

    // Rewind the per-engagement DB to the schema the church-site run wrote:
    // findings had a url column but no response_evidence column.
    const engPath = StoragePaths.engagementDbPath(eng.id)
    const legacy = new Database(engPath)
    legacy.exec("ALTER TABLE findings DROP COLUMN response_evidence")
    const columns = legacy.query("PRAGMA table_info(findings)").all() as { name: string }[]
    expect(columns.some((c) => c.name === "response_evidence")).toBe(false)
    legacy.close()

    const reopened = new EngagementStore(rootPath)
    try {
      const loaded = reopened.getFindings(eng.id)
      expect(loaded).toHaveLength(1)
      expect(loaded[0].id).toBe("legacy-1")
      expect(loaded[0].responseEvidence).toBeUndefined()

      reopened.saveFindings(eng.id, [
        finding({
          id: "legacy-1",
          title: "Missing security headers",
          severity: Severity.MEDIUM,
          responseEvidence: observed,
        }),
      ])

      expect(reopened.getFindings(eng.id)[0].responseEvidence).toEqual(observed)
    } finally {
      reopened.close()
    }
  })

  test("raw worker evidence is lifted into response_evidence on write", () => {
    const store = makeStore()
    const eng = store.createEngagement("https://www.hisdayspringfamily.org", "assessment")

    // The workflow runner saves worker findings without normalizing them first,
    // so the http_response block is still inside evidence.
    store.saveFindings(eng.id, [
      {
        ...finding({ id: "raw-1", title: "Missing csp: /", severity: Severity.MEDIUM }),
        evidence: [
          {
            http_response: {
              url: "https://www.hisdayspringfamily.org/",
              status_code: 200,
              headers: { server: "Caddy" },
              body_bytes: 10,
              body_sha256: "d".repeat(64),
              body_preview: "hello",
            },
          },
        ],
      } as unknown as NormalizedFinding,
    ])

    expect(store.getFindings(eng.id)[0].responseEvidence).toEqual({
      url: "https://www.hisdayspringfamily.org/",
      statusCode: 200,
      headers: { server: "Caddy" },
      bodyBytes: 10,
      bodySha256: "d".repeat(64),
      preview: "hello",
    })
  })

  test("a finding with no http_response evidence has none invented", () => {
    const normalized = normalizeFinding({
      title: "Certificate expired",
      severity: 3,
      confidence: 3,
      tool: "web_scanner",
      evidence: [{ reason: "expired" }],
    })

    expect(normalized.responseEvidence).toBeUndefined()
  })
})

describe("duplicate root causes", () => {
  test("missing CSP from two tools is one finding", () => {
    const merged = mergeDuplicateFindings([
      finding({ title: "Missing csp: /", severity: Severity.MEDIUM, tool: "web_scanner" }),
      finding({
        title: "Missing csp: https://www.hisdayspringfamily.org",
        severity: Severity.MEDIUM,
        tool: "browser_security_operator",
        responseEvidence: { statusCode: 200 },
      }),
    ])

    expect(merged).toHaveLength(1)
    expect(merged[0].responseEvidence?.statusCode).toBe(200)
    expect(merged[0].description).toContain("browser_security_operator")
  })

  test("the same port from two tools is one finding at the worst severity", () => {
    const merged = mergeDuplicateFindings([
      finding({ title: "Open port: www.hisdayspringfamily.org:443", severity: Severity.MEDIUM, tool: "naabu" }),
      finding({ title: "Open port: 443/tcp (https)", severity: Severity.INFO, tool: "nmap" }),
      // The attack-surface row names the host but no port, so it is a different
      // statement and must not be folded into port 443.
      finding({ title: "Open port: www.hisdayspringfamily.org", severity: Severity.INFO, tool: "attack_surface_mapper" }),
    ])

    expect(merged).toHaveLength(2)
    expect(merged.find((f) => f.tool === "naabu")?.severity).toBe(Severity.MEDIUM)
  })

  test("different problems and different ports stay separate", () => {
    const merged = mergeDuplicateFindings([
      finding({ title: "Missing security headers", severity: Severity.LOW }),
      finding({ title: "Missing csp: /", severity: Severity.MEDIUM }),
      finding({ title: "Open port: 22/tcp (ssh)", severity: Severity.INFO }),
      finding({ title: "Open port: 443/tcp (https)", severity: Severity.INFO }),
    ])

    expect(merged).toHaveLength(4)
  })

  test("a duplicate arriving in a later phase merges into the stored row", () => {
    const store = makeStore()
    const eng = store.createEngagement("https://www.hisdayspringfamily.org", "assessment")

    store.saveFindings(eng.id, [
      finding({ title: "Missing x frame options: /", severity: Severity.LOW, tool: "web_scanner" }),
    ])
    store.saveFindings(eng.id, [
      finding({
        title: "Missing x frame options: https://www.hisdayspringfamily.org/",
        severity: Severity.LOW,
        tool: "browser_security_operator",
      }),
    ])

    const rows = store.getFindings(eng.id)
    expect(rows).toHaveLength(1)
    expect(rows[0].title).toContain("x frame options")
  })

  test("a full crawl plus duplicates writes one row per problem", () => {
    const store = makeStore()
    const eng = store.createEngagement("https://www.hisdayspringfamily.org", "assessment")

    store.saveFindings(eng.id, [
      ...churchSiteFindings(),
      finding({ title: "Missing csp: https://www.hisdayspringfamily.org", severity: Severity.MEDIUM, tool: "browser_security_operator" }),
      finding({ title: "Open port: 443/tcp (https)", severity: Severity.INFO, tool: "nmap" }),
      finding({ title: "Open port: www.hisdayspringfamily.org:443", severity: Severity.MEDIUM, tool: "naabu" }),
    ])

    const rows = store.getFindings(eng.id)
    expect(rows.filter((f) => f.subtype === "MISSING_CSP")).toHaveLength(1)
    // 5 base rows, both CSP reports merged, and the two 443 reports merged.
    expect(rows).toHaveLength(6)
  })
})

describe("observations are not findings", () => {
  test("ten negative DNS answers become one observation row", () => {
    const dns = Array.from({ length: 10 }, (_, i) =>
      finding({
        title: `Host resolves: api${i}.hisdayspringfamily.org -> no A record`,
        severity: Severity.INFO,
        tool: "dnsx",
      }),
    )

    const rolled = rollupInventoryFindings(mergeDuplicateFindings(dns))
    expect(rolled).toHaveLength(1)
    expect(rolled[0].title).toBe("DNS observation inventory — dnsx")
    expect(rolled[0].description).toContain("10 dns observations")
  })

  test("a clean-negative recon check collapses to one row", () => {
    const rolled = rollupInventoryFindings([
      finding({ title: "Subdomain enumeration complete for www.hisdayspringfamily.org: no certificate-transparency hosts", severity: Severity.INFO, tool: "amass" }),
      finding({ title: "Subdomain enumeration complete for www.hisdayspringfamily.org: no certificate-transparency hosts", severity: Severity.INFO, tool: "subfinder" }),
    ])

    expect(rolled.map((f) => f.tool).sort()).toEqual(["amass", "subfinder"])
    expect(rolled.every((f) => f.title.includes("Subdomain check inventory"))).toBe(true)
  })
})
