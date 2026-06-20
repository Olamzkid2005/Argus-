import { readFileSync, writeFileSync, chmodSync, existsSync, mkdirSync, statSync } from "fs"
import { join } from "path"
import { homedir } from "os"

export interface CredentialEntry {
  username: string
  password: string
}

export interface CredentialFile {
  roles: Record<string, CredentialEntry>
  default_role?: string
}

const DEFAULT_CREDS_PATH = join(homedir(), ".argus", "credentials.json")

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
      this.data = JSON.parse(readFileSync(resolved, "utf-8")) as CredentialFile
      if (!this.data.roles) this.data.roles = {}
      try {
        const stats = statSync(resolved)
        if (stats.mode & 0o077) {
          console.warn(`[Argus] WARNING: Credentials file ${resolved} has world-readable permissions (${(stats.mode & 0o777).toString(8)}). Run: chmod 0600 "${resolved}"`)
        }
      } catch { /* stat check best-effort */ }
    } catch {
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
    if (roles.length > 0) return this.getCredentials(roles[0])
    return null
  }

  /** Future: migrate to OS keychain integration */
  clear(): void {
    this.data = { roles: {} }
  }

  save(data: CredentialFile, filePath?: string): void {
    const resolved = filePath ?? this.path ?? DEFAULT_CREDS_PATH
    const dir = join(resolved, "..")
    if (!existsSync(dir)) mkdirSync(dir, { recursive: true })
    writeFileSync(resolved, JSON.stringify(data, null, 2))
    chmodSync(resolved, 0o600)
    this.data = data
  }

  static defaultPath(): string {
    return DEFAULT_CREDS_PATH
  }
}
