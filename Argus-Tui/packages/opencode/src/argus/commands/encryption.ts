/**
 * Encryption command — manage encryption-at-rest (Item 14c)
 *
 * Subcommands:
 *   init         Generate and store a master key in the OS keychain (idempotent)
 *   status       Show whether a master key exists and encryption is initialized
 *   on           Enable encryption-at-rest (requires initialized master key)
 *   off          Disable encryption-at-rest (stops encrypting new engagements)
 *   export       Export the master key to a file, encrypted with a passphrase
 *   import       Import a master key from a previously exported backup file
 *
 * All actions require macOS Keychain (via EncryptionManager's Bun FFI).
 * Non-macOS platforms will show a clear unsupported error.
 */
import { EncryptionManager, EncryptionError } from "../storage/encryption"
import { EngagementStore } from "../engagement/store"
import { existsSync, readFileSync, writeFileSync, mkdirSync } from "node:fs"
import { join, dirname } from "node:path"
import { StoragePaths } from "../storage/paths"

export interface EncryptionCommandOptions {
  passphrase?: string
  output?: string
  input?: string
  /** Engagement ID for the decrypt action */
  engagement?: string
}

/**
 * Execute an encryption command action.
 *
 * @param action  The subcommand to execute
 * @param opts    Optional parameters (passphrase, output path, input path)
 * @returns       Human-readable output string (written to stdout by the CLI handler)
 */
/**
 * Configure the encryption passphrase for file-based keychain mode.
 * On non-macOS platforms, the passphrase is required for all keychain operations.
 * Falls back to the ARGUS_KEY_PASSPHRASE env var if not provided.
 */
function configurePassphrase(passphrase?: string): void {
  if (passphrase) {
    EncryptionManager.setPassphrase(passphrase)
  }
  // If env var is set, it will be picked up by EncryptionManager.getPassphrase()
}

/**
 * Write a key-value pair to the user's `~/.argus/config.yaml` file.
 * Creates the file with defaults if it doesn't exist.
 * Preserves all existing keys and comments.
 */
function writeUserConfigKey(key: string, value: boolean): void {
  const configPath = StoragePaths.config
  const configDir = dirname(configPath)

  // Ensure the config directory exists
  if (!existsSync(configDir)) {
    mkdirSync(configDir, { recursive: true })
  }

  let content: string
  if (existsSync(configPath)) {
    content = readFileSync(configPath, "utf-8")
  } else {
    content = "# Argus user configuration\n"
  }

  // Update or add the storage.encryption.enabled line
  // Match lines like "storage:" / "  encryption:" / "    enabled: true|false"
  const lines = content.split("\n")
  let storageSection = -1
  let encryptionSection = -1
  let enabledLine = -1

  for (let i = 0; i < lines.length; i++) {
    const trimmed = lines[i]
    if (/^storage:/.test(trimmed)) storageSection = i
    if (storageSection >= 0 && /^\s{2}encryption:/.test(trimmed)) encryptionSection = i
    if (encryptionSection >= 0 && /^\s{4}enabled:\s*(true|false)/.test(trimmed)) {
      enabledLine = i
      break
    }
  }

  if (enabledLine >= 0) {
    // Replace existing enabled line
    lines[enabledLine] = `    enabled: ${value}`
  } else if (encryptionSection >= 0) {
    // Add enabled line after encryption section header
    lines.splice(encryptionSection + 1, 0, `    enabled: ${value}`)
  } else if (storageSection >= 0) {
    // Add encryption section after storage line
    lines.splice(storageSection + 1, 0, `  encryption:`, `    enabled: ${value}`)
  } else {
    // Add storage section at end
    lines.push("", "storage:", "  encryption:", `    enabled: ${value}`)
  }

  writeFileSync(configPath, lines.join("\n"), { mode: 0o600 })
}

export async function encryptionCommand(
  action: "init" | "status" | "on" | "off" | "export" | "import" | "decrypt",
  opts: EncryptionCommandOptions = {},
): Promise<string> {
  // Configure file-based keychain passphrase if provided
  configurePassphrase(opts.passphrase)

  switch (action) {
    // ── init ──
    case "init": {
      try {
        // On file-based platforms, passphrase is required
        if (EncryptionManager.isFileBased() && !EncryptionManager.getPassphrase()) {
          return [
            "✗ Passphrase is required on this platform.",
            "",
            "  Usage: argus encryption init --passphrase <your-passphrase>",
            "",
            "  The passphrase is used to encrypt the master key on disk.",
            "  You will need to provide it each session (or set",
            "  ARGUS_KEY_PASSPHRASE env var).",
            "",
            "  Keep this passphrase safe — without it, the master key",
            "  and all encrypted data is unrecoverable.",
          ].join("\n")
        }

        const created = await EncryptionManager.initialize()
        if (created) {
          const storageDesc = EncryptionManager.isFileBased()
            ? `stored in ${join(StoragePaths.basePath, ".master-key.enc")}`
            : "stored in macOS Keychain."
          return [
            `✓ Master key generated and ${storageDesc}`,
            "",
          "  Encryption-at-rest is enabled by default for new engagements.",
          "  To disable it, run: argus encryption off",
            "",
            "  To export a backup of this key (RECOMMENDED):",
            "    argus encryption export --passphrase <your-passphrase>",
          ].join("\n")
        }
        const storageDesc = EncryptionManager.isFileBased()
          ? "in the encrypted key file."
          : "in Keychain."
        return [
          `• Master key already exists ${storageDesc}`,
          "",
          "  Run `argus encryption export` to back it up, or",
          "  `argus encryption status` to check the current state.",
        ].join("\n")
      } catch (err) {
        if (err instanceof EncryptionError) {
          return `✗ ${err.message}`
        }
        throw err
      }
    }

    // ── on / off ──
    case "on": {
      // Check that a master key exists
      const initialized = await EncryptionManager.isInitialized()
      if (!initialized) {
        return [
          "✗ Cannot enable encryption: no master key found.",
          "",
          "  Run `argus encryption init` first to generate and store",
          "  a master key in the OS keychain.",
        ].join("\n")
      }

      // Load master key into cache
      await EncryptionManager.requireMasterKey()

      // Enable in memory
      EngagementStore.encryptionEnabled = true

      // Persist to user config
      writeUserConfigKey("storage.encryption.enabled", true)

      return [
        "✓ Encryption-at-rest is now ENABLED.",
        "",
        "  New engagements will be encrypted automatically.",
        "  Existing plaintext engagements will be migrated to encrypted",
        "  format on their next access.",
        "",
        "  Setting persisted to: ~/.argus/config.yaml",
      ].join("\n")
    }

    case "off": {
      // Disable in memory
      EngagementStore.encryptionEnabled = false

      // Persist to user config
      writeUserConfigKey("storage.encryption.enabled", false)

      return [
        "✗ Encryption-at-rest is now DISABLED.",
        "",
        "  New engagements will be stored in plaintext.",
        "  Existing encrypted engagements remain encrypted on disk.",
        "  To make them readable again, re-enable encryption with `argus encryption on`.",
        "",
        "  Note: Encryption is enabled by default in new configs.",
        "  To make this permanent, set `storage.encryption.enabled: false` in config.",
        "  Setting persisted to: ~/.argus/config.yaml",
      ].join("\n")
    }

    // ── status ──
    case "status": {
      try {
        // On file-based platforms, passphrase may be needed
        if (EncryptionManager.isFileBased() && !EncryptionManager.getPassphrase()) {
          return [
            "• Encryption status requires a passphrase on this platform.",
            "",
            "  Usage: argus encryption status --passphrase <your-passphrase>",
            "  Or set the ARGUS_KEY_PASSPHRASE environment variable.",
          ].join("\n")
        }

        const initialized = await EncryptionManager.isInitialized()

        if (!initialized) {
          return [
            "✗ Encryption is NOT initialized.",
            "",
            "  No master key found.",
            "  Run `argus encryption init` to generate one.",
          ].join("\n")
        }

        const key = await EncryptionManager.getMasterKey()
        const keyFingerprint = key
          ? key.subarray(0, 4).toString("hex")
          : "unknown"

        const storageDesc = EncryptionManager.isFileBased()
          ? `File-based (scrypt + AES-256-GCM): ${join(StoragePaths.basePath, ".master-key.enc")}`
          : "macOS Keychain (Security Framework via Bun FFI)"

        return [
          "✓ Encryption-at-rest status",
          "═".repeat(40),
          `  Master key:      PRESENT (fingerprint: ${keyFingerprint}...)`,
          `  Key length:      256 bits (AES-256-GCM)`,
          `  Key storage:     ${storageDesc}`,
          `  Key cache:       5-minute in-memory TTL`,
          "",
          "  Encryption is enabled by default for new assessments.",
          "",
          "  To encrypt existing engagement data:",
            "    Enable the flag and re-access each engagement to trigger migration.",
        ].join("\n")
      } catch (err) {
        if (err instanceof EncryptionError) {
          return `✗ ${err.message}`
        }
        throw err
      }
    }

    // ── decrypt ──
    case "decrypt": {
      const engagementId = opts.engagement
      const outputDir = opts.output

      if (!engagementId) {
        return [
          "✗ Engagement ID is required.",
          "",
          "  Usage: argus encryption decrypt --engagement <id> --output <dir>",
        ].join("\n")
      }

      if (!outputDir) {
        return [
          "✗ Output directory is required.",
          "",
          "  Usage: argus encryption decrypt --engagement <id> --output <dir>",
        ].join("\n")
      }

      try {
        // Load master key
        const masterKey = await EncryptionManager.requireMasterKey()

        // Open the root DB to check engagement state
        const store = new EngagementStore()
        const eng = store.getEngagement(engagementId)
        if (!eng) {
          store.close()
          return `✗ Engagement not found: ${engagementId}`
        }

        if (eng.storageVersion < 3) {
          store.close()
          return `✗ Engagement ${engagementId} is not encrypted (storage_version=${eng.storageVersion}). Nothing to decrypt.`
        }

        // Resolve paths
        const encryptedPath = StoragePaths.engagementDbPath(engagementId)
        if (!existsSync(encryptedPath)) {
          store.close()
          return `✗ Encrypted database not found at: ${encryptedPath}`
        }

        // Ensure output directory exists
        const outDir = join(process.cwd(), outputDir)
        if (!existsSync(outDir)) {
          mkdirSync(outDir, { recursive: true })
        }

        const outputPath = join(outDir, `${engagementId}.db`)

        // Read and decrypt the encrypted DB file
        const encrypted = readFileSync(encryptedPath)
        let decrypted: Buffer
        try {
          decrypted = EncryptionManager.decryptEngagementDb(encrypted, masterKey, engagementId)
        } catch (err) {
          store.close()
          const msg = err instanceof EncryptionError ? err.message : String(err)
          return `✗ Failed to decrypt engagement database: ${msg}`
        }

        // Write decrypted SQLite database directly to output path
        writeFileSync(outputPath, decrypted, { mode: 0o600 })

        store.close()

        return [
          `✓ Decrypted engagement ${engagementId} to: ${outputPath}`,
          "",
          `  File size: ${decrypted.length} bytes`,
          "  The decrypted database is a standard SQLite file.",
          "  Open it with any SQLite browser or use:",
          `    sqlite3 "${outputPath}"`,
          "",
          "  WARNING: This file contains plaintext data.",
          "  Store it securely and delete it when no longer needed.",
        ].join("\n")
      } catch (err) {
        if (err instanceof EncryptionError) {
          return `✗ ${err.message}`
        }
        throw err
      }
    }

    // ── export ──
    case "export": {
      const passphrase = opts.passphrase
      if (!passphrase) {
        return [
          "✗ Passphrase is required for key export.",
          "",
          "  Usage: argus encryption export --passphrase <your-passphrase> [--output <path>]",
          "",
          "  The passphrase must be provided via the --passphrase flag.",
          "  It should be a strong, memorable passphrase (not stored anywhere).",
          "  The exported key file can be used with `argus encryption import`.",
        ].join("\n")
      }

      try {
        await EncryptionManager.exportKey(passphrase, opts.output)
        const path = opts.output ?? join(process.cwd(), "argus-master-key.enc")
        return [
          `✓ Master key exported to: ${path}`,
          "",
          "  WARNING: Keep this file and its passphrase safe!",
          "  - Without the passphrase, this file cannot be used.",
          "  - Without this file, a lost master key means all encrypted",
          "    engagement data is permanently unrecoverable.",
          `  - File permissions: 0o600 (owner read/write only).`,
        ].join("\n")
      } catch (err) {
        if (err instanceof EncryptionError) {
          return `✗ ${err.message}`
        }
        throw err
      }
    }

    // ── import ──
    case "import": {
      const passphrase = opts.passphrase
      if (!passphrase) {
        return [
          "✗ Passphrase is required for key import.",
          "",
          "  Usage: argus encryption import --passphrase <your-passphrase> [--input <path>]",
          "",
          "  The passphrase must match the one used during export.",
        ].join("\n")
      }

      const inputPath = opts.input
      if (inputPath && !existsSync(inputPath)) {
        return `✗ Backup file not found: ${inputPath}`
      }

      try {
        await EncryptionManager.importKey(passphrase, inputPath)
        const defaultPath = join(process.cwd(), "argus-master-key.enc")
        const path = inputPath ?? defaultPath
        return [
          `✓ Master key imported from: ${path}`,
          "",
          "  The key has been stored in the macOS Keychain.",
          "  Encryption-at-rest is now available.",
          "  Encryption is enabled by default — no further action needed.",
        ].join("\n")
      } catch (err) {
        if (err instanceof EncryptionError) {
          return `✗ ${err.message}`
        }
        // Re-throw non-EncryptionError (e.g., scrypt auth tag failure for wrong passphrase)
        throw err
      }
    }

    default:
      // This shouldn't be reached — yargs enforces the action choices
      return `✗ Unknown encryption action: ${action}. Use: init, status, on, off, export, import, decrypt`
  }
}
