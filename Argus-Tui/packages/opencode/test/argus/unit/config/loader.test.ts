import { describe, it, expect, mock, beforeEach } from "bun:test"
import { z } from "zod"
import { Confidence } from "../../../../src/argus/shared/types"

const mockExistsSync = mock(() => true)
const mockReadFileSync = mock(() => 'features:\n  browser_verification: true')

mock.module("fs", () => ({
  existsSync: mockExistsSync,
  readFileSync: mockReadFileSync,
}))

const { ConfigLoader } = await import("../../../../src/argus/config/loader")

describe("ConfigLoader", () => {
  beforeEach(() => {
    mockExistsSync.mockReset()
    mockReadFileSync.mockReset()
    mockExistsSync.mockImplementation(() => true)
    mockReadFileSync.mockImplementation(() => 'features:\n  browser_verification: true')
  })

  it("loadFrom() returns defaults when file doesn't exist", () => {
    mockExistsSync.mockImplementation(() => false)
    const result = ConfigLoader.loadFrom("/nonexistent/path.yaml")
    expect(result).toEqual({})
  })

  it("loadFrom() returns defaults when readFileSync throws", () => {
    mockReadFileSync.mockImplementation(() => { throw new Error("ENOENT") })
    const result = ConfigLoader.loadFrom("/some/path.yaml")
    expect(result).toEqual({})
  })

  it("loadFrom() returns defaults when YAML parse fails", () => {
    mockReadFileSync.mockImplementation(() => "{{invalid: yaml: ")
    const result = ConfigLoader.loadFrom("/some/path.yaml")
    expect(result).toEqual({})
  })

  it("loadFrom() returns defaults when parsed is not an object", () => {
    mockReadFileSync.mockImplementation(() => '"just a string"')
    const result = ConfigLoader.loadFrom("/some/path.yaml")
    expect(result).toEqual({})
  })

  it("loadFrom() validates with Zod and returns typed config", () => {
    mockReadFileSync.mockImplementation(() => 'features:\n  browser_verification: true')
    const result = ConfigLoader.loadFrom("/some/path.yaml")
    expect(result.features?.browser_verification).toBe(true)
  })

  it("loadFrom() applies default values for missing evidence fields", () => {
    mockReadFileSync.mockImplementation(() => 'evidence:\n  capture_har: true')
    const result = ConfigLoader.loadFrom("/some/path.yaml")
    expect(result.evidence).toBeDefined()
    expect(result.evidence?.capture_har).toBe(true)
    expect(result.evidence?.retention_days).toBe(30)
    expect(result.evidence?.max_engagement_size_mb).toBe(500)
    expect(result.evidence?.capture_video).toBe(false)
    expect(result.evidence?.capture_threshold).toBe(Confidence.HIGH)
  })

  it("loadProjectConfig() returns valid config matching loadFrom result", () => {
    mockReadFileSync.mockImplementation(() => 'features:\n  browser_verification: true')
    const result = ConfigLoader.loadProjectConfig()
    const expected = ConfigLoader.loadFrom(ConfigLoader.PROJECT_CONFIG_PATH)
    expect(result).toEqual(expected)
  })

  it("loadUserConfig() returns valid config matching loadFrom result", () => {
    mockReadFileSync.mockImplementation(() => 'features:\n  browser_verification: true')
    const result = ConfigLoader.loadUserConfig()
    const expected = ConfigLoader.loadFrom(ConfigLoader.USER_CONFIG_PATH)
    expect(result).toEqual(expected)
  })
})
