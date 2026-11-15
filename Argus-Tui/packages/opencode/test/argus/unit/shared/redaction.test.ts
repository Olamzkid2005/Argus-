import { describe, expect, test } from "bun:test"
import { redactSecrets } from "../../../../src/argus/shared/redaction"

describe("redactSecrets", () => {
  test("removes bearer tokens, cookies, AWS keys, and embedded credentials", () => {
    const redacted = redactSecrets(
      "Authorization: Bearer secret-token Cookie: session=secret AKIAIOSFODNN7EXAMPLE postgres://operator:secret@example.com/db"
    )
    expect(redacted).not.toContain("secret-token")
    expect(redacted).not.toContain("session=secret")
    expect(redacted).not.toContain("AKIAIOSFODNN7EXAMPLE")
    expect(redacted).not.toContain("operator:secret@")
    expect(redacted).toContain("Bearer __REDACTED__")
    expect(redacted).toContain("Cookie: session=__REDACTED__")
    expect(redacted).toContain("__REDACTED_AWS_KEY__")
    expect(redacted).toContain("postgres://__REDACTED_CREDS__@")
  })

  test("removes private keys without leaking key material", () => {
    const key = "-----BEGIN PRIVATE KEY-----\nsecret-key-material\n-----END PRIVATE KEY-----"
    const redacted = redactSecrets(key)
    expect(redacted).not.toContain("secret-key-material")
    expect(redacted).toContain("__REDACTED_PRIVATE_KEY__")
  })
})
