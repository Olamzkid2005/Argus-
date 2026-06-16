import { describe, expect, test } from "bun:test"
import { compareObservations } from "../../../../src/argus/browser/observer"
import type { Observation } from "../../../../src/argus/browser/types"

function makeObservation(domSnapshot: string): Observation {
  return {
    url: "https://example.com",
    domSnapshot,
    responseHeaders: {},
    statusCode: 200,
    timestamp: new Date().toISOString(),
  }
}

describe("compareObservations", () => {
  test("Returns changed=false when DOM snapshots are identical", () => {
    const dom = "<html>\n<body>\n<p>Hello</p>\n</body>\n</html>"
    const result = compareObservations(makeObservation(dom), makeObservation(dom))
    expect(result.changed).toBe(false)
    expect(result.additions).toHaveLength(0)
    expect(result.removals).toHaveLength(0)
  })

  test("Returns changed=true and additions when DOM differs", () => {
    const a = makeObservation("<html>\n<body>\n<p>A</p>\n</body>\n</html>")
    const b = makeObservation("<html>\n<body>\n<p>B</p>\n</body>\n</html>")
    const result = compareObservations(a, b)
    expect(result.changed).toBe(true)
    expect(result.additions).toContain("<p>B</p>")
    expect(result.removals).toContain("<p>A</p>")
  })

  test("Returns changed=true and removals when lines are removed", () => {
    const a = makeObservation(
      "<html>\n<body>\n<p>A</p>\n<p>B</p>\n</body>\n</html>",
    )
    const b = makeObservation("<html>\n<body>\n<p>A</p>\n</body>\n</html>")
    const result = compareObservations(a, b)
    expect(result.changed).toBe(true)
    expect(result.additions).toHaveLength(0)
    expect(result.removals).toContain("<p>B</p>")
  })

  test("Handles completely different DOM content", () => {
    const a = makeObservation("line1\nline2")
    const b = makeObservation("line3\nline4")
    const result = compareObservations(a, b)
    expect(result.changed).toBe(true)
    expect(result.additions).toEqual(["line3", "line4"])
    expect(result.removals).toEqual(["line1", "line2"])
  })

  test("Handles empty DOM strings", () => {
    const result = compareObservations(makeObservation(""), makeObservation(""))
    expect(result.changed).toBe(false)
    expect(result.additions).toHaveLength(0)
    expect(result.removals).toHaveLength(0)
  })
})
