import { describe, expect, test } from "bun:test"
import { mkdtempSync, writeFileSync, rmSync } from "fs"
import { join } from "path"
import { tmpdir } from "os"
import { CredentialStore } from "../../../src/argus/engagement/credentials"

function makeTempCredsPath(): string {
  return join(mkdtempSync(join(tmpdir(), "argus-creds-test-")), "creds.json")
}

describe("CredentialStore getDefaultCredentials", () => {
  test("returns null when no roles exist", () => {
    const path = makeTempCredsPath()
    try {
      const store = new CredentialStore(path)
      store.load(path)
      expect(store.getDefaultCredentials()).toBeNull()
    } finally {
      try { rmSync(join(path, ".."), { recursive: true, force: true }) } catch {}
    }
  })

  test("returns the default_role when set", () => {
    const path = makeTempCredsPath()
    try {
      const store = new CredentialStore(path)
      store.save({ roles: { admin: { username: "admin", password: "secret" }, user: { username: "user", password: "pass" } }, default_role: "admin" })
      const creds = store.getDefaultCredentials()
      expect(creds).toEqual({ username: "admin", password: "secret" })
    } finally {
      try { rmSync(join(path, ".."), { recursive: true, force: true }) } catch {}
    }
  })

  test("returns alphabetically first role when no default_role", () => {
    const path = makeTempCredsPath()
    try {
      const store = new CredentialStore(path)
      store.save({ roles: { admin: { username: "admin", password: "secret" }, user: { username: "user", password: "pass" } } })
      const creds = store.getDefaultCredentials()
      expect(creds).toEqual({ username: "admin", password: "secret" })
    } finally {
      try { rmSync(join(path, ".."), { recursive: true, force: true }) } catch {}
    }
  })

  test("deterministic regardless of role insertion order", () => {
    const path = makeTempCredsPath()
    try {
      const store = new CredentialStore(path)
      const roles = { z_admin: { username: "z", password: "p1" }, a_admin: { username: "a", password: "p2" }, m_role: { username: "m", password: "p3" } }
      store.save({ roles })
      const creds = store.getDefaultCredentials()
      expect(creds).toEqual({ username: "a", password: "p2" })
    } finally {
      try { rmSync(join(path, ".."), { recursive: true, force: true }) } catch {}
    }
  })

  test("single role returns that role even without default_role", () => {
    const path = makeTempCredsPath()
    try {
      const store = new CredentialStore(path)
      store.save({ roles: { admin: { username: "admin", password: "secret" } } })
      const creds = store.getDefaultCredentials()
      expect(creds).toEqual({ username: "admin", password: "secret" })
    } finally {
      try { rmSync(join(path, ".."), { recursive: true, force: true }) } catch {}
    }
  })

  test(".sort() ensures consistent alphabetical order", () => {
    const roles = ["z_role", "a_role", "m_role"]
    const sorted = roles.sort()
    expect(sorted).toEqual(["a_role", "m_role", "z_role"])
  })

  test("getDefaultCredentials returns null when only default_role references a nonexistent role", () => {
    const path = makeTempCredsPath()
    try {
      const store = new CredentialStore(path)
      store.load(path)
      ;(store as any).data = { roles: {}, default_role: "missing" }
      const creds = store.getDefaultCredentials()
      expect(creds).toBeNull()
    } finally {
      try { rmSync(join(path, ".."), { recursive: true, force: true }) } catch {}
    }
  })

  test("getDefaultCredentials for undefined default_role and empty roles returns null", () => {
    const path = makeTempCredsPath()
    try {
      const store = new CredentialStore(path)
      store.load(path)
      ;(store as any).data = { roles: {} }
      expect(store.getDefaultRole()).toBeUndefined()
      expect(store.getDefaultCredentials()).toBeNull()
    } finally {
      try { rmSync(join(path, ".."), { recursive: true, force: true }) } catch {}
    }
  })
})
