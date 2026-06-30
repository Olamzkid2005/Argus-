import { readFileSync, writeFileSync, chmodSync, existsSync, mkdirSync, statSync } from "fs"
import { join } from "path"
import { StoragePaths } from "../storage/paths"
import { EncryptionManager } from "../storage/encryption"

export interface CredentialEntry {
  username: string
  password: string
}

export interface CredentialFile {
  roles: Record<string, CredentialEntry>
  default_role?: string
}

const DEFAULT_CREDS_PATH = StoragePaths.credentials

export class CredentialStore {
  private data: CredentialFile = { roles: {} }

  constructor(private path?: string) {}

  load(filePath?: string): CredentialFile {
    const resolved = filePath ?? this.path ?? DEFAULT_CREDS_PATH
    if (!existsSync(resolved)) {
      this.data = { roles: {} }
      return this.data
    }
    try {        // Try to read as binary and decrypt with master key
      const masterKey = EncryptionManager.getCachedMasterKey()
      if (masterKey) {
        try {
          const raw = readFileSync(resolved)
          const decrypted = EncryptionManager.decryptCredentials(raw, masterKey)
          this.data = JSON.parse(decrypted.toString("utf-8")) as CredentialFile
          if (!this.data.roles) this.data.roles = {}
          return this.data
        } catch (decryptErr) {
          // Decryption failed — file may be in legacy plaintext format.
          // Log for debugging, then fall through to plaintext read.
          console.warn(
            `[Argus] WARNING: Failed to decrypt credentials file "${resolved}": ` +
            `${(decryptErr as Error).message}. Falling back to plaintext.`,
          )
        }
      }

      // Legacy plaintext fallback (backward compatible)
      this.data = JSON.parse(readFileSync(resolved, "utf-8")) as CredentialFile
      if (!this.data.roles) this.data.roles = {}

      // Warn if running without encryption
      if (!masterKey) {
        console.warn(
          `[Argus] WARNING: Credentials file ${resolved} is stored in plaintext. ` +
          "Run `argus encryption init` to enable encryption at rest.",
        )
      }

      try {
        const stats = statSync(resolved)
        if (stats.mode & 0o077) {
          console.warn(
            `[Argus] WARNING: Credentials file ${resolved} has world-readable permissions ` +
            `(${(stats.mode & 0o777).toString(8)}). Run: chmod 0600 "${resolved}"`,
          )
        }
      } catch { /* stat check best-effort */ }
    } catch (e) {
      console.warn(
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

    const masterKey = EncryptionManager.getCachedMasterKey()
    if (masterKey) {
      // Encrypt credentials before writing
      const plaintext = Buffer.from(JSON.stringify(data, null, 2), "utf-8")
      const encrypted = EncryptionManager.encryptCredentials(plaintext, masterKey)
      writeFileSync(resolved, encrypted)
    } else {
      // No master key available — write as plaintext with warning
      console.warn(
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
