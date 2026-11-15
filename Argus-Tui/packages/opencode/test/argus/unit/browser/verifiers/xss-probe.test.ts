import { describe, expect, test } from "bun:test"
import {
  XSS_EXECUTION_GLOBAL,
  XSS_HIT_BINDING,
  XSS_NONCE_PLACEHOLDER,
  XssProbeError,
  createXssNonce,
  installXssProbe,
  resolveXssPayload,
  xssProbeInitScript,
  xssProbePayload,
  type XssBindingCallback,
  type XssExecutionHit,
} from "../../../../../src/argus/browser/verifiers/xss-probe"

function expectProbeError(fn: () => unknown, code: XssProbeError["code"]): void {
  try {
    fn()
  } catch (error) {
    if (!(error instanceof XssProbeError)) throw error
    expect(error.code).toBe(code)
    return
  }
  throw new Error(`expected XssProbeError(${code}) but nothing was thrown`)
}

describe("xss probe nonces", () => {
  test("a nonce is unique per run and usable as a page token", () => {
    const first = createXssNonce()
    const second = createXssNonce()
    expect(first).not.toBe(second)
    expect(first).toMatch(/^argus-xss-[0-9a-f]{32}$/)
  })

  test("a nonce that changes the script is refused", () => {
    expectProbeError(() => xssProbeInitScript("bad');alert(1);//"), "invalid-nonce")
    expectProbeError(() => xssProbePayload("short"), "invalid-nonce")
  })
})

describe("xss payload resolution", () => {
  test("the default payload carries the nonce and calls the probe", () => {
    const nonce = createXssNonce()
    const payload = resolveXssPayload(undefined, nonce)
    expect(payload).toContain(nonce)
    expect(payload).toContain(`${XSS_EXECUTION_GLOBAL}(`)
    expect(payload).toContain("onerror")
  })

  test("an empty template still yields the nonce payload", () => {
    const nonce = createXssNonce()
    expect(resolveXssPayload("   ", nonce)).toBe(xssProbePayload(nonce))
  })

  test("a template without the nonce placeholder is refused", () => {
    expectProbeError(
      () => resolveXssPayload("<script>alert('xss')</script>", createXssNonce()),
      "payload-without-nonce",
    )
  })

  test("a template that reflects the nonce without calling the probe is refused", () => {
    expectProbeError(
      () => resolveXssPayload(`<img src=x onerror="alert('${XSS_NONCE_PLACEHOLDER}')">`, createXssNonce()),
      "payload-without-probe",
    )
  })

  test("a template with the placeholder and probe call is substituted", () => {
    const nonce = createXssNonce()
    const payload = resolveXssPayload(
      `<svg onload="${XSS_EXECUTION_GLOBAL}({where:'onload',nonce:'${XSS_NONCE_PLACEHOLDER}'})">`,
      nonce,
    )
    expect(payload).toContain("onload")
    expect(payload).toContain(nonce)
    expect(payload).not.toContain(XSS_NONCE_PLACEHOLDER)
  })
})

describe("xss probe installation", () => {
  test("the init script defines the probe entry point with this run's nonce", () => {
    const nonce = createXssNonce()
    const script = xssProbeInitScript(nonce)
    expect(script).toContain(JSON.stringify(nonce))
    expect(script).toContain(XSS_EXECUTION_GLOBAL)
    expect(script).toContain(XSS_HIT_BINDING)
  })

  test("installs the binding and the init script on the context", async () => {
    const nonce = createXssNonce()
    const calls: string[] = []
    const context = {
      exposeBinding: async (name: string) => { calls.push(`binding:${name}`) },
      addInitScript: async () => { calls.push("init-script") },
    }
    await installXssProbe(context, nonce, () => {})
    expect(calls).toEqual([`binding:${XSS_HIT_BINDING}`, "init-script"])
  })

  test("forwards a page execution report with the page identity", async () => {
    const nonce = createXssNonce()
    const hits: XssExecutionHit[] = []
    let binding: XssBindingCallback | undefined
    const page = { url: () => "https://example.com/victim" }
    await installXssProbe(
      {
        exposeBinding: async (_name, callback) => { binding = callback },
        addInitScript: async () => {},
      },
      nonce,
      (hit) => hits.push(hit),
    )
    binding!({ page }, { nonce, detail: "onerror", href: page.url() })
    expect(hits).toHaveLength(1)
    expect(hits[0].nonce).toBe(nonce)
    expect(hits[0].url).toBe("https://example.com/victim")
    expect(hits[0].detail).toBe("onerror")
    expect(hits[0].page).toBe(page)
  })

  test("ignores reports that carry no nonce", async () => {
    let binding: XssBindingCallback | undefined
    const hits: XssExecutionHit[] = []
    await installXssProbe(
      {
        exposeBinding: async (_name, callback) => { binding = callback as typeof binding },
        addInitScript: async () => {},
      },
      createXssNonce(),
      (hit) => hits.push(hit),
    )
    binding!({}, { detail: "onerror" })
    expect(hits).toHaveLength(0)
  })

  test("fails closed when the context cannot observe execution", async () => {
    let caught: unknown
    try {
      await installXssProbe({}, createXssNonce(), () => {})
    } catch (error) {
      caught = error
    }
    expect(caught).toBeInstanceOf(XssProbeError)
    expect((caught as XssProbeError).code).toBe("probe-not-installed")
  })
})
