/**
 * Encryption Manager (Item 14c)
 *
 * Key management, OS keychain integration (via Bun FFI on macOS),
 * HKDF key derivation, AES-256-GCM encrypt/decrypt, and key backup/recovery.
 *
 * Platform support:
 *   - macOS: Security Framework via Bun FFI (Keychain Services)
 *   - Linux: Future — libsecret or file-based fallback
 *   - Windows: Future — Credential Manager via Bun FFI
 *
 * ── Architecture ──
 *   Master key (32 bytes) stored in OS keychain.
 *   Per-engagement keys derived via HKDF-SHA256(masterKey, engagementId).
 *   Per-file keys derived via HKDF-SHA256(masterKey, engagementId + ":" + fileId).
 *
 * ── Threat model ──
 *   Protects against filesystem-level attackers. Key lives in process memory
 *   during active sessions (see Risk 1 in PLAN_14C_ENCRYPTION_AT_REST.md).
 *   No memory zeroization guarantees in V8/Bun — accepted limitation.
 */
export declare class EncryptionError extends Error {
    readonly code: string;
    constructor(message: string, code: string);
}
export declare class KeyNotFoundError extends EncryptionError {
    constructor();
}
export declare class UnsupportedPlatformError extends EncryptionError {
    constructor(op: string);
}
export declare class EncryptionManager {
    /**
     * Maximum age for a cached master key (5 minutes).
     * After this, the next access will re-prompt for OS authentication.
     */
    private static readonly CACHE_TTL_MS;
    /** Cached master key (in process memory). */
    private static cachedKey;
    /** Passphrase for file-based keychain (Linux/Windows). Cleared after use. */
    private static filePassphrase;
    /**
     * Set the passphrase for file-based keychain access.
     * Required on Linux and Windows where the OS keychain is not available.
     * Can also be set via the ARGUS_KEY_PASSPHRASE environment variable.
     * Cleared when clearCache() or clearPassphrase() is called.
     */
    static setPassphrase(passphrase: string): void;
    /**
     * Clear the file-based keychain passphrase from memory.
     */
    static clearPassphrase(): void;
    /**
     * Get the passphrase, checking env var as fallback.
     * Returns null if not set.
     */
    static getPassphrase(): string | null;
    /**
     * Check if running in file-based keychain mode (non-macOS).
     */
    static isFileBased(): boolean;
    /**
     * Initialize encryption: generate a master key and store it in the OS keychain.
     * Safe to call multiple times — skips if key already exists.
     *
     * @returns true if a new key was generated, false if one already existed
     */
    static initialize(): Promise<boolean>;
    /**
     * Check if a master key has been initialized in the OS keychain.
     */
    static isInitialized(): Promise<boolean>;
    /**
     * Delete the master key from the OS keychain.
     * ⚠️ WARNING: This makes all encrypted engagements permanently unrecoverable
     * unless a backup was previously exported.
     */
    static destroy(): Promise<void>;
    /**
     * Check whether a master key is currently cached (non-expired).
     * Returns true if a key is loaded and within the 5-minute TTL.
     */
    static isCached(): boolean;
    /**
     * Get the master key from the in-memory cache synchronously.
     * Returns null if the key is not in cache (expired or never loaded).
     *
     * This is used by sync contexts like EngagementStore._getEngagementDb
     * that need to open encrypted databases synchronously. The caller should
     * ensure the key is loaded before using encrypted engagements.
     */
    static getCachedMasterKey(): Buffer | null;
    /**
     * Get the master key from cache or OS keychain.
     * Returns null if no key exists.
     */
    static getMasterKey(): Promise<Buffer | null>;
    private static rawGetMasterKey;
    /**
     * Get the master key, throwing if not found.
     */
    static requireMasterKey(): Promise<Buffer>;
    /**
     * Derive a per-engagement encryption key from the master key.
     *
     * Each engagement gets its own derived key via HKDF with domain
     * separation. Compromising one engagement's key does not expose others.
     */
    static deriveEngagementKey(masterKey: Buffer, engagementId: string): Buffer;
    /**
     * Derive a per-file encryption key from the master key.
     *
     * Each evidence file gets its own derived key via HKDF with domain
     * separation. Compromising one file's key does not expose other files
     * or the engagement DB.
     */
    static deriveFileKey(masterKey: Buffer, engagementId: string, fileId: string): Buffer;
    /**
     * Export the master key to a file, encrypted with a user-supplied passphrase.
     *
     * The backup file uses scrypt (N=2^17, r=8, p=1) for passphrase-based
     * key derivation, then AES-256-GCM to encrypt the master key.
     *
     * @param outputPath Path for the backup file (default: ./argus-master-key.enc)
     * @param passphrase User-supplied passphrase for encrypting the backup
     */
    static exportKey(passphrase: string, outputPath?: string): Promise<void>;
    /**
     * Import a previously exported master key from a backup file.
     *
     * @param inputPath Path to the backup file
     * @param passphrase Passphrase used during export
     */
    static importKey(passphrase: string, inputPath?: string): Promise<void>;
    /**
     * Encrypt a per-engagement database buffer with AES-256-GCM.
     *
     * The engagement key is derived from the master key + engagement ID.
     * Each encryption uses a fresh random salt and IV.
     */
    static encryptEngagementDb(plaintext: Buffer, masterKey: Buffer, engagementId: string): Buffer;
    /**
     * Decrypt a per-engagement database buffer.
     */
    static decryptEngagementDb(encrypted: Buffer, masterKey: Buffer, engagementId: string): Buffer;
    /**
     * Encrypt an evidence file with AES-256-GCM.
     *
     * Each file gets its own derived key (master + engagement ID + file ID).
     */
    static encryptFile(plaintext: Buffer, masterKey: Buffer, engagementId: string, fileId: string): Buffer;
    /**
     * Decrypt an evidence file.
     */
    static decryptFile(encrypted: Buffer, masterKey: Buffer, engagementId: string, fileId: string): Buffer;
    /**
     * Encrypt credentials data with AES-256-GCM.
     *
     * Uses a fixed domain salt ("argus-credentials-v1") for key derivation,
     * independent of any specific engagement. Each encryption still uses a
     * fresh random salt and IV, so encrypting the same data twice produces
     * different ciphertext.
     */
    static encryptCredentials(plaintext: Buffer, masterKey: Buffer): Buffer;
    /**
     * Decrypt credentials data previously encrypted with encryptCredentials.
     */
    static decryptCredentials(encrypted: Buffer, masterKey: Buffer): Buffer;
    /**
     * Ensure a master key exists, auto-generating one if needed.
     *
     * Designed for the case where `storage.encryption.enabled` defaults to `true`
     * but no master key has been initialized yet. Generates a random 256-bit
     * key and stores it in the OS keychain (macOS) or encrypted file (Linux/Windows).
     *
     * On file-based platforms without a configured passphrase, this method:
     * 1. First checks for an existing auto-passphrase file (`~/.argus/.auto-passphrase`)
     * 2. If found, loads the passphrase and attempts to decrypt the existing key
     * 3. If none found, generates a fresh auto-passphrase, stores it, and creates
     *    a new master key
     *
     * @returns true if a key is available (existing or newly created), false if
     *          auto-generation is impossible (e.g., file-based but can't create
     *          the passphrase file)
     */
    static ensureKeySync(): boolean;
    /**
     * Clear the in-memory key cache.
     * Call this when the user logs out or the session ends.
     */
    static clearCache(): void;
}
