import { readFileSync, writeFileSync, chmodSync, existsSync, mkdirSync, statSync } from "fs"
import { join } from "path"
import { StoragePaths } from "../storage/paths"
import { EncryptionManager } from "../storage/encryption"

export interface CredentialEntry {
  username: string
  password: string
  /** Optional JWT/token for OAuth or token-based auth (Gap 2.6) */
  authToken?: string
  /** Optional auth cookies for session-based auth fallback */
  authCookies?: Array<{ name: string; value: string; domain: string; path?: string; httpOnly?: boolean; secure?: boolean }>
}

export interface CredentialFile {
  roles: Record<string, CredentialEntry>
  default_role?: string
}

const DEFAULT_CREDS_PATH = StoragePaths.credentials

/**
 * File paths already warned about in this process.
 *
 * `load()` is called on every credential lookup, so the plaintext and
 * permissions warnings repeated once per call: a single assessment produced
 * ~36 copies of the same two lines. Keyed by `resolved|warningKind` so a real
 * change (the file becomes encrypted, or the mode is fixed and then breaks
 * again) still warns.
 */
const _warnedPaths = new Set<string>()

function warnOnce(key: string, message: string): void {
  if (_warnedPaths.has(key)) return
  _warnedPaths.add(key)
  console.warn(message)
}

export class CredentialStore {
  private data: CredentialFile = { roles: {} }

  constructor(private path?: string) {}

  load(filePath?: string): CredentialFile {
    const resolved = filePath ?? this.path ?? DEFAULT_CREDS_PATH
    if (!existsSync(resolved)) {
      this.data = { roles: {} }
      return this.data
    }
    try {
      const rawBytes = readFileSync(resolved)

      // Try to read as binary and decrypt with master key.
      //
      // `loadKeySync()` rather than `getCachedMasterKey()`: the cache TTL is
      // 5 minutes and an assessment runs far longer, so after the first few
      // minutes the cache is always empty. That made every later lookup warn
      // "stored in plaintext", and — worse — made an *encrypted* file fail to
      // decrypt and then be parsed as plaintext, i.e. read as empty.
      // `loadKeySync` only ever reads an existing key; it never mints one.
      const masterKey = EncryptionManager.loadKeySync()
      if (masterKey) {
        try {
          const decrypted = EncryptionManager.decryptCredentials(rawBytes, masterKey)
          this.data = JSON.parse(decrypted.toString("utf-8")) as CredentialFile
          if (!this.data.roles) this.data.roles = {}
          return this.data
        } catch (decryptErr) {
          // Decryption failed — file may be in legacy plaintext format, or it
          // may have been written under a different master key. Log once per
          // path, then fall through to the plaintext read.
          warnOnce(
            `${resolved}|decrypt`,
            `[Argus] WARNING: Failed to decrypt credentials file "${resolved}": ` +
            `${(decryptErr as Error).message}. Falling back to plaintext.`,
          )
        }
      }

      // Legacy plaintext fallback (backward compatible)
      this.data = JSON.parse(rawBytes.toString("utf-8")) as CredentialFile
      if (!this.data.roles) this.data.roles = {}

      // Warn once when the file really is plaintext. Previously this fired
      // whenever the key cache happened to be cold, which is not the same
      // question as "is this file encrypted".
      if (!masterKey && !_isEncryptedPayload(rawBytes)) {
        warnOnce(
          `${resolved}|plaintext`,
          `[Argus] WARNING: Credentials file ${resolved} is stored in plaintext. ` +
          "Run `argus encryption init` to enable encryption at rest.",
        )
      }

      try {
        const stats = statSync(resolved)
        if (stats.mode & 0o077) {
          warnOnce(
            `${resolved}|permissions`,
            `[Argus] WARNING: Credentials file ${resolved} has world-readable permissions ` +
            `(${(stats.mode & 0o777).toString(8)}). Run: chmod 0600 "${resolved}"`,
          )
        }
      } catch { /* stat check best-effort */ }
    } catch (e) {
      warnOnce(
        `${resolved}|parse`,
        `[Argus] WARNING: Failed to parse credentials file — resetting to empty: ${(e as Error).message}`,
      )
      this.data = { roles: {} }
    }
    return this.data
  }

  getCredentials(role: string): CredentialEntry | null {
    return this.data.roles[role] ?? null
  }

  getAllCredentials(): Record<string, CredentialEntry> {
    return { ...this.data.roles }
  }

  listRoles(): string[] {
    return Object.keys(this.data.roles)
  }

  getDefaultRole(): string | undefined {
    return this.data.default_role
  }

  getDefaultCredentials(): CredentialEntry | null {
    const defaultRole = this.data.default_role
    if (defaultRole) return this.getCredentials(defaultRole)
    const roles = this.listRoles()
    if (roles.length > 0) return this.getCredentials(roles.sort()[0])
    return null
  }

  clear(): void {
    this.data = { roles: {} }
  }

  save(data: CredentialFile, filePath?: string): void {
    const resolved = filePath ?? this.path ?? DEFAULT_CREDS_PATH
    const dir = join(resolved, "..")
    if (!existsSync(dir)) mkdirSync(dir, { recursive: true })

    // Same reason as load(): the cache is cold for most of a long run, and a
    // cold cache must not silently downgrade a write to plaintext.
    const masterKey = EncryptionManager.loadKeySync()
    if (masterKey) {
      // Encrypt credentials before writing
      const plaintext = Buffer.from(JSON.stringify(data, null, 2), "utf-8")
      const encrypted = EncryptionManager.encryptCredentials(plaintext, masterKey)
      writeFileSync(resolved, encrypted)
      _warnedPaths.delete(`${resolved}|plaintext`)
    } else {
      // No master key available — write as plaintext with warning
      warnOnce(
        `${resolved}|plaintext-write`,
        `[Argus] WARNING: Saving credentials to ${resolved} in plaintext. ` +
        "Run `argus encryption init` to enable encryption at rest.",
      )
      writeFileSync(resolved, JSON.stringify(data, null, 2))
    }

    chmodSync(resolved, 0o600)
    this.data = data
  }

  static defaultPath(): string {
    return DEFAULT_CREDS_PATH
  }
}

/**
 * Best-effort check for the encrypted credentials envelope.
 *
 * `encryptCredentials` writes a version-prefixed payload, never valid JSON.
 * Distinguishing the two is what lets the plaintext warning be accurate
 * instead of "the master key cache happened to be empty".
 */
function _isEncryptedPayload(raw: Buffer): boolean {
  if (raw.length < 3) return false
  const first = raw[0]
  // Encrypted payloads start with a version byte (or a JSON-incompatible
  // byte). Valid JSON must begin with '{' (0x7b) or whitespace.
  if (first === 0x7b || first === 0x20 || first === 0x09 || first === 0x0a || first === 0x0d) {
    return false
  }
  return true
}
