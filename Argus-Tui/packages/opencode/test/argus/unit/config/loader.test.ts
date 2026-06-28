import { describe, it, expect, afterAll } from "bun:test"
import { mkdtempSync, writeFileSync, rmSync, mkdirSync } from "fs"
import { join } from "path"
import { tmpdir } from "os"
import { ConfigLoader } from "../../../../src/argus/config/loader"
import { Confidence } from "../../../../src/argus/shared/types"

let tempDir: string | undefined

afterAll(() => {
  if (tempDir) try { rmSync(tempDir, { recursive: true, force: true }) } catch {}
})

function makeDir(): string {
  const dir = mkdtempSync(join(tmpdir(), "config-loader-test-"))
  tempDir = dir
  return dir
}

function makeFile(dir: string, content: string): string {
  const filePath = join(dir, "argus.config.yaml")
  writeFileSync(filePath, content, "utf-8")
  return filePath
}

describe("ConfigLoader", () => {
  it("loadFrom() returns defaults when file doesn't exist", () => {
    const result = ConfigLoader.loadFrom("/nonexistent/path.yaml")
    expect(result).toEqual({})
  })

  it("loadFrom() returns defaults when readFileSync throws", () => {
    const dir = makeDir()
    const dirPath = join(dir, "configdir")
    mkdirSync(dirPath)
    const result = ConfigLoader.loadFrom(dirPath)
    expect(result).toEqual({})
  })

  it("loadFrom() returns defaults when YAML parse fails", () => {
    const dir = makeDir()
    const filePath = makeFile(dir, "{{invalid: yaml: ")
    const result = ConfigLoader.loadFrom(filePath)
    expect(result).toEqual({})
  })

  it("loadFrom() returns defaults when parsed is not an object", () => {
    const dir = makeDir()
    const filePath = makeFile(dir, '"just a string"')
    const result = ConfigLoader.loadFrom(filePath)
    expect(result).toEqual({})
  })

  it("loadFrom() validates with Zod and returns typed config", () => {
    const dir = makeDir()
    const filePath = makeFile(dir, 'features:\n  browser_verification: true')
    const result = ConfigLoader.loadFrom(filePath)
    expect(result.features?.browser_verification).toBe(true)
  })

  it("loadFrom() applies default values for missing evidence fields", () => {
    const dir = makeDir()
    const filePath = makeFile(dir, 'evidence:\n  capture_har: true')
    const result = ConfigLoader.loadFrom(filePath)
    expect(result.evidence).toBeDefined()
    expect(result.evidence?.capture_har).toBe(true)
    expect(result.evidence?.retention_days).toBe(30)
    expect(result.evidence?.max_engagement_size_mb).toBe(500)
    expect(result.evidence?.capture_video).toBe(false)
    expect(result.evidence?.capture_threshold).toBe(Confidence.HIGH)
  })

  it("loadFrom() parses storage.encryption.enabled", () => {
    const dir = makeDir()
    const filePath = makeFile(dir, 'storage:\n  encryption:\n    enabled: true')
    const result = ConfigLoader.loadFrom(filePath)
    expect(result.storage?.encryption?.enabled).toBe(true)
  })

  it("loadFrom() defaults storage.encryption.enabled to false", () => {
    const dir = makeDir()
    const filePath = makeFile(dir, 'features:\n  x: true')
    const result = ConfigLoader.loadFrom(filePath)
    expect(result.storage).toBeUndefined()
  })

  it("loadProjectConfig() returns valid config matching loadFrom result", () => {
    const result = ConfigLoader.loadProjectConfig()
    const expected = ConfigLoader.loadFrom(ConfigLoader.PROJECT_CONFIG_PATH)
    expect(result).toEqual(expected)
  })

  it("loadUserConfig() returns valid config matching loadFrom result", () => {
    const result = ConfigLoader.loadUserConfig()
    const expected = ConfigLoader.loadFrom(ConfigLoader.USER_CONFIG_PATH)
    expect(result).toEqual(expected)
  })
})
