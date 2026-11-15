/**
 * The XSS execution probe — Stage 4.3 item 1.
 *
 * A reflected `<script>` string, an `onerror=` fragment in `innerHTML`, or the
 * payload echoed into the page body are all things a *page* can contain without
 * the browser ever running the payload: escaping, sanitising, CSP and an inert
 * fetch all look like "markers" to a string scan. So confirmation no longer
 * comes from matching text. Every run generates a fresh random nonce, installs
 * a binding that reports executions to Node, and injects a payload that can
 * only report that nonce by actually executing in the page. A run is confirmed
 * only when a report for *its* nonce arrives from the victim page.
 *
 * The probe is installed on the browser context before the first navigation
 * (`addInitScript` runs before page scripts, and the binding exists for every
 * page in the context), so a report cannot be produced by replaying something
 * observed after the fact, and cannot be attributed to a page outside the
 * intended context.
 */

import { randomBytes } from "crypto"

/** Where a caller-supplied payload template must place the run's nonce. */
export const XSS_NONCE_PLACEHOLDER = "{{nonce}}"

/** Page-side function the payload calls; it forwards the hit to Node. */
export const XSS_EXECUTION_GLOBAL = "__argusXssExecuted"

/** Binding installed on the context; the page-side wrapper calls it. */
export const XSS_HIT_BINDING = "__argusXssHit"

export type XssProbeErrorCode =
  | "payload-without-nonce"
  | "payload-without-probe"
  | "invalid-nonce"
  | "probe-not-installed"

/** A payload that cannot prove its own execution is refused, not weakened. */
export class XssProbeError extends Error {
  override readonly name = "XssProbeError"

  constructor(
    readonly code: XssProbeErrorCode,
    message: string,
  ) {
    super(message)
  }
}

/** One execution report, as received over the binding. */
export interface XssExecutionHit {
  /** Nonce the page-side probe reported. Must equal the run's nonce. */
  nonce: string
  /** URL of the page that executed the payload. */
  url: string
  /** Free-form marker from the payload call site (`onerror`, `onload`, …). */
  detail: string
  /** When Node received the report. */
  at: string
  /** The Playwright page object that reported, when the binding provides it. */
  page?: unknown
}

/** The slice of `BrowserContext` the probe needs (kept small for tests). */
export interface XssProbeContext {
  exposeBinding?: (name: string, callback: XssBindingCallback) => unknown
  addInitScript?: (script: { content: string }) => unknown
}

type XssBindingSource = { page?: { url?: () => string } }

export type XssBindingCallback = (source: XssBindingSource, payload: unknown) => unknown

/** A nonce unique to one verification run. */
export function createXssNonce(): string {
  return `argus-xss-${randomBytes(16).toString("hex")}`
}

function assertNonce(nonce: string): void {
  if (!/^[A-Za-z0-9_-]{8,}$/.test(nonce)) {
    throw new XssProbeError("invalid-nonce", `XSS nonce is not usable as a page token: ${nonce}`)
  }
}

/**
 * The script installed before navigation. It defines the page-side entry point
 * the payload calls and forwards `{nonce, detail}` to the Node binding. The
 * nonce lives in this closure, so a page that merely *contains* the payload
 * text has no way to produce a matching report.
 */
export function xssProbeInitScript(nonce: string): string {
  assertNonce(nonce)
  const nonceJson = JSON.stringify(nonce)
  return `(() => {
  const nonce = ${nonceJson};
  const send = (detail) => {
    try {
      const hit = {
        nonce: nonce,
        detail: detail && typeof detail === "object" && detail.where ? String(detail.where) : String(detail ?? ""),
        href: String(window.location.href),
      };
      if (typeof window.${XSS_HIT_BINDING} === "function") window.${XSS_HIT_BINDING}(hit);
    } catch (error) {}
  };
  try {
    Object.defineProperty(window, ${JSON.stringify(XSS_EXECUTION_GLOBAL)}, {
      value: send,
      configurable: false,
      enumerable: false,
      writable: false,
    });
  } catch (error) {
    window.${XSS_EXECUTION_GLOBAL} = send;
  }
})();`
}

/**
 * The payload the verifier injects. It carries the nonce, so the only way a
 * matching report can arrive is the browser executing this attribute handler.
 */
export function xssProbePayload(nonce: string): string {
  assertNonce(nonce)
  return `<img src=x onerror="${XSS_EXECUTION_GLOBAL}({where:'onerror',nonce:'${nonce}'})">`
}

/**
 * Resolve the payload for a run.
 *
 * With no template the verifier uses its own nonce-bearing probe. A supplied
 * template is only accepted when it has the `{{nonce}}` placeholder *and* calls
 * the probe entry point with it — anything else would be a payload whose
 * execution the verifier cannot distinguish from reflected text, so it is
 * refused with a clear error instead of being reported as a pass.
 */
export function resolveXssPayload(template: string | undefined, nonce: string): string {
  assertNonce(nonce)
  if (!template || template.trim() === "") return xssProbePayload(nonce)

  if (!template.includes(XSS_NONCE_PLACEHOLDER)) {
    throw new XssProbeError(
      "payload-without-nonce",
      `XSS payload template must contain ${XSS_NONCE_PLACEHOLDER} so execution can be attributed to this run`,
    )
  }
  const resolved = template.split(XSS_NONCE_PLACEHOLDER).join(nonce)
  if (!resolved.includes(XSS_EXECUTION_GLOBAL)) {
    throw new XssProbeError(
      "payload-without-probe",
      `XSS payload template must call ${XSS_EXECUTION_GLOBAL}(…) — reflecting a nonce is not execution`,
    )
  }
  return resolved
}

function normalizeHit(payload: unknown, source: XssBindingSource | undefined): XssExecutionHit {
  const record = (payload ?? {}) as { nonce?: unknown; detail?: unknown; href?: unknown }
  const page = source?.page
  const url = page?.url?.() ?? (typeof record.href === "string" ? record.href : "")
  return {
    nonce: typeof record.nonce === "string" ? record.nonce : "",
    url,
    detail: typeof record.detail === "string" ? record.detail : "",
    at: new Date().toISOString(),
    ...(page ? { page } : {}),
  }
}

/**
 * Install the probe on a context before anything is navigated.
 *
 * Fails closed (`probe-not-installed`) when the context cannot expose a binding
 * or run an init script: without both, execution cannot be observed, and a
 * verifier that cannot observe execution must not report a result either way.
 */
export async function installXssProbe(
  context: XssProbeContext,
  nonce: string,
  onHit: (hit: XssExecutionHit) => void,
): Promise<void> {
  assertNonce(nonce)
  if (typeof context?.exposeBinding !== "function" || typeof context?.addInitScript !== "function") {
    throw new XssProbeError(
      "probe-not-installed",
      "browser context cannot install the XSS execution probe (exposeBinding/addInitScript missing)",
    )
  }

  await context.exposeBinding(XSS_HIT_BINDING, (source, payload) => {
    const hit = normalizeHit(payload, source)
    if (hit.nonce) onHit(hit)
  })
  await context.addInitScript({ content: xssProbeInitScript(nonce) })
}
