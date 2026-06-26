# Item 14(c): Encryption at Rest — Implementation Plan

> **Goal:** Make all Argus data on disk unreadable without the correct encryption key.
> **Audience:** Developers new to the codebase. No prior security or cryptography knowledge assumed.

---

## Table of Contents

1. [What Is "Encryption at Rest"?](#1-what-is-encryption-at-rest)
2. [Why Does Argus Need It?](#2-why-does-argus-need-it)
3. [Current Architecture: How Argus Stores Data Today](#3-current-architecture-how-argus-stores-data-today)
4. [The Three Layers of Encryption](#4-the-three-layers-of-encryption)
5. [Layer 1: Key Management — The Master Key](#5-layer-1-key-management--the-master-key)
6. [Layer 2: Per-Engagement Database Encryption](#6-layer-2-per-engagement-database-encryption)
7. [Layer 3: Evidence File Encryption](#7-layer-3-evidence-file-encryption)
8. [What Gets Encrypted vs. What Stays Plaintext](#8-what-gets-encrypted-vs-what-stays-plaintext)
9. [Files That Need to Be Created or Modified](#9-files-that-need-to-be-created-or-modified)
10. [Migration: What Happens to Existing Data?](#10-migration-what-happens-to-existing-data)
11. [Security Trade-offs and Risks](#11-security-trade-offs-and-risks)
12. [Effort Estimate](#12-effort-estimate)
13. [Questions for Decision](#13-questions-for-decision)

---

## 1. What Is "Encryption at Rest"?

**Encryption at rest** means that data stored on disk (a hard drive, SSD, or cloud storage) is scrambled using a secret key. Without that key, the data looks like random garbage — nobody can read it, even if they steal the physical drive or gain access to the file system.

Think of it like a **locked safe**. When you need the data, you unlock the safe with your key, use the data, and lock it again when you're done. If someone steals the safe while it's locked, they cannot read what's inside.

This is different from **encryption in transit** (scrambling data while it travels across a network) and **encryption in use** (scrambling data while it's being processed in memory). We are only concerned with data that sits quietly on disk.

### Common examples of encryption at rest:
- Your phone's disk encryption (iPhone FileVault, Android encryption)
- Your laptop's full-disk encryption (BitLocker on Windows, FileVault on macOS)
- Encrypted cloud storage (iCloud, Google Drive "client-side encryption")

---

## 2. Why Does Argus Need It?

Argus is a **security assessment tool**. It scans targets (websites, APIs, networks) and stores the results — often containing highly sensitive information:

- **Target URLs** — the actual web addresses being tested
- **Security findings** — detailed descriptions of vulnerabilities found (SQL injections, XSS, authentication bypasses, etc.)
- **Screenshots** — images of web pages at the time of testing
- **Network logs** — HTTP requests, responses, headers
- **Credentials** — test usernames and passwords used during assessment
- **Audit logs** — a timeline of every action taken during the assessment

If an attacker gains access to the filesystem where Argus stores its data (`~/.argus/`), they could read every assessment ever performed — including the vulnerabilities found. This would be a **goldmine for attackers**: they could use the findings against those targets before the vulnerabilities are fixed.

Currently, all this data sits on disk in **plaintext** — completely unencrypted. Anyone with filesystem access can read it.

### Who might gain filesystem access?
- A malicious user on a shared machine (CI/CD runner, cloud VM, shared workstation)
- An attacker who compromises the system via another vulnerability
- A laptop thief
- An insider with system access but no legitimate need to see assessment data

Encryption at rest protects against all these scenarios.

---

## 3. Current Architecture: How Argus Stores Data Today

To understand the encryption plan, you first need to understand how Argus currently stores data. The architecture was redesigned in Item 14(b) — "Per-engagement storage isolation."

### Directory layout on disk

```
~/.argus/                          ← Top-level data directory (configurable)
├── argus.db                       ← Root database (SQLite)
│   └── Contains: engagements table only
│       - engagement ID, target URL, status, timestamps
│       - This is the "index" — a list of all engagements
│
└── engagements/                   ← Per-engagement directories
    ├── ENG-abc123/                ← One folder per engagement
    │   ├── engagement.db          ← Per-engagement database (SQLite)
    │   │   └── Contains:
    │   │       - findings (vulnerabilities discovered)
    │   │       - phases (steps in the assessment workflow)
    │   │       - audit_log (timeline of actions)
    │   │       - evidence_packages (references to files)
    │   │       - artifacts (metadata about screenshots, HAR files, etc.)
    │   │       - workflow_snapshots (saved workflow definitions)
    │   │       - finding_analysis (AI-generated explanations)
    │   │
    │   └── artifacts/             ← Actual binary files on disk
    │       └── pkg-xyz789/
    │           ├── screenshot.png
    │           ├── network-log.har
    │           └── manifest.json
    │
    └── ENG-def456/
        └── engagement.db
```

### Important details

| Detail | What it means |
|--------|---------------|
| **Database engine** | SQLite via `bun:sqlite` (a high-performance TypeScript SQLite driver built into Bun) |
| **OR/M** | Drizzle ORM (provides type-safe queries: `db.select().from(findings).where(eq(findings.id, id))`) |
| **Storage version** | Each engagement has a `storage_version` field: `1` = legacy (data in root DB), `2` = per-engagement DB (current), `3` = encrypted (future — what we're building now) |
| **Evidence files** | Screenshots and network logs are stored as plain files on disk, referenced by the database |
| **File integrity** | Evidence files already have SHA-256 hashes for detecting tampering (integrity, not confidentiality) |

### What encryption will change

```
CURRENT (plaintext):                     FUTURE (encrypted):

~/.argus/                                ~/.argus/
├── argus.db (plaintext)                 ├── argus.db (plaintext — still)
└── engagements/                         └── engagements/
    └── ENG-abc123/                          └── ENG-abc123/
        ├── engagement.db                        ├── engagement.db
        │   └── Plain SQLite file                │   └── AES-GCM encrypted blob
        └── artifacts/                           └── artifacts/
            └── screenshot.png                       └── screenshot.png
                └── Plain PNG                           └── AES-GCM encrypted
```

The root `argus.db` (engagement index) stays **plaintext** because it needs to be readable without a key — otherwise you couldn't even list your engagements to know what to decrypt.

**Important trade-off:** The root DB contains the target URL in plaintext (see the directory layout above). This is a deliberate limitation — the root DB is the "index" that must remain readable to list engagements. If target URL confidentiality is critical, operators should avoid storing identifying information in the engagement target field or use a mapping scheme. See [Section 8](#8-what-gets-encrypted-vs-what-stays-plaintext) for details.

---

## 4. The Three Layers of Encryption

We propose a **three-layer hybrid approach**. Each layer builds on the previous one:

```
┌─────────────────────────────────────────────────────────────────┐
│                                                                   │
│   Layer 1: Key Management                                         │
│   ┌───────────────────────────────────────────────────────────┐  │
│   │  Master key (32 bytes) stored in OPERATING SYSTEM          │  │
│   │  keychain — not in a file on disk.                         │  │
│   │                                                            │  │
│   │  macOS: Keychain Access.app                                │  │
│   │  Windows: Credential Manager                               │  │
│   │  Linux: Secret Service (GNOME Keyring / KDE Wallet)        │  │
│   └───────────────────────────────────────────────────────────┘  │
│                              │                                    │
│                              ▼                                    │
│   Layer 2: Per-engagement DB encryption                          │
│   ┌───────────────────────────────────────────────────────────┐  │
│   │  Each engagement.db file is encrypted as a single blob     │  │
│   │  using AES-256-GCM. Key is derived from master key +       │  │
│   │  engagement ID via HKDF (a key derivation function).       │  │
│   │                                                            │  │
│   │  On open:  decrypt file → in-memory SQLite (bun:sqlite     │  │
│   │            :memory:)                                        │  │
│   │  On close: serialize in-memory DB → encrypt → save         │  │
│   └───────────────────────────────────────────────────────────┘  │
│                              │                                    │
│                              ▼                                    │
│   Layer 3: Evidence file encryption                              │
│   ┌───────────────────────────────────────────────────────────┐  │
│   │  Screenshots, HAR files, and other evidence files are      │  │
│   │  encrypted individually with AES-256-GCM. Each file gets   │  │
│   │  its own derived key (master + engagement ID + file path   │  │
│   │  + unique salt).                                           │  │
│   └───────────────────────────────────────────────────────────┘  │
│                                                                   │
└─────────────────────────────────────────────────────────────────┘
```

Think of it like a **key ring**:

1. **Layer 1** = your house key (the master key, stored safely in the OS keychain)
2. **Layer 2** = a safety deposit box at the bank (the per-engagement DB)
3. **Layer 3** = individual lockboxes inside the deposit box (each evidence file)

You use your house key to unlock a derived key for the safety deposit box, which in turn unlocks keys for each lockbox inside.

---

## 5. Layer 1: Key Management — The Master Key

### What we're building

A module called `EncryptionManager` in a new file `storage/encryption.ts`.

### How it works

1. **First run:** The user runs `argus init --encrypt` (or sets `storage.encryption.enabled: true` in config). The system:
   - Generates a cryptographically random 32-byte (256-bit) master key
   - Asks the OS keychain to store it securely (this may prompt for a password or biometric)
   - The key is never written to disk as a file — it lives only in the OS keychain

2. **Everyday use:** When Argus needs to read or write encrypted data:
   - It asks the OS keychain for the master key (OS may prompt for authentication)
   - It derives a **per-engagement key** using HKDF (a standard key derivation function)
   - It uses that derived key for the actual encryption/decryption
   - It discards the key from memory after use

3. **Why not use the master key directly for everything?** If one engagement's key is compromised (e.g., through a memory dump), the other engagements are still safe — each has a different derived key.

### Library choice

We need an OS keychain library. Two options:

#### Option A: `cross-keychain` (third-party npm package)

`cross-keychain` is the nominal successor to the unmaintained `keytar` library.

| Platform | Backend used by cross-keychain |
|----------|-------------------------------|
| macOS | Security Framework (Keychain Services) |
| Windows | Credential Manager (DPAPI) |
| Linux | libsecret (D-Bus Secret Service) |

**Evaluation required before committing:**
- How many downloads / weekly npm installs does it have?
- Is it maintained by a reputable entity or individual?
- Has it undergone any security audit?
- What is its fallback behavior when the OS keychain is unavailable (headless Linux)?
- Does it support requesting user presence verification (biometric/password prompt)?

#### Option B: Bun FFI (direct OS API calls, no third-party dependency)

Bun's FFI (`Bun.ffi`) can call OS keychain APIs directly:
- **macOS:** Security Framework (`/System/Library/Frameworks/Security.framework`) — `SecKeychainAddGenericPassword`, `SecKeychainFindGenericPassword`
- **Windows:** Credential Manager (`advapi32.dll`) — `CredWriteW`, `CredReadW`
- **Linux:** `libsecret` (`libsecret-1.so`) — `secret_password_store_sync`, `secret_password_lookup_sync`

**Recommendation:** Start with `cross-keychain` for development velocity. Have a documented Bun FFI fallback plan if `cross-keychain` proves insufficient (especially for headless Linux environments). Both should be benchmarked for user-presence verification support.

### User presence verification

When Argus requests the master key from the OS keychain, it **must explicitly request user authentication** (biometric or password prompt), not silently retrieve the key. This ensures that malware running as the same user cannot silently decrypt all data without the user's knowledge.

| Platform | API for requiring user presence |
|----------|-------------------------------|
| macOS | `kSecUseAuthenticationUI` with `kSecUseAuthenticationUIAllow` or `kSecUseAuthenticationUIRequire` |
| Windows | `CredReadW` with `CRED_TYPE_DOMAIN_PASSWORD` requires auth |
| Linux | `libsecret` — varies by keyring daemon; `GNOME_KEYRING_CONTROL` |

**Recommendation:** Require OS authentication on first keychain access per session. Cache the master key in process memory (with zeroization on close) so subsequent accesses within the same session don't re-prompt.

### Pseudocode

```typescript
import { setPassword, getPassword, deletePassword } from "cross-keychain"
import crypto from "node:crypto"

const SERVICE_NAME = "argus"
const ACCOUNT_NAME = "master-key"

export class EncryptionManager {
  /** Generate and store a new master key. Called once on setup. */
  static async initialize(): Promise<void> {
    const masterKey = crypto.randomBytes(32)  // 256 bits
    await setPassword(SERVICE_NAME, ACCOUNT_NAME, masterKey.toString("hex"))
  }

  /** Retrieve the master key from the OS keychain. */
  static async getMasterKey(): Promise<Buffer | null> {
    const hex = await getPassword(SERVICE_NAME, ACCOUNT_NAME)
    if (!hex) return null
    return Buffer.from(hex, "hex")
  }

  /**
   * Derive a per-engagement key using HKDF-SHA256.
   *
   * HKDF uses a two-step extract-then-expand pattern.
   * The salt is a fixed domain separator (per RFC 5869 Section 3.1,
   * salt may be a fixed non-secret value when the input key material
   * is already uniformly random). The info parameter provides domain
   * separation for each engagement.
   */
  static deriveEngagementKey(masterKey: Buffer, engagementId: string): Buffer {
    const salt = Buffer.from("argus-engagement-v1", "utf-8")
    const info = Buffer.from(engagementId, "utf-8")
    return crypto.hkdfSync("sha256", masterKey, salt, info, 32)
  }

  /**
   * Derive a per-file key (for evidence file encryption).
   * Uses the same HKDF extract-then-expand with a different domain
   * separator salt and engagement+file info.
   */
  static deriveFileKey(masterKey: Buffer, engagementId: string, fileId: string): Buffer {
    const salt = Buffer.from("argus-file-v1", "utf-8")
    const info = Buffer.from(`${engagementId}:${fileId}`, "utf-8")
    return crypto.hkdfSync("sha256", masterKey, salt, info, 32)
  }
}
```

### Key backup and recovery

Two CLI commands must be implemented before shipping:

| Command | Behavior |
|---------|----------|
| `argus encryption export-key --output ./argus-master-key.enc` | Prompts for OS authentication, then exports master key encrypted with a user-supplied passphrase (PBKDF2-scrypt). Writes to file with `0o600` permissions. |
| `argus encryption import-key --input ./argus-master-key.enc` | Prompts for passphrase, decrypts, stores in OS keychain. |

Both commands show prominent warnings about key security. The export uses a strong password-based KDF (scrypt) so the backup file can be safely stored offline.

### Critical limitation: Memory protection in JavaScript/TypeScript

The master key and all derived keys exist in process memory as JavaScript `Buffer` objects. In Bun (V8-based runtime), you **cannot reliably zeroize memory**:
- The garbage collector may have moved or copied `Buffer` contents
- V8's optimizing compiler may keep values in registers or hidden classes
- `Buffer.fill(0)` only overwrites the current reference — stale copies may persist

**Accept this limitation.** Memory-level key protection requires a native addon (NAPI) or a dedicated security co-processor. For Argus's threat model (filesystem-level attackers, not sophisticated memory forensics), process memory exposure is acceptable. Document this explicitly.

---

## 6. Layer 2: Per-Engagement Database Encryption

### What we're building

A module called `EncryptedDbHandle` in a new file `storage/encrypted-db.ts`.

### The encrypted file format

When an engagement DB file is encrypted, it has this structure on disk:

```
┌─────────────────────────────────────────────┐
│  VERSION (1 byte)                           │ ← Format version (0x01 for this plan)
├─────────────────────────────────────────────┤
│  SALT (16 bytes)                            │ ← Random, unique per encryption
├─────────────────────────────────────────────┤
│  IV / NONCE (12 bytes)                      │ ← Random, unique per encryption
├─────────────────────────────────────────────┤
│  CIPHERTEXT (variable length)               │ ← The actual encrypted SQLite data
│  (optionally zlib-compressed before encrypt) │
├─────────────────────────────────────────────┤
│  AUTHENTICATION TAG (16 bytes)              │ ← Ensures data hasn't been tampered with
└─────────────────────────────────────────────┘
```

- **VERSION (0x01):** A single version byte at the start. Allows future format evolution (e.g., adding compression, changing KDF, or switching ciphers) without breaking existing files.
- **SALT:** Random 16 bytes used with HKDF. Ensures that even the same master key + engagement ID produces different derived keys per encryption cycle.
- **IV (Initialization Vector):** 12 random bytes for AES-GCM. Ensures that encrypting the same data twice produces different ciphertext.
- **CIPHERTEXT:** The encrypted database content. May be zlib-compressed before encryption (controlled by a flag in the version byte).
- **AUTH TAG:** GCM authentication tag (16 bytes). Both verifies integrity and authenticates the ciphertext.

### The lifecycle of an encrypted engagement DB

```
                         User opens engagement
                                │
                                ▼
                ┌───────────────────────────────┐
                │  Ask OS keychain for master   │
                │  key (may prompt for auth)     │
                └───────────────────────────────┘
                                │
                                ▼
                ┌───────────────────────────────┐
                │  Derive engagement key via    │
                │  HKDF (master + engagement ID)│
                └───────────────────────────────┘
                                │
                                ▼
                ┌───────────────────────────────┐
                │  Read encrypted file from     │
                │  disk, parse version byte     │
                └───────────────────────────────┘
                                │
                                ▼
                ┌───────────────────────────────┐
                │  Verify GCM auth tag → decrypt│
                │  (decompress if compressed)   │
                └───────────────────────────────┘
                                │
                                ▼
                ┌───────────────────────────────┐
                │  Load decrypted SQLite into   │
                │  bun:sqlite :memory: — NO     │
                │  temp file is ever written    │
                └───────────────────────────────┘
                                │
                        ... time passes ...
                    (user interacts with data)
                                │
                                ▼
                ┌───────────────────────────────┐
                │  User closes engagement /     │
                │  app shuts down               │
                └───────────────────────────────┘
                                │
                                ▼
                ┌───────────────────────────────┐
                │  Serialize in-memory DB via    │
                │  Database.serialize()          │
                └───────────────────────────────┘
                                │
                                ▼
                ┌───────────────────────────────┐
                │  Compress (optional) → encrypt │
                │  with AES-256-GCM (new random  │
                │  salt + IV each time)          │
                └───────────────────────────────┘
                                │
                                ▼
                ┌───────────────────────────────┐
                │  Overwrite original encrypted │
                │  file on disk                 │
                └───────────────────────────────┘
                                │
                                ▼
                          Done ✓
```

**Why in-memory instead of temp files?**

| Concern | Temp file approach | In-memory approach |
|---------|-------------------|-------------------|
| **Same-user attacks** | Any process as same user can read `/tmp/` | No file on disk to steal |
| **Secure deletion** | Unreliable on SSDs (wear-leveling) + journaling filesystems | Not needed — nothing to delete |
| **Swap exposure** | Decrypted data on disk may be paged | Still in RAM (see Risk 1) |
| **Crash safety** | Stale temp file left behind | Nothing left behind |
| **Idle timeout complexity** | Must re-encrypt on idle, race conditions | No re-encryption needed — held in memory for session |

The only downside is RAM usage. Engagement databases contain only metadata (findings, phases, audit logs) — screenshots and HAR files are stored separately. Typical engagement DBs are under 10 MB. If a DB exceeds 50 MB, Bun's `Database.serialize()` may briefly double memory usage during save, but this is acceptable for the threat model.

### Handling WAL files

SQLite's WAL mode creates `-wal` and `-shm` journal files that may contain plaintext fragments. Since we use in-memory databases, WAL mode is irrelevant during the session. On close, `Database.serialize()` produces a single consistent snapshot regardless of journal mode.

Important: When migrating a plaintext per-engagement DB to encrypted format, delete any existing `-wal` and `-shm` files after the migration is complete. These may contain residual plaintext data.

### Crash resilience

If Argus crashes while an encrypted engagement is open:
1. The in-memory DB is lost — no temp file cleanup needed
2. The encrypted DB on disk is **stale** (reflects last clean close)
3. On next startup, the stale encrypted DB is detected and loaded normally
4. Any writes that were buffered in memory are lost — this is no different from any other crash scenario

No special crash recovery is needed beyond what SQLite's own integrity checks provide (`PRAGMA integrity_check` on the decrypted data after loading).

### Integration with EngagementStore

The existing `EngagementStore` class (in `store.ts`) already has a `_getEngagementDb()` method that opens per-engagement DBs. We add a check:

```typescript
private _getEngagementDb(engagementId: string) {
  // ...existing logic...

  // NEW: If engagement has storage_version === STORAGE_VERSION_ENCRYPTED
  if (eng.storageVersion === STORAGE_VERSION_ENCRYPTED) {
    return this._openEncryptedDb(engagementId)  // New method
  }

  // ...existing logic for plaintext DBs...
}
```

The new `_openEncryptedDb()` method:
1. Gets the master key from OS keychain
2. Derives the engagement key via HKDF
3. Reads the encrypted `.db` file, parses version byte, decrypts in memory
4. Opens decrypted SQLite data as an in-memory database with `new Database(":memory:")` and loads the serialized data
5. Registers a cleanup handler for when the store closes (serializes in-memory DB → encrypts → writes to disk)

Key implementation detail — loading serialized data into `bun:sqlite`:

```typescript
import { Database } from "bun:sqlite"

function loadEncryptedDb(encryptedBuffer: Buffer, masterKey: Buffer, engagementId: string): Database {
  const engagementKey = EncryptionManager.deriveEngagementKey(masterKey, engagementId)
  const decrypted = decryptAesGcm(encryptedBuffer, engagementKey)  // returns Buffer
  const db = new Database(":memory:")
  db.exec(decrypted.toString("utf-8"))  // Load SQL dump into in-memory DB
  return db
}
```

Note: `bun:sqlite`'s `Database.serialize()` outputs a full SQL dump that can be replayed with `db.exec()`. Alternative: use `db.backup("/tmp/...")` to a temp file and read it back, but that recreates the temp file problem. The `serialize()/exec()` approach keeps everything in memory.

### Why not use SQLCipher (transparent database encryption)?

**SQLCipher** is a popular library that encrypts SQLite databases transparently — you just open the database with a password, and it handles encryption/decryption automatically at the storage layer. It would be ideal.

However, **Bun's built-in `bun:sqlite` does not support SQLCipher**. Attempting to open an encrypted SQLCipher database with `bun:sqlite` produces a `SQLITE_NOTADB` error. Supporting SQLCipher would require replacing `bun:sqlite` with native bindings, which is complex and fragile with Bun's runtime.

Our file-level approach achieves the same security property (data at rest is encrypted) while keeping the proven `bun:sqlite` driver and all existing code paths intact.

---

## 7. Layer 3: Evidence File Encryption

### What we're building

A module called `EncryptedFileStore` in a new file `storage/encrypted-file.ts`.

### How it works

Evidence files (screenshots, HAR network logs, etc.) are encrypted individually. Each file has the same on-disk format as the encrypted DB (including the version byte):

```
[VERSION: 1 byte][SALT: 16 bytes][IV: 12 bytes][CIPHERTEXT ...][AUTH TAG: 16 bytes]
```

The version byte (`0x01`) serves the same purpose — allows future format evolution.

The difference from Layer 2: each evidence file gets a **unique key derived from the master key + engagement ID + file ID + a random salt**. This means:
- Compromising one file's key doesn't affect other files
- Compromising the engagement DB key doesn't expose evidence files
- Each file can be independently verified for integrity

### Pseudocode

```typescript
import crypto from "node:crypto"
import zlib from "node:zlib"

const VERSION_BYTE = 0x01
const SALT_LEN = 16
const IV_LEN = 12
const TAG_LEN = 16
const KEY_LEN = 32  // AES-256

export class EncryptedFileStore {
  constructor(
    private masterKey: Buffer,
    private engagementId: string
  ) {}

  /** Encrypt data and return the encrypted buffer (with optional compression). */
  encrypt(plaintext: Buffer, fileId: string, compress = false): Buffer {
    const payload = compress ? zlib.deflateSync(plaintext) : plaintext
    const salt = crypto.randomBytes(SALT_LEN)
    const iv = crypto.randomBytes(IV_LEN)
    const key = EncryptionManager.deriveFileKey(
      this.masterKey, this.engagementId, fileId
    )

    const cipher = crypto.createCipheriv("aes-256-gcm", key, iv)
    const encrypted = Buffer.concat([cipher.update(payload), cipher.final()])
    const tag = cipher.getAuthTag()

    // Version byte (0x01) | salt | iv | ciphertext | auth tag
    const version = Buffer.alloc(1)
    // Bit 0: compression flag (1 = compressed)
    version[0] = VERSION_BYTE | (compress ? 0x02 : 0x00)
    return Buffer.concat([version, salt, iv, encrypted, tag])
  }

  /** Decrypt an encrypted buffer. Handles version byte. */
  decrypt(encrypted: Buffer, fileId: string): Buffer {
    const version = encrypted[0]
    let offset = 1

    const salt = encrypted.subarray(offset, offset + SALT_LEN)
    offset += SALT_LEN
    const iv = encrypted.subarray(offset, offset + IV_LEN)
    offset += IV_LEN
    const tag = encrypted.subarray(encrypted.length - TAG_LEN)
    const ciphertext = encrypted.subarray(offset, encrypted.length - TAG_LEN)

    const key = EncryptionManager.deriveFileKey(
      this.masterKey, this.engagementId, fileId
    )

    const decipher = crypto.createDecipheriv("aes-256-gcm", key, iv)
    decipher.setAuthTag(tag)
    const decrypted = Buffer.concat([decipher.update(ciphertext), decipher.final()])

    // Decompress if compression flag is set (bit 1 of version byte)
    return (version & 0x02) ? zlib.inflateSync(decrypted) : decrypted
  }
}
```

### Why derive per-file keys instead of using one key for everything?

| Why | Explanation |
|-----|-------------|
| **Compartmentalization** | If a memory dump captures one file's key, only that file is exposed |
| **Key rotation** | A file can be re-encrypted with a new key without touching other files |
| **Selective access** | In theory, you could share a single evidence file without sharing the entire engagement |
| **Integrity binding** | Each file's key is bound to its identity — swapping files would fail decryption |

### What about the existing SHA-256 integrity check?

Evidence files already have SHA-256 hashes stored in the database for integrity verification (detecting tampering). AES-GCM's authentication tag serves a similar purpose — it detects if the encrypted data has been modified. We will keep both:

- **SHA-256** = integrity check at the application layer (works even when the DB is closed)
- **GCM auth tag** = integrity check at the encryption layer (verifies decryption is correct)

---

## 8. What Gets Encrypted vs. What Stays Plaintext

Not all data needs to be encrypted. Some data must remain readable to even know what to decrypt.

| Data | Encrypted? | Why? |
|------|-----------|------|
| **Root DB — engagement list** | ❌ **Plaintext** | Without this, you can't list engagements to know which to decrypt |
| Engagement ID (e.g., `ENG-abc123`) | ❌ **Plaintext** | Directory names need to be resolved on disk; also lives in root DB |
| Engagement target (URL) | ✅ **Encrypted** | The target URL is sensitive — it's the actual thing being tested |
| Engagement status (CREATED, RUNNING, DONE) | ❌ **Plaintext** | Needed for dashboard/summary without decrypting everything |
| Finding title | ✅ **Encrypted** | "SQL Injection in login form" — highly sensitive |
| Finding description | ✅ **Encrypted** | Detailed vulnerability description — highly sensitive |
| Finding severity, confidence | ❌ **Plaintext** | Needed for summary charts / statistics |
| Phase definitions | ✅ **Encrypted** | May contain target context |
| Audit log messages | ✅ **Encrypted** | "Exploited SQL injection on /api/users" — sensitive |
| Audit log timestamps | ❌ **Plaintext** | Needed for timeline without decryption (debatable) |
| Evidence package hashes | ✅ **Encrypted** | Links to encrypted files |
| Artifact paths on disk | ✅ **Encrypted** | Could reveal target structure |
| Artifact file content | ✅ **Encrypted** | Screenshots, HAR logs — highly sensitive |
| Workflow YAML snapshots | ✅ **Encrypted** | May contain target-specific configuration |
| Finding analysis (AI explanations) | ✅ **Encrypted** | Detailed AI analysis of vulnerabilities |

### Important caveat: Target URL in root DB

The `engagements` table in the root DB stores `target` (the assessment target URL) in plaintext. This creates a **deliberate contradiction** with the "encrypted" classification above — the target URL is marked as sensitive but remains visible in the root DB because the root DB must be readable without a key.

**Options for handling this:**

| Option | Trade-off |
|--------|-----------|
| **Accept it** (recommended for MVP) | Document that target URLs are visible in the root DB. Most users already share target URLs with their team; this is not the most sensitive data in the system. |
| **Use a mapping scheme** | Store an opaque engagement label in the root DB (`"ENG-abc123: Q1 PCI Scan"`) and keep the real target URL only in the encrypted per-engagement DB. User must decrypt to see the target. |
| **Encrypt the root DB** | Use a user-password-derived key (not OS keychain, since you need it on every startup) to encrypt the root DB. Adds startup friction. Future work. |

### What this means for the database schema

The per-engagement DB schema stays the same — we encrypt the **entire file**, not individual columns. This is simpler and more secure (no risk of accidentally leaving a column unencrypted).

---

## 9. Files That Need to Be Created or Modified

### New files

| File | Description | Estimated lines |
|------|-------------|-----------------|
| `src/argus/storage/encryption.ts` | `EncryptionManager` — key generation, OS keychain interaction, HKDF key derivation, key export/import | ~80 lines |
| `src/argus/storage/encrypted-db.ts` | `EncryptedDbHandle` — decrypt encrypted blob → in-memory SQLite, serialize → encrypt on close | ~150 lines |
| `src/argus/storage/encrypted-file.ts` | `EncryptedFileStore` — per-file encrypt/decrypt for evidence artifacts | ~100 lines |
| `src/argus/commands/encryption.ts` | `argus encryption export-key` and `argus encryption import-key` CLI commands | ~60 lines |
| `test/argus/unit/encryption.test.ts` | Unit tests for all modules | ~150 lines |

### Modified files

| File | What changes | Estimated lines |
|------|-------------|-----------------|
| `src/argus/engagement/store.ts` | Add `storage_version === 3` path in `_getEngagementDb()`, `_ensureEngagementDb()`, in-memory DB lifecycle | ~40 lines |
| `src/argus/config/loader.ts` | Add `storage.encryption` to Zod config schema | ~10 lines |
| `src/argus/config/feature-flags.ts` | Add encryption feature flag | ~5 lines |
| `src/argus/commands/config.ts` | Register encryption subcommands | ~5 lines |
| `src/argus/cli.ts` | Add encryption command to CLI parser | ~5 lines |
| `package.json` | Add `cross-keychain` dependency (or implement Bun FFI keychain module) | 1 line |
| `argus.config.yaml` | Add `storage.encryption.enabled: false` (disabled by default) | 2 lines |
| `docs/ARCHITECTURAL_FIXES_PLAN.md` | Mark Item 14(c) completed | 5 lines |

### Files that already exist and need NO changes

| File | Why no change |
|------|---------------|
| `src/argus/engagement/schema.sql.ts` | Already has `STORAGE_VERSION_ENCRYPTED = 3` defined (defined in advance during Item 14b) |
| `src/argus/storage/paths.ts` | Paths don't change — only the content of files at those paths changes |
| `src/argus/commands/evidence.ts` | Evidence command works the same way; the encryption layer is transparent (decryption happens in the evidence store before hashing) |

---

## 10. Migration: What Happens to Existing Data?

Existing engagements with `storage_version = 1` (legacy) and `storage_version = 2` (per-engagement, plaintext) remain **fully readable**. They are not affected by this change.

### Scenario matrix

| Existing engagements | Encryption setting in config | Behavior |
|---------------------|------------------------------|----------|
| `storage_version = 1` (legacy) | `enabled: false` | Read from root DB — no change |
| `storage_version = 1` (legacy) | `enabled: true` | Read from root DB — still no change. Legacy data is never encrypted |
| `storage_version = 2` (plaintext) | `enabled: false` | Read/write per-engagement DB — no change |
| `storage_version = 2` (plaintext) | `enabled: true` | Read per-engagement DB. On first write, create NEW encrypted DB, migrate data, update version to 3 |
| `storage_version = 3` (encrypted) | `enabled: true` | Decrypt on open, encrypt on close — normal operation |
| `storage_version = 3` (encrypted) | `enabled: false` | Error — cannot read encrypted data without encryption enabled |

### Migration (plaintext → encrypted)

When encryption is enabled and an existing plaintext engagement is first accessed:

1. Read all data from existing `engagement.db` (plaintext)
2. Create new encrypted `engagement.db` (encrypted blob)
3. Write data into the encrypted DB
4. Update `storage_version` from `2` to `3`
5. Delete old plaintext `engagement.db`
6. Delete any `-wal` and `-shm` files left over from WAL mode

This is a **lazy migration** — it happens per-engagement, on first access. Not all at once.

### ⚠️ Important: Ghost data from migration

Deleting the old plaintext `engagement.db` does **not guarantee the data is permanently erased**:

- **SSD wear-leveling:** The filesystem may have relocated the old data to different flash cells. The original plaintext may persist in over-provisioned blocks.
- **Journaling filesystems:** ext4, APFS, and NTFS may retain copies of the deleted file in journal logs.
- **Snapshots:** ZFS, Btrfs, APFS snapshots, and Windows Volume Shadow Copy may preserve the old file.
- **Backups:** Time Machine, rsync, or cloud backup tools may have already backed up the plaintext file.

**Mitigation:** Document this clearly. For high-security environments, recommend starting fresh with encryption enabled rather than migrating existing data. The migration is a convenience feature, not a guaranteed sanitization.

### Recovery path for users who lose keychain access

The plan previously had: `storage_version = 3` with `enabled: false` = **Error** (user-hostile). To avoid bricking user data:

| Scenario | Behavior |
|----------|----------|
| Encryption enabled, keychain available | Normal operation |
| Encryption enabled, keychain **missing** (new machine, reformatted) | Error with recovery instructions: run `argus encryption import-key` |
| User explicitly wants to decrypt an engagement | Provide `argus decrypt --engagement ENG-abc123 --output ./backup` command (requires keychain access) |
| User disabled encryption after previously having it enabled | Provide `argus encryption disable` command that re-encrypts all engagements back to plaintext (with warning) |

**Never leave users with unrecoverable data.** The key export/import commands (Section 5) are prerequisite to shipping encryption.

---

## 11. Security Trade-offs and Risks

No security system is perfect. Here are the trade-offs we're making:

### Risk 1: Key in process memory (JavaScript limitations)

**Problem:** While Argus is running with encryption enabled, the master key exists in the application's memory (RAM) as a JavaScript `Buffer` object. A sophisticated attacker who can read process memory (e.g., via a debugger, `/proc/pid/mem`, or a kernel exploit) could extract the key.

**Why we cannot fully mitigate this in Bun/V8:**
- The garbage collector may move or copy `Buffer` contents internally
- V8's optimizing compiler may keep values in hidden classes or registers
- `Buffer.fill(0)` only zeroizes the current reference — old copies may persist
- The key must remain in memory during active engagement sessions

**Mitigation:** We call `Buffer.fill(0)` on key buffers when they are no longer needed (even though this is imperfect). Decrypted data lives in `bun:sqlite`'s in-memory database, which is managed by SQLite's own allocator — outside of V8's heap but still in process memory.

**Severity:** Low/Medium. Reading process memory requires a serious compromise — at that point, the attacker likely has worse things they could do. This is an accepted limitation of using a managed runtime. Native key handling (NAPI addon) could improve this but is deferred.

### Risk 2: In-memory database (was: temp file exposure)

**Problem:** Previously this plan called for writing decrypted databases to `/tmp/`. This was **unacceptable** — any process running as the same user could read temp files, and "secure deletion" is unreliable on modern SSDs and journaling filesystems.

**Resolution:** We now use **in-memory SQLite databases** exclusively. No decrypted data is ever written to disk during a session. This eliminates the entire temp file threat vector.

**Remaining concern:** The in-memory database may be swapped to disk by the operating system's virtual memory manager. This is a system-level concern beyond Argus's control.

**Mitigation:** On Linux, document that users can `mlock()` the process via `ulimit -l`. On macOS, memory is not swapped to a swapfile by default on modern SSDs (APFS compression handles memory pressure). Accept the residual risk for other platforms.

**Severity:** Low (down from Medium).

### Risk 3: Lost key = lost data

**Problem:** The master key is stored in the OS keychain. If the user loses access to their keychain (e.g., they reformat their machine, or their user profile is deleted), the key is gone forever.

**Mitigation:** We provide two CLI commands before shipping encryption:
- `argus encryption export-key` — exports the master key encrypted with a user passphrase (scrypt KDF), to be stored offline
- `argus encryption import-key` — imports a previously exported key into the OS keychain on a new machine

**Severity:** High. Users are responsible for backing up their key. No backdoor means no attacker can use a backdoor. The export/import commands are prerequisite to shipping.

### Risk 4: OS keychain availability on Linux servers

**Problem:** The Linux Secret Service (libsecret) requires a running D-Bus session and a keyring daemon (GNOME Keyring, KDE Wallet, or similar). On headless servers or containers, these may not be available.

**Mitigation:** Two options:
1. If using `cross-keychain`, use its documented CLI fallback for headless environments
2. If using Bun FFI, implement a file-based fallback (encrypted master key stored in `~/.argus/master-key.enc`, protected by a user password via scrypt)

**Severity:** Low/Medium. A known limitation, documented in the README with platform-specific setup instructions.

### Risk 5: No key rotation

**Problem:** The current design uses a single master key for the lifetime of the Argus installation. There's no mechanism to rotate (change) the key without re-encrypting all engagements.

**Mitigation:** Key rotation is explicitly deferred to a future version. Each engagement's derived key uses HKDF with the engagement ID as "info" — so the same master key produces different keys for different engagements. Rotation would mean re-encrypting each engagement with a new master key, which is straightforward to implement later.

**Severity:** Low. Key rotation is a best practice but rarely needed in practice for local CLI tools.

### Risk 6: Backups, cloud sync, and cloud storage

**Problem:** If `~/.argus/` is included in system backups (Time Machine, Windows File History) or cloud syncing (iCloud Drive, Dropbox, OneDrive), encrypted blobs are safely backed up — but there are edge cases:

- **Temp file exposure (legacy):** Eliminated by the in-memory approach
- **Cloud sync of `~/.argus/`:** Encrypted files are safe to sync. However, if an attacker gains access to the cloud account, they could steal encrypted blobs for offline brute-forcing
- **Backup during migration:** If a backup runs during migration, it may capture both the plaintext and encrypted versions of an engagement DB

**Mitigation:** Document that `~/.argus/` should not be placed in cloud-synced directories for high-security environments. The migration is designed to be atomic (delete plaintext after encrypted write succeeds), but snapshotted backups may still capture the plaintext version.

**Severity:** Low. Documented in README.

### Risk 7: SQLite WAL file residue

**Problem:** When using plaintext `bun:sqlite` databases with WAL mode, `-wal` and `-shm` journal files may contain plaintext fragments even after the main DB is encrypted and replaced.

**Mitigation:** During migration (plaintext → encrypted), explicitly delete any `-wal` and `-shm` files. For the in-memory approach, WAL mode is never used, so no WAL files are created during encrypted sessions.

**Severity:** Low. Handled by the migration code.

### Risk 8: Crash during save

**Problem:** If Argus crashes while writing the encrypted DB back to disk, the file may be partially written (corrupted) or zero-length.

**Mitigation:** Use atomic write pattern:
1. Write encrypted data to `<engagement.db>.tmp` (same directory)
2. `fs.rename()` to replace the original file (atomic on most filesystems)
3. On next open, if the main file is corrupted, check for `.tmp` files as recovery candidates

**Severity:** Low. Standard atomic write pattern handles this.

---

## 12. Effort Estimate

| Component | Lines of code | Estimated time |
|-----------|---------------|----------------|
| `encryption.ts` — key management, export/import | ~80 | 45 minutes |
| `encrypted-db.ts` — DB encrypt/decrypt, in-memory lifecycle | ~150 | 1.5 hours |
| `encrypted-file.ts` — file encrypt/decrypt with version byte | ~100 | 1 hour |
| `commands/encryption.ts` — CLI commands for key management | ~60 | 30 minutes |
| `store.ts` — integration with encrypted path | ~40 | 45 minutes |
| `config/loader.ts`, `feature-flags.ts`, `cli.ts` — wiring | ~30 | 30 minutes |
| Tests | ~150 | 1 hour |
| **Total** | **~610** | **~5-6 hours** |

---

## 13. Questions for Decision

The following decisions need to be made before implementation begins:

### Q1: Which encryption scope?

Three options, each building on the previous:

1. **Full three-layer plan** (5-6 hours) — Keychain + DB encryption + file encryption. Complete solution.
2. **DB encryption only — MVP** (3-4 hours) — Keychain + per-engagement DB encryption. File-level encryption deferred. Most sensitive data (findings, credentials, audit logs) is in the DB.
3. **Application-level column encryption** (1.5-2 hours) — Encrypt individual database columns inside SQLite (finding titles, descriptions) rather than the entire file. Leaves evidence files unprotected.

**🎯 Recommended: Option 2 (DB encryption MVP).**
- File encryption (Layer 3) adds significant complexity for marginal gain — screenshots and HAR files without DB context are much less useful to an attacker
- Defers the temp file / compression / version byte concerns for Layer 3 to a follow-up
- Still delivers the core security property: all structured assessment data is encrypted at rest

### Q2: Temp file cleanup strategy?

1. **On close only** — Decrypted DB stays in `/tmp` while engagement is open. ❌ **Discarded** — temp files on disk are unacceptable for a security tool.
2. **On close + idle timeout** — Re-encrypt after 5 minutes of inactivity. ❌ **Discarded** — race conditions and temp file churn create more problems than they solve.
3. **In-memory only (no temp file)** — Load the entire decrypted DB into a Bun in-memory SQLite database (`:memory:`). No temp file at all.

**🎯 Recommended: Option 3 (in-memory only).**
- Eliminates the entire temp file threat vector
- No secure deletion concerns
- No idle timeout complexity or race conditions
- Engagement DBs are metadata-only (< 10 MB typical) — RAM usage is negligible
- Bun's `Database.serialize()` produces a full SQL dump for persist-on-close

### Q3: Encryption default — opt-in or opt-out?

1. **Opt-in (safe default)** — Encryption only activates when user sets `storage.encryption.enabled: true` in config. No surprise for existing users.
2. **Opt-out (secure by default)** — Encryption enabled automatically on first run. Users must explicitly disable it. More secure but may break existing scripts/workflows.
3. **Prompt on first run** — Ask the user interactively on first `argus scan` whether to enable encryption. Most user-friendly but adds a CLI interaction.

**🎯 Recommended: Option 1 (opt-in).**
- Argus has existing users with existing data — silently changing the storage format would break tooling
- Opt-out surprises users when their scripts fail because `cross-keychain` isn't installed or keychain isn't available
- Add a post-install message (a one-liner in the CLI) suggesting: "Tip: enable encryption at rest with `argus config set storage.encryption.enabled true`"
- Revisit opt-out in a future major version

---

## Appendix A: Glossary

| Term | Simple explanation |
|------|-------------------|
| **AES-256-GCM** | A widely-used encryption algorithm. "256" = 256-bit key (very strong). "GCM" = Galois/Counter Mode, which provides both encryption and integrity checking. |
| **Authentication tag** | A cryptographic checksum that proves the data hasn't been tampered with. Part of the GCM mode. If someone modifies the encrypted data, decryption will fail with a clear error. |
| **Ciphertext** | Encrypted data — looks like random bytes. |
| **HKDF** | HMAC-based Key Derivation Function. A standard way to derive multiple keys from a single master key. Used to create different keys for each engagement and each file. |
| **IV (Initialization Vector)** | A random value that ensures encrypting the same data twice produces different output. Not secret — stored alongside the ciphertext. |
| **Keychain** | The operating system's secure credential storage. macOS has Keychain Access, Windows has Credential Manager, Linux has Secret Service. |
| **PBKDF2 / scrypt** | Password-Based Key Derivation Functions. Used to turn a password into a cryptographic key. We use HKDF instead (since our key is already random, not a human password). |
| **Plaintext** | Unencrypted data — readable by anyone. |
| **Salt** | A random value added to the key derivation process. Ensures that even with the same master key, each encryption produces different keys. |
| **SQLite** | A lightweight, file-based database engine. The most widely deployed database in the world (every phone, browser, and many apps use it). |
| **Storage version** | A number field on each engagement that tells the system how its data is stored: 1 = legacy (single DB), 2 = per-engagement DB (plaintext), 3 = encrypted. |

---

## Appendix B: Code Flow Diagram

For developers who will implement this, here's the high-level code flow:

```
User runs: argus scan --encrypt https://example.com
                    │
                    ▼
          ┌─────────────────────┐
          │  config/loader.ts   │
          │  Reads config:      │
          │  encryption enabled │
          └─────────┬───────────┘
                    │
                    ▼
          ┌─────────────────────┐
          │  engagement/store.ts│
          │  createEngagement() │
          │  storage_version = 3│
          └─────────┬───────────┘
                    │
                    ▼
          ┌─────────────────────┐
          │  _ensureEngagementDb│
          │  (engagementId)     │
          └─────────┬───────────┘
                    │
         ┌──────────┴──────────┐
         ▼                     ▼
   storage_version=2     storage_version=3
   (plaintext)            (encrypted)
         │                     │
         ▼                     ▼
   ┌─────────────┐    ┌──────────────────────┐
   │ Open .db    │    │  encryption.ts        │
   │ with        │    │  GetMasterKey()       │
   │ bun:sqlite  │    │  DeriveEngKey(id)     │
   └─────────────┘    └──────────┬───────────┘
                                  │
                                  ▼
                         ┌──────────────────────────┐
                         │  encrypted-db.ts          │
                         │  Decrypt .db file →       │
                         │  in-memory Buffer          │
                         └──────────┬───────────────┘
                                  │
                                  ▼
                         ┌──────────────────────────┐
                         │  Open :memory: SQLite    │
                         │  with bun:sqlite          │
                         │  Load decrypted data      │
                         └──────────────────────────┘
                                  │
                     ... assessment runs ...
                     (findings saved, evidence collected)
                                  │
                                  ▼
                         ┌──────────────────────────┐
                         │  store.close()            │
                         └──────────┬───────────────┘
                                  │
                                  ▼
                         ┌──────────────────────────┐
                         │  encrypted-db.ts          │
                         │  Database.serialize() →   │
                         │  Encrypt → write .db file │
                         │  (atomic: .tmp + rename)  │
                         └──────────────────────────┘
```

For evidence files:

```
    EvidenceCollector.saveArtifact(path, data)
                    │
                    ▼
          ┌─────────────────────┐
          │  encrypted-file.ts  │
          │  encrypt(data)      │
          │  → write to disk     │
          └─────────────────────┘
```

---

*End of plan. Ready for implementation once decisions are made.*
