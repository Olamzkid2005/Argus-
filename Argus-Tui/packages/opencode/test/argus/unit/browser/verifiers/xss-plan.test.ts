import { describe, expect, test } from "bun:test"
import {
  XssPlanError,
  withQueryPayload,
  xssInjectionPlan,
  xssInjectionPointForFinding,
} from "../../../../../src/argus/browser/verifiers/xss-plan"

const TARGET = "https://app.example.com"

function expectPlanError(fn: () => unknown, code: XssPlanError["code"]): void {
  let caught: unknown
  try {
    fn()
  } catch (error) {
    caught = error
  }
  expect(caught).toBeInstanceOf(XssPlanError)
  if (!(caught instanceof XssPlanError)) throw new Error("expected XssPlanError")
  expect(caught.code).toBe(code)
}

describe("xssInjectionPointForFinding", () => {
  test("uses the finding's discovered endpoint and query parameter", () => {
    const plan = xssInjectionPointForFinding(
      { id: "find-xss-9", url: "https://app.example.com/search?q=test" },
      TARGET,
    )
    expect(plan.url).toBe("https://app.example.com/search?q=test")
    expect(plan.parameter).toBe("q")
    expect(plan.method).toBe("GET")
    expect(plan.encoding).toBe("query")
    expect(plan.victimUrl).toBe(plan.url)
    expect(plan.source).toBe("finding")
    expect(plan.evidenceRef).toBe("finding:find-xss-9")
  })

  test("resolves a relative discovered endpoint against the target", () => {
    const plan = xssInjectionPointForFinding({ id: "f", url: "/profile?bio=hi" }, TARGET)
    expect(plan.url).toBe("https://app.example.com/profile?bio=hi")
    expect(plan.parameter).toBe("bio")
  })

  test("accepts a discovered POST parameter with the method and encoding discovery recorded", () => {
    const plan = xssInjectionPointForFinding(
      { id: "f", url: "https://app.example.com/comments" },
      TARGET,
      { parameter: "comment", method: "POST", encoding: "form" },
    )
    expect(plan.parameter).toBe("comment")
    expect(plan.method).toBe("POST")
    expect(plan.encoding).toBe("form")
  })

  test("an operator-supplied endpoint is recorded as operator evidence", () => {
    const plan = xssInjectionPointForFinding(
      { id: "f" },
      TARGET,
      { endpoint: "https://app.example.com/search?q=x" },
    )
    expect(plan.source).toBe("operator")
    expect(plan.evidenceRef).toBe("finding:f")
  })

  test("a discovered victim page is kept separate from the injection endpoint", () => {
    const plan = xssInjectionPointForFinding(
      { id: "f", url: "https://app.example.com/comments" },
      TARGET,
      { parameter: "comment", method: "POST", encoding: "form", victimUrl: "https://app.example.com/posts/1" },
    )
    expect(plan.url).toBe("https://app.example.com/comments")
    expect(plan.victimUrl).toBe("https://app.example.com/posts/1")
  })
})

describe("xssInjectionPlan fail-closed rule", () => {
  test("refuses a finding with no discovered endpoint", () => {
    expectPlanError(() => xssInjectionPointForFinding({ id: "f" }, TARGET), "endpoint-missing")
  })

  test("refuses a non-http(s) endpoint", () => {
    expectPlanError(
      () => xssInjectionPlan({ endpoint: "javascript:alert(1)", evidenceRef: "finding:f" }, TARGET),
      "unstructured-endpoint",
    )
  })

  test("refuses an endpoint on another origin", () => {
    expectPlanError(
      () => xssInjectionPlan({ endpoint: "https://evil.example/search?q=1", evidenceRef: "finding:f" }, TARGET),
      "endpoint-out-of-scope",
    )
  })

  test("refuses an endpoint with no parameter and no discovery record", () => {
    expectPlanError(
      () => xssInjectionPlan({ endpoint: "https://app.example.com/search", evidenceRef: "finding:f" }, TARGET),
      "parameter-missing",
    )
  })

  test("refuses an ambiguous query string instead of picking a parameter", () => {
    expectPlanError(
      () =>
        xssInjectionPlan(
          { endpoint: "https://app.example.com/search?q=1&lang=en", evidenceRef: "finding:f" },
          TARGET,
        ),
      "ambiguous-parameter",
    )
  })

  test("refuses a POST parameter without the method", () => {
    expectPlanError(
      () =>
        xssInjectionPlan(
          { endpoint: "https://app.example.com/comments", parameter: "comment", evidenceRef: "finding:f" },
          TARGET,
        ),
      "method-missing",
    )
  })

  test("refuses a GET parameter that the discovered URL does not contain", () => {
    expectPlanError(
      () =>
        xssInjectionPlan(
          { endpoint: "https://app.example.com/search", parameter: "q", method: "GET", evidenceRef: "finding:f" },
          TARGET,
        ),
      "parameter-not-in-endpoint",
    )
  })

  test("refuses an unsupported method", () => {
    expectPlanError(
      () =>
        xssInjectionPlan(
          { endpoint: "https://app.example.com/search?q=1", method: "PUT", evidenceRef: "finding:f" },
          TARGET,
        ),
      "unsupported-method",
    )
  })

  test("refuses an unsupported payload encoding", () => {
    expectPlanError(
      () =>
        xssInjectionPlan(
          {
            endpoint: "https://app.example.com/comments",
            parameter: "comment",
            method: "POST",
            encoding: "json",
            evidenceRef: "finding:f",
          },
          TARGET,
        ),
      "unsupported-encoding",
    )
  })

  test("refuses a victim page on another origin", () => {
    expectPlanError(
      () =>
        xssInjectionPlan(
          {
            endpoint: "https://app.example.com/search?q=1",
            victimUrl: "https://evil.example/view",
            evidenceRef: "finding:f",
          },
          TARGET,
        ),
      "victim-url-out-of-scope",
    )
  })

  test("refuses an injection point with no evidence behind it", () => {
    expectPlanError(
      () => xssInjectionPlan({ endpoint: "https://app.example.com/search?q=1" }, TARGET),
      "missing-evidence",
    )
  })
})

describe("withQueryPayload", () => {
  test("places the payload in the discovered parameter and keeps the others", () => {
    const url = withQueryPayload(
      { url: "https://app.example.com/search?q=test&lang=en", parameter: "q" },
      "<img src=x onerror=alert(1)>",
    )
    const parsed = new URL(url)
    expect(parsed.searchParams.get("q")).toBe("<img src=x onerror=alert(1)>")
    expect(parsed.searchParams.get("lang")).toBe("en")
  })
})
