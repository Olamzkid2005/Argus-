import { describe, expect, test } from "bun:test"
import { isAccessDenied } from "../../../../src/argus/browser/login"

describe("isAccessDenied", () => {
  test("Returns true for '403 Forbidden' text", () => {
    expect(isAccessDenied("403 Forbidden")).toBe(true)
  })

  test("Returns true for '401 Unauthorized'", () => {
    expect(isAccessDenied("401 Unauthorized")).toBe(true)
  })

  test("Returns true for 'access denied'", () => {
    expect(isAccessDenied("access denied")).toBe(true)
  })

  test("Returns true for 'forbidden'", () => {
    expect(isAccessDenied("forbidden")).toBe(true)
  })

  test("Returns true for 'unauthorized' and 'not authorized'", () => {
    expect(isAccessDenied("unauthorized")).toBe(true)
    expect(isAccessDenied("not authorized")).toBe(true)
  })

  test("Returns true for 'insufficient permissions'", () => {
    expect(isAccessDenied("insufficient permissions")).toBe(true)
  })

  test("Returns false for normal page content", () => {
    expect(
      isAccessDenied(
        "<html><body><h1>Welcome to the dashboard</h1></body></html>",
      ),
    ).toBe(false)
  })

  test("Returns false for empty string", () => {
    expect(isAccessDenied("")).toBe(false)
  })

  test("Is case insensitive", () => {
    expect(isAccessDenied("FORBIDDEN")).toBe(true)
    expect(isAccessDenied("Access Denied")).toBe(true)
    expect(isAccessDenied("UNAUTHORIZED")).toBe(true)
    expect(isAccessDenied("Not Authorized")).toBe(true)
  })
})
