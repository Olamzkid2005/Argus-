/**
 * Print a fingerprint of the master key in the namespace this process resolves.
 *
 * Used to prove that running the test suite does not touch the production key:
 * record the fingerprint, run the suite, record it again — it must be identical.
 * Only a SHA-256 prefix is printed, never the key.
 *
 * Run from packages/opencode:
 *   bun run script/argus-master-key-fingerprint.ts
 */
import { createHash } from "node:crypto"
import { EncryptionManager, keychainServiceName, keychainAccountName } from "../src/argus/storage/encryption"

const service = keychainServiceName()
const account = keychainAccountName()
const key = await EncryptionManager.getMasterKey()

const fingerprint = key
  ? createHash("sha256").update(key).digest("hex").slice(0, 16)
  : "(no key)"

console.log(`service=${service} account=${account} fingerprint=${fingerprint}`)
