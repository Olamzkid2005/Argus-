import { describe, expect, test } from "bun:test"
import { mkdtempSync, writeFileSync, rmSync } from "fs"
import { join } from "path"
import { tmpdir } from "os"
import { CredentialStore } from "../../../src/argus/engagement/credentials"
import { EncryptionManager } from "../../../src/argus/storage/encryption"

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

describe("CredentialStore warning hygiene", () => {
  const singleRole = { roles: { admin: { username: "a", password: "p" } } }

  /** A throwaway directory per test, so each path is unique and the module
   *  level warn-once set cannot leak between tests. */
  const credPath = (name: string): string =>
    join(mkdtempSync(join(tmpdir(), "argus-creds-warn-")), name)

  /**
   * Force the master-key lookup to a known answer.
   *
   * Without this the test depends on whether *this machine* has a key in the
   * OS keychain: with one, a plaintext file takes the decrypt-failure path
   * instead of the plaintext path, and the assertions flip.
   */
  function withMasterKey<T>(key: Buffer | null, fn: () => T): T {
    const original = EncryptionManager.loadKeySync
    ;(EncryptionManager as any).loadKeySync = () => key
    try {
      return fn()
    } finally {
      ;(EncryptionManager as any).loadKeySync = original
    }
  }

  function captureWarnings<T>(fn: () => T): { warnings: string[]; result: T } {
    const warnings: string[] = []
    const origWarn = console.warn
    console.warn = ((msg: string) => { warnings.push(msg) }) as any
    try {
      return { warnings, result: fn() }
    } finally {
      console.warn = origWarn
    }
  }

  test("the plaintext warning is emitted once per path, not once per load", () => {
    const path = credPath("warn-once.json")
    writeFileSync(path, JSON.stringify(singleRole))

    const { warnings } = withMasterKey(null, () =>
      captureWarnings(() => {
        const store = new CredentialStore(path)
        for (let i = 0; i < 5; i++) store.load()
      }),
    )

    const plaintextWarnings = warnings.filter((w) => w.includes("stored in plaintext"))
    expect(plaintextWarnings).toHaveLength(1)
  })

  test("a differently-named path still warns on its own", () => {
    const first = credPath("warn-once-a.json")
    const second = credPath("warn-once-b.json")
    writeFileSync(first, JSON.stringify(singleRole))
    writeFileSync(second, JSON.stringify(singleRole))

    const { warnings } = withMasterKey(null, () =>
      captureWarnings(() => {
        new CredentialStore(first).load()
        new CredentialStore(second).load()
      }),
    )

    expect(warnings.filter((w) => w.includes("stored in plaintext"))).toHaveLength(2)
  })

  test("a plaintext file is still read when no master key is available", () => {
    const path = credPath("plaintext-read.json")
    writeFileSync(path, JSON.stringify(singleRole))

    const data = withMasterKey(null, () => new CredentialStore(path).load())
    expect(data.roles.admin).toEqual({ username: "a", password: "p" })
  })

  test("a decrypt failure is reported once per path, not once per load", () => {
    const path = credPath("decrypt-once.json")
    // Not valid JSON under any reading, so this is what a file encrypted with a
    // different master key looks like to `load()`: the decrypt fails, the
    // plaintext fallback fails, and the store resets to empty.
    writeFileSync(path, Buffer.from([0x01, 0x02, 0x03, 0xff, 0xfe]))

    const { warnings } = withMasterKey(Buffer.alloc(32, 7), () =>
      captureWarnings(() => {
        const store = new CredentialStore(path)
        for (let i = 0; i < 4; i++) store.load()
      }),
    )

    // The whole point: four loads, one warning each kind.
    expect(warnings.filter((w) => w.includes("Failed to decrypt"))).toHaveLength(1)
    expect(warnings.filter((w) => w.includes("Failed to parse"))).toHaveLength(1)
  })

  test("an encrypted file that decrypts cleanly does not warn at all", () => {
    const path = credPath("encrypted-clean.json")
    const key = Buffer.alloc(32, 3)
    writeFileSync(path, EncryptionManager.encryptCredentials(Buffer.from(JSON.stringify(singleRole)), key))

    const { warnings, result } = withMasterKey(key, () =>
      captureWarnings(() => new CredentialStore(path).load()),
    )

    expect(result.roles.admin).toEqual({ username: "a", password: "p" })
    expect(warnings.filter((w) => w.includes("plaintext"))).toHaveLength(0)
  })
})
