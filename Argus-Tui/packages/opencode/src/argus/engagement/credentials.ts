import { readFileSync, writeFileSync, existsSync, mkdirSync } from "fs"
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
    } catch {
      this.data = { roles: {} }
    }
    return this.data
  }

  getCredentials(role: string): CredentialEntry | null {
    return this.data.roles[role] ?? null
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

  save(data: CredentialFile, filePath?: string): void {
    const resolved = filePath ?? this.path ?? DEFAULT_CREDS_PATH
    const dir = join(resolved, "..")
    if (!existsSync(dir)) mkdirSync(dir, { recursive: true })
    writeFileSync(resolved, JSON.stringify(data, null, 2))
    this.data = data
  }

  static defaultPath(): string {
    return DEFAULT_CREDS_PATH
  }
}
