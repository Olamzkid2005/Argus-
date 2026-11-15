/**
 * The XSS injection plan — Stage 4.3 item 2.
 *
 * A stored/reflected XSS check used to guess where to inject: the workflow
 * navigated to `${target}/contact` and `verify` reloaded the engagement root,
 * then filled every visible input and searched the victim page for marker text.
 * That tests whatever page happened to exist, not the endpoint discovery found.
 *
 * This module is the one place that turns a discovered endpoint (a finding's
 * structured `url`, plus whatever an operator/scan recorded about the parameter,
 * method and encoding) into an injection point. It refuses to invent any part:
 * no endpoint, no parameter, an ambiguous query string, an out-of-scope host or
 * an unsupported method/encoding each raise a distinguishable `XssPlanError`,
 * and the caller records the finding as unsupported instead of testing a guess.
 */

/** Where the endpoint and parameter were learned. */
export type XssInjectionSource = "finding" | "operator"

export type XssHttpMethod = "GET" | "POST"
export type XssPayloadEncoding = "query" | "form"

/** One discovered, fully-specified injection point. */
export interface XssInjectionPoint {
  /** Absolute URL of the discovered endpoint. */
  url: string
  /** Name of the injectable parameter at that endpoint. */
  parameter: string
  method: XssHttpMethod
  encoding: XssPayloadEncoding
  /** Page the victim views; defaults to the discovered endpoint itself. */
  victimUrl: string
  source: XssInjectionSource
  /** What observation backs this endpoint/parameter (finding id, scan tool, …). */
  evidenceRef: string
}

export type XssPlanErrorCode =
  | "endpoint-missing"
  | "unstructured-endpoint"
  | "endpoint-out-of-scope"
  | "parameter-missing"
  | "ambiguous-parameter"
  | "parameter-not-in-endpoint"
  | "method-missing"
  | "unsupported-method"
  | "unsupported-encoding"
  | "victim-url-unstructured"
  | "victim-url-out-of-scope"
  | "missing-evidence"

/** A verification target that cannot be derived honestly is refused. */
export class XssPlanError extends Error {
  override readonly name = "XssPlanError"

  constructor(
    readonly code: XssPlanErrorCode,
    message: string,
  ) {
    super(message)
  }
}

/** What a scan, operator or finding says about the injection point. */
export interface XssDiscovery {
  endpoint?: string
  parameter?: string
  method?: string
  encoding?: string
  victimUrl?: string
  /** Overrides the derived source when the endpoint came from the operator. */
  source?: XssInjectionSource
  evidenceRef?: string
}

function parseHttpUrl(value: string, base: string): URL | null {
  try {
    const url = new URL(value, base)
    if (url.protocol !== "http:" && url.protocol !== "https:") return null
    return url
  } catch {
    return null
  }
}

function originOf(value: string): string | null {
  try {
    const url = new URL(value)
    return url.protocol === "http:" || url.protocol === "https:" ? url.origin : null
  } catch {
    return null
  }
}

function requireSameOrigin(url: URL, targetOrigin: string | null, code: "endpoint-out-of-scope" | "victim-url-out-of-scope", label: string): void {
  if (targetOrigin && url.origin !== targetOrigin) {
    throw new XssPlanError(
      code,
      `${label} ${url.href} is outside the engagement target origin ${targetOrigin}`,
    )
  }
}

function queryParameters(url: URL): string[] {
  return Array.from(new Set(url.searchParams.keys()))
}

function normalizeMethod(method: string | undefined): XssHttpMethod | undefined {
  if (!method) return undefined
  const upper = method.trim().toUpperCase()
  if (upper !== "GET" && upper !== "POST") {
    throw new XssPlanError(
      "unsupported-method",
      `XSS verification supports GET and POST, not ${method}`,
    )
  }
  return upper
}

function normalizeEncoding(encoding: string | undefined): XssPayloadEncoding | undefined {
  if (!encoding) return undefined
  const lower = encoding.trim().toLowerCase()
  if (lower !== "query" && lower !== "form") {
    throw new XssPlanError(
      "unsupported-encoding",
      `XSS verification supports query and form payload encoding, not ${encoding}`,
    )
  }
  return lower
}

/**
 * Build the validated injection point, or explain precisely what is missing.
 *
 * `targetUrl` is the engagement target, used to resolve a relative endpoint and
 * to refuse a discovered URL on another origin.
 */
export function xssInjectionPlan(discovery: XssDiscovery | undefined, targetUrl: string): XssInjectionPoint {
  const targetOrigin = originOf(targetUrl)

  const endpointRaw = discovery?.endpoint?.trim()
  if (!endpointRaw) {
    throw new XssPlanError(
      "endpoint-missing",
      "XSS verification requires a discovered endpoint; this finding has none",
    )
  }
  const endpoint = parseHttpUrl(endpointRaw, targetUrl)
  if (!endpoint) {
    throw new XssPlanError(
      "unstructured-endpoint",
      `XSS endpoint ${endpointRaw} is not a usable http(s) URL`,
    )
  }
  requireSameOrigin(endpoint, targetOrigin, "endpoint-out-of-scope", "XSS endpoint")

  // The parameter must come from the discovery result: either the discovered
  // query string carries it, or the caller names it explicitly (e.g. a POST
  // body field a scan recorded). It is never assumed.
  const discoveredParameters = queryParameters(endpoint)
  const explicitParameter = discovery?.parameter?.trim() || undefined
  let parameter: string
  if (explicitParameter) {
    parameter = explicitParameter
  } else if (discoveredParameters.length === 1) {
    parameter = discoveredParameters[0]
  } else if (discoveredParameters.length === 0) {
    throw new XssPlanError(
      "parameter-missing",
      `XSS endpoint ${endpoint.href} has no query parameter and none was supplied by discovery`,
    )
  } else {
    throw new XssPlanError(
      "ambiguous-parameter",
      `XSS endpoint ${endpoint.href} has several parameters (${discoveredParameters.join(", ")}); ` +
        "the injectable one must be supplied by discovery",
    )
  }

  const parameterInQuery = discoveredParameters.includes(parameter)
  const discoveredMethod = normalizeMethod(discovery?.method)
  let method: XssHttpMethod
  if (discoveredMethod) {
    method = discoveredMethod
  } else if (parameterInQuery) {
    // A parameter found in the discovered URL is a GET parameter; that is read
    // from the observation, not guessed.
    method = "GET"
  } else {
    throw new XssPlanError(
      "method-missing",
      `XSS parameter "${parameter}" is not in the discovered URL query, so the request method must be supplied`,
    )
  }

  const discoveredEncoding = normalizeEncoding(discovery?.encoding)
  const encoding: XssPayloadEncoding = discoveredEncoding ?? (method === "GET" ? "query" : "form")
  if (method === "GET" && encoding !== "query") {
    throw new XssPlanError(
      "unsupported-encoding",
      `GET XSS injection uses query encoding, not ${encoding}`,
    )
  }
  if (method === "POST" && encoding !== "form") {
    throw new XssPlanError(
      "unsupported-encoding",
      `POST XSS injection uses form encoding, not ${encoding}`,
    )
  }
  if (method === "GET" && !parameterInQuery) {
    throw new XssPlanError(
      "parameter-not-in-endpoint",
      `XSS endpoint ${endpoint.href} does not contain the discovered parameter "${parameter}"`,
    )
  }

  const victimRaw = discovery?.victimUrl?.trim()
  const victim = victimRaw ? parseHttpUrl(victimRaw, targetUrl) : endpoint
  if (!victim) {
    throw new XssPlanError(
      "victim-url-unstructured",
      `victim view ${victimRaw} is not a usable http(s) URL`,
    )
  }
  requireSameOrigin(victim, targetOrigin, "victim-url-out-of-scope", "XSS victim view")

  const evidenceRef = discovery?.evidenceRef?.trim()
  if (!evidenceRef) {
    throw new XssPlanError(
      "missing-evidence",
      "XSS verification requires the evidence reference that identified the endpoint",
    )
  }

  return {
    url: endpoint.href,
    parameter,
    method,
    encoding,
    victimUrl: victim.href,
    source: discovery?.source ?? "operator",
    evidenceRef,
  }
}

/**
 * The injection point for a finding: its structured `url` is the endpoint, and
 * an operator/scan override may add the parameter, method, encoding or the
 * separate victim page. Nothing is read out of free-text descriptions.
 */
export function xssInjectionPointForFinding(
  finding: { id?: string; url?: string },
  targetUrl: string,
  override?: XssDiscovery,
): XssInjectionPoint {
  const endpoint = override?.endpoint ?? finding.url
  return xssInjectionPlan(
    {
      endpoint,
      parameter: override?.parameter,
      method: override?.method,
      encoding: override?.encoding,
      victimUrl: override?.victimUrl,
      source: override?.endpoint ? "operator" : "finding",
      evidenceRef: override?.evidenceRef ?? `finding:${finding.id ?? "unknown"}`,
    },
    targetUrl,
  )
}

/** Merge the payload into the plan's query parameter (GET/query injection). */
export function withQueryPayload(plan: Pick<XssInjectionPoint, "url" | "parameter">, payload: string): string {
  const url = new URL(plan.url)
  url.searchParams.set(plan.parameter, payload)
  return url.href
}
