import { describe, expect, test } from "bun:test"
import { StoredXSSVerifier } from "../../../../../src/argus/browser/verifiers/xss"
import { XssProbeError } from "../../../../../src/argus/browser/verifiers/xss-probe"
import {
  XssPlanError,
  xssInjectionPlan,
  xssInjectionPointForFinding,
  type XssInjectionPoint,
} from "../../../../../src/argus/browser/verifiers/xss-plan"
import { ProofStatus } from "../../../../../src/argus/shared/types"

const TARGET = "https://app.example.com"

function makePage(url: string, content = "<html><body>clean</body></html>") {
  return {
    content: async () => content,
    url: () => url,
    goto: async () => ({}),
    close: async () => {},
    waitForLoadState: async () => {},
    waitForTimeout: async () => {},
    locator: (selector: string) => {
      const field = {
        isVisible: async () => selector.includes("name="),
        click: async () => {},
        fill: async (_value: string) => {},
        press: async (_key: string) => {},
      }
      return {
        all: async () => [],
        first: () => field,
        last: () => field,
        isVisible: async () => false,
        fill: async () => {},
        innerText: async () => "",
        count: async () => 0,
      }
    },
    evaluate: async () => "",
    screenshot: async () => Buffer.from("screenshot"),
  }
}

/** Records which context each navigation and probe installation happened in. */
function mockEngine(options: { observe?: boolean } = {}) {
  const events: string[] = []
  const navigations: Array<{ url: string; context: number }> = []
  const probeContexts: number[] = []
  const initScriptContexts: number[] = []
  let binding: ((source: { page?: { url?: () => string } }, payload: unknown) => unknown) | undefined
  let initScript = ""
  let context = 0
  let victimContent = "<html><body>clean — no markers</body></html>"
  let closed = false

  const injectPage = makePage("https://app.example.com/search?q=test")
  const victimPage = makePage("https://app.example.com/search?q=test", victimContent)

  const engine = {
    launch: async () => { events.push("launch") },
    createContext: async () => {
      context += 1
      const index = context
      events.push(`createContext#${index}`)
      if (options.observe === false) return {}
      return {
        exposeBinding: async (name: string, callback: (source: { page?: { url?: () => string } }, payload: unknown) => unknown) => {
          events.push(`exposeBinding#${index}:${name}`)
          probeContexts.push(index)
          binding = callback
        },
        addInitScript: async (script: { content: string }) => {
          events.push(`addInitScript#${index}`)
          initScriptContexts.push(index)
          initScript = script.content
        },
      }
    },
    navigate: async (url: string) => {
      events.push(`navigate#${context}:${url}`)
      navigations.push({ url, context })
      if (navigations.length === 1) return injectPage
      victimPage.content = async () => victimContent
      return victimPage
    },
    captureScreenshot: async () => Buffer.from("xss-screenshot"),
    close: async () => { closed = true },
    observe: async () => ({}),
    _events: events,
    _navigations: navigations,
    _probeContexts: probeContexts,
    _initScriptContexts: initScriptContexts,
    _initScript: () => initScript,
    _closed: () => closed,
    _setVictimContent: (c: string) => { victimContent = c; victimPage.content = async () => c },
    _victimPage: victimPage,
    _injectPage: injectPage,
    _fireHit: (payload: unknown, page: { url?: () => string } = victimPage) => {
      binding?.({ page }, payload)
    },
    _hasBinding: () => binding !== undefined,
  }
  return engine
}

const DISCOVERED_URL = "https://app.example.com/search?q=test"

function discoveredPlan(overrides: Record<string, unknown> = {}): XssInjectionPoint {
  return xssInjectionPlan(
    {
      endpoint: DISCOVERED_URL,
      evidenceRef: "finding:find-xss-1",
      ...overrides,
    },
    TARGET,
  )
}

function makeVerifier(
  engine: ReturnType<typeof mockEngine>,
  plan: XssInjectionPoint = discoveredPlan(),
  options?: { payloadTemplate?: string },
) {
  return new StoredXSSVerifier(
    engine as never,
    plan,
    undefined,
    undefined,
    undefined,
    options,
  )
}

async function runVerifier(verifier: StoredXSSVerifier) {
  await verifier.setup()
  await verifier.execute()
  return verifier.verify()
}

describe("StoredXSSVerifier (discovered endpoint and victim session)", () => {
  test("navigates the discovered endpoint/parameter and never the guessed /contact page", async () => {
    const engine = mockEngine()
    const verifier = makeVerifier(engine)
    await runVerifier(verifier)

    const urls = engine._navigations.map((n) => n.url)
    expect(urls.length).toBe(2)
    expect(urls[0].startsWith(`${DISCOVERED_URL.split("?")[0]}?`)).toBe(true)
    const injected = new URL(urls[0])
    expect(injected.searchParams.get("q")).toContain(verifier.executionNonce)
    expect(urls[1]).toBe(DISCOVERED_URL)
    expect(urls.some((url) => url.includes("/contact"))).toBe(false)
    expect(urls.some((url) => url === TARGET)).toBe(false)
  })

  test("uses a separate victim context and installs the probe there before navigation", async () => {
    const engine = mockEngine()
    const verifier = makeVerifier(engine)
    await runVerifier(verifier)

    const events = engine._events
    const injectionContext = events.indexOf("createContext#1")
    const firstNavigate = events.findIndex((e) => e.startsWith("navigate#1"))
    const victimContext = events.indexOf("createContext#2")
    const probeBinding = events.indexOf("exposeBinding#2:__argusXssHit")
    const initScript = events.indexOf("addInitScript#2")
    const victimNavigate = events.findIndex((e) => e.startsWith("navigate#2"))

    expect(injectionContext).toBeGreaterThanOrEqual(0)
    expect(firstNavigate).toBeGreaterThan(injectionContext)
    expect(victimContext).toBeGreaterThan(firstNavigate)
    expect(probeBinding).toBeGreaterThan(victimContext)
    expect(initScript).toBeGreaterThan(probeBinding)
    expect(victimNavigate).toBeGreaterThan(initScript)

    // The probe is a property of the victim context only.
    expect(engine._probeContexts).toEqual([2])
    expect(engine._initScriptContexts).toEqual([2])
    expect(engine._initScript()).toContain(verifier.executionNonce)
    expect(engine._navigations[1].context).toBe(2)
    expect(engine._navigations[0].context).toBe(1)

    const result = await verifier.verify()
    expect(result.controls?.some((c) => c.kind === "victim-session")).toBe(true)
  })

  test("delivers the payload through the discovered POST parameter", async () => {
    const engine = mockEngine()
    const plan = xssInjectionPlan(
      {
        endpoint: "https://app.example.com/comments",
        parameter: "comment",
        method: "POST",
        encoding: "form",
        evidenceRef: "finding:find-xss-post",
      },
      TARGET,
    )
    const verifier = makeVerifier(engine, plan)
    const result = await runVerifier(verifier)

    const urls = engine._navigations.map((n) => n.url)
    expect(urls[0]).toBe("https://app.example.com/comments")
    expect(urls).not.toContain(`${TARGET}/contact`)
    expect(result.controls?.some((c) => c.kind === "injection-session" && c.description.includes('parameter "comment"'))).toBe(true)
  })

  test("confirms only when the victim page reports this run's nonce", async () => {
    const engine = mockEngine()
    const verifier = makeVerifier(engine)
    await verifier.setup()
    await verifier.execute()
    engine._fireHit({ nonce: verifier.executionNonce, detail: "onerror" })
    const result = await verifier.verify()

    expect(result.passed).toBe(true)
    expect(result.proofStatus).toBe(ProofStatus.REPRODUCED)
    expect(result.summary).toContain("nonce payload executed in the victim view")
    expect(result.controls?.some((c) => c.kind === "nonce-execution" && c.outcome?.includes("executed"))).toBe(true)
  })

  test("does not confirm a page that merely contains the reflected payload", async () => {
    const engine = mockEngine()
    const verifier = makeVerifier(engine)
    await verifier.setup()
    engine._setVictimContent(
      `<html><body><img src=x onerror="__argusXssExecuted({where:'onerror',nonce:'${verifier.executionNonce}'})"></body></html>`,
    )
    await verifier.execute()
    const result = await verifier.verify()

    expect(result.passed).toBe(false)
    expect(result.proofStatus).toBe(ProofStatus.NOT_REPRODUCED)
    expect(result.summary).toContain("reflected but never ran")
  })

  test("does not confirm an execution report from the injection page", async () => {
    const engine = mockEngine()
    const verifier = makeVerifier(engine)
    await verifier.setup()
    await verifier.execute()
    engine._fireHit({ nonce: verifier.executionNonce, detail: "onerror" }, engine._injectPage)
    const result = await verifier.verify()

    expect(result.passed).toBe(false)
    expect(result.proofStatus).toBe(ProofStatus.NOT_REPRODUCED)
    expect(result.summary).toContain("injection page")
    expect(result.summary).toContain("not in the victim view")
  })

  test("ignores an execution report for a different nonce", async () => {
    const engine = mockEngine()
    const verifier = makeVerifier(engine)
    await verifier.setup()
    await verifier.execute()
    engine._fireHit({ nonce: "argus-xss-someone-else", detail: "onerror" })
    const result = await verifier.verify()

    expect(result.passed).toBe(false)
    expect(result.proofStatus).toBe(ProofStatus.NOT_REPRODUCED)
    expect(result.summary).toContain("no execution of the nonce payload")
  })

  test("reports no execution without claiming anything when the payload never runs", async () => {
    const engine = mockEngine()
    const verifier = makeVerifier(engine)
    const result = await runVerifier(verifier)

    expect(result.passed).toBe(false)
    expect(result.proofStatus).toBe(ProofStatus.NOT_REPRODUCED)
    expect(result.summary).toContain("not detected")
    expect(result.controls?.some((c) => c.kind === "nonce-execution" && c.outcome === "no execution observed")).toBe(true)
  })

  test("refuses a caller payload that cannot report a nonce", async () => {
    const engine = mockEngine()
    let caught: unknown
    try {
      makeVerifier(engine, discoveredPlan(), { payloadTemplate: "<script>alert('xss')</script>" })
    } catch (error) {
      caught = error
    }
    expect(caught).toBeInstanceOf(XssProbeError)
    if (!(caught instanceof XssProbeError)) throw new Error("expected XssProbeError")
    expect(caught.code).toBe("payload-without-nonce")
    expect(engine._events).not.toContain("launch")
  })

  test("fails closed when the victim context cannot install the probe", async () => {
    const engine = mockEngine({ observe: false })
    const verifier = makeVerifier(engine)
    let caught: unknown
    try {
      await verifier.setup()
      await verifier.execute()
    } catch (error) {
      caught = error
    }
    expect(caught).toBeInstanceOf(XssProbeError)
    if (!(caught instanceof XssProbeError)) throw new Error("expected XssProbeError")
    expect(caught.code).toBe("probe-not-installed")
  })

  test("an unrun verifier reports inconclusive rather than a negative", async () => {
    const engine = mockEngine()
    const verifier = makeVerifier(engine)
    const result = await verifier.verify()
    expect(result.passed).toBe(false)
    expect(result.proofStatus).toBe(ProofStatus.INCONCLUSIVE)
    expect(result.summary).toContain("victim session")
  })

  test("collectEvidence() returns screenshots, requests and responses", async () => {
    const engine = mockEngine()
    const verifier = makeVerifier(engine)
    await runVerifier(verifier)
    const evidence = await verifier.collectEvidence()
    expect(evidence.artifacts.some((a) => a.type === "screenshot")).toBe(true)
    expect(evidence.artifacts.some((a) => a.type === "request")).toBe(true)
    expect(evidence.artifacts.some((a) => a.type === "response")).toBe(true)
  })

  test("cleanup() closes the engine", async () => {
    const engine = mockEngine()
    const verifier = makeVerifier(engine)
    await verifier.setup()
    await verifier.cleanup()
    expect(engine._closed()).toBe(true)
  })
})

describe("XSS discovery fail-closed", () => {
  test("a finding with no discovered endpoint cannot produce an injection plan", () => {
    let caught: unknown
    try {
      xssInjectionPointForFinding({ id: "find-xss-none" }, TARGET)
    } catch (error) {
      caught = error
    }
    expect(caught).toBeInstanceOf(XssPlanError)
    if (!(caught instanceof XssPlanError)) throw new Error("expected XssPlanError")
    expect(caught.code).toBe("endpoint-missing")
    expect(caught.message).toContain("requires a discovered endpoint")
  })

  test("a discovered endpoint with no parameter cannot produce an injection plan", () => {
    let caught: unknown
    try {
      xssInjectionPointForFinding({ id: "f", url: "https://app.example.com/search" }, TARGET)
    } catch (error) {
      caught = error
    }
    expect(caught).toBeInstanceOf(XssPlanError)
    if (!(caught instanceof XssPlanError)) throw new Error("expected XssPlanError")
    expect(caught.code).toBe("parameter-missing")
  })
})

function artifact(type: "request" | "response" | "log" | "screenshot") {
  return { path: `${type}/a.txt`, type, hash: "h", size_bytes: 1 }
}

function mockCollector() {
  const logs: string[] = []
  const collector = {
    captureScreenshot: async () => artifact("screenshot"),
    saveRequest: async () => artifact("request"),
    saveResponse: async () => artifact("response"),
    saveLog: async (_engagementId: string, _findingId: string, log: string) => {
      logs.push(log)
      return artifact("log")
    },
    ingestHarFiles: async () => [],
    createPackage: async () => ({
      package_id: "pkg",
      engagement_id: "eng",
      created_at: new Date(0).toISOString(),
      artifacts: [],
      package_hash: "hash",
    }),
  }
  return { collector: collector as unknown as import("../../../../../src/argus/evidence/collector").EvidenceCollector, logs }
}

describe("StoredXSSVerifier evidence and non-executions", () => {
  test("preserves the request, response, execution event and cleanup outcome", async () => {
    const engine = mockEngine()
    const { collector, logs } = mockCollector()
    const verifier = new StoredXSSVerifier(
      engine as never,
      discoveredPlan(),
      collector,
      "eng-1",
      "find-1",
    )
    await verifier.setup()
    await verifier.execute()
    engine._fireHit({ nonce: verifier.executionNonce, detail: "onerror" })

    const pkg = await verifier.collectEvidence()
    const types = pkg.artifacts.map((a) => a.type)
    expect(types).toContain("request")
    expect(types).toContain("response")
    expect(types).toContain("log")
    expect(logs.some((log) => log.includes('"matchesRunNonce":true'))).toBe(true)
    expect(logs.some((log) => log.includes('"inVictimContext":true'))).toBe(true)

    await verifier.cleanup()
    expect(verifier.cleanupOutcome()).toEqual({
      ok: true,
      detail: "browser closed; temporary HAR directory removed",
    })
    expect(logs.some((log) => log.includes("cleanup:") && log.includes("browser closed"))).toBe(true)
  })

  test("a victim page that runs its own scripts but never the nonce payload does not pass", async () => {
    const engine = mockEngine()
    const verifier = makeVerifier(engine)
    await verifier.setup()
    engine._setVictimContent(
      "<html><body><script>alert('page script')</script><p>nothing injected here</p></body></html>",
    )
    await verifier.execute()
    // The page's own script touches the probe global with a nonce of its own.
    engine._fireHit({ nonce: "page-script-nonce", detail: "own-script" })
    const result = await verifier.verify()

    expect(result.passed).toBe(false)
    expect(result.proofStatus).toBe(ProofStatus.NOT_REPRODUCED)
    expect(result.controls?.some((c) => c.kind === "execution-source" && c.outcome?.includes("no attributable"))).toBe(true)
  })

  test("an encoded reflected payload does not pass", async () => {
    const engine = mockEngine()
    const verifier = makeVerifier(engine)
    await verifier.setup()
    const encoded = `<html><body>&lt;img src=x onerror="__argusXssExecuted({nonce:'${verifier.executionNonce}'})"&gt;</body></html>`
    engine._setVictimContent(encoded)
    await verifier.execute()
    const result = await verifier.verify()

    expect(result.passed).toBe(false)
    expect(result.proofStatus).toBe(ProofStatus.NOT_REPRODUCED)
    expect(result.summary).toContain("reflected but never ran")
  })

  test("an inert payload inside a template does not pass", async () => {
    const engine = mockEngine()
    const verifier = makeVerifier(engine)
    await verifier.setup()
    engine._setVictimContent(
      `<html><body><template><img src=x onerror="__argusXssExecuted({nonce:'${verifier.executionNonce}'})"></template></body></html>`,
    )
    await verifier.execute()
    const result = await verifier.verify()

    expect(result.passed).toBe(false)
    expect(result.proofStatus).toBe(ProofStatus.NOT_REPRODUCED)
    expect(result.summary).toContain("reflected but never ran")
  })

  test("records a failed teardown instead of hiding it", async () => {
    const engine = mockEngine()
    ;(engine as { close: () => Promise<void> }).close = async () => {
      throw new Error("browser already gone")
    }
    const verifier = makeVerifier(engine)
    await verifier.setup()
    await verifier.cleanup()
    const outcome = verifier.cleanupOutcome()
    expect(outcome.ok).toBe(false)
    expect(outcome.detail).toContain("browser close failed: browser already gone")
  })
})
