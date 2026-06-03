import { describe, expect, test, beforeAll, afterAll } from "bun:test"
import { mkdtempSync, rmSync, writeFileSync } from "fs"
import { join } from "path"
import { tmpdir } from "os"
import { CredentialStore } from "../../../src/argus/engagement/credentials"

let tmpDir: string

beforeAll(() => {
  tmpDir = mkdtempSync(join(tmpdir(), "argus-cred-test-"))
})

afterAll(() => {
  rmSync(tmpDir, { recursive: true, force: true })
})

function credPath(name: string): string {
  return join(tmpDir, name)
}

const adminCreds = { roles: { admin: { username: "admin", password: "admin123" }, user: { username: "user", password: "user123" } }, default_role: "admin" }
const singleRole = { roles: { admin: { username: "a", password: "p" } } }
const noDefault = { roles: { first: { username: "f", password: "fp" }, second: { username: "s", password: "sp" } } }

describe("CredentialStore", () => {
  test("load() returns empty roles when file doesn't exist", () => {
    const store = new CredentialStore(join(tmpDir, "nonexistent.json"))
    const result = store.load()
    expect(result.roles).toEqual({})
  })

  test("load(filePath) reads credentials from a JSON file", () => {
    const path = credPath("read-test.json")
    writeFileSync(path, JSON.stringify(adminCreds))
    const store = new CredentialStore()
    const result = store.load(path)
    expect(result.roles.admin).toEqual({ username: "admin", password: "admin123" })
    expect(result.roles.user).toEqual({ username: "user", password: "user123" })
    expect(result.default_role).toBe("admin")
  })

  test("load() handles malformed JSON gracefully (returns empty roles)", () => {
    const path = credPath("bad.json")
    writeFileSync(path, "{ invalid json }")
    const store = new CredentialStore()
    const result = store.load(path)
    expect(result.roles).toEqual({})
  })

  test("getCredentials(role) returns null for unknown role", () => {
    const path = credPath("unknown-role.json")
    writeFileSync(path, JSON.stringify(singleRole))
    const store = new CredentialStore()
    store.load(path)
    expect(store.getCredentials("nonexistent")).toBeNull()
  })

  test("getCredentials(role) returns entry for known role", () => {
    const path = credPath("known-role.json")
    writeFileSync(path, JSON.stringify(adminCreds))
    const store = new CredentialStore()
    store.load(path)
    const creds = store.getCredentials("admin")
    expect(creds).toEqual({ username: "admin", password: "admin123" })
  })

  test("listRoles() returns all role names", () => {
    const path = credPath("list-roles.json")
    writeFileSync(path, JSON.stringify(adminCreds))
    const store = new CredentialStore()
    store.load(path)
    const roles = store.listRoles()
    expect(roles).toContain("admin")
    expect(roles).toContain("user")
  })

  test("getDefaultRole() returns undefined when not set", () => {
    const path = credPath("no-default.json")
    writeFileSync(path, JSON.stringify(singleRole))
    const store = new CredentialStore()
    store.load(path)
    expect(store.getDefaultRole()).toBeUndefined()
  })

  test("getDefaultRole() returns default role when configured", () => {
    const path = credPath("with-default.json")
    writeFileSync(path, JSON.stringify(adminCreds))
    const store = new CredentialStore()
    store.load(path)
    expect(store.getDefaultRole()).toBe("admin")
  })

  test("getDefaultCredentials() returns default role's credentials", () => {
    const path = credPath("default-creds.json")
    writeFileSync(path, JSON.stringify(adminCreds))
    const store = new CredentialStore()
    store.load(path)
    const creds = store.getDefaultCredentials()
    expect(creds).toEqual({ username: "admin", password: "admin123" })
  })

  test("getDefaultCredentials() returns first role when no default set", () => {
    const path = credPath("first-role.json")
    writeFileSync(path, JSON.stringify(noDefault))
    const store = new CredentialStore()
    store.load(path)
    const creds = store.getDefaultCredentials()
    expect(creds).toEqual({ username: "f", password: "fp" })
  })

  test("save() writes credentials file to disk", () => {
    const path = credPath("saved.json")
    const store = new CredentialStore()
    store.save({ roles: { editor: { username: "edit", password: "edit123" } }, default_role: "editor" }, path)
    const raw = require("fs").readFileSync(path, "utf-8")
    const parsed = JSON.parse(raw)
    expect(parsed.roles.editor.username).toBe("edit")
    expect(parsed.default_role).toBe("editor")
  })

  test("save() creates parent directories if needed", () => {
    const path = join(tmpDir, "nested", "sub", "creds.json")
    const store = new CredentialStore()
    store.save({ roles: { deep: { username: "d", password: "dp" } } }, path)
    const raw = require("fs").readFileSync(path, "utf-8")
    const parsed = JSON.parse(raw)
    expect(parsed.roles.deep.username).toBe("d")
  })

  test("static defaultPath() returns expected path", () => {
    const path = CredentialStore.defaultPath()
    expect(path).toMatch(/\.argus[/\\]credentials\.json$/)
  })
})
