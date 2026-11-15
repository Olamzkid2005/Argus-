import { describe, expect, test } from "bun:test";
import {
  identityFromActionArguments,
  normalizeActionSource,
  provenanceForAction,
} from "../../../../src/argus/planner/action-provenance";

describe("action provenance", () => {
  test("normalizes known worker provenance labels", () => {
    expect(normalizeActionSource("llm")).toBe("llm");
    expect(normalizeActionSource("fallback")).toBe("fallback");
    expect(normalizeActionSource("deterministic")).toBe("deterministic");
    expect(normalizeActionSource("unknown")).toBe("deterministic");
  });

  test("extracts only non-secret identity labels", () => {
    expect(identityFromActionArguments({ username: "attacker" })).toBe("attacker");
    expect(identityFromActionArguments({ password: "secret", email: "victim@example.com" })).toBe(
      "victim@example.com",
    );
    expect(identityFromActionArguments({ authorization: "Bearer secret" })).toBe("");
    expect(identityFromActionArguments(null)).toBe("");
  });

  test("packages reasoning, identity, and normalized source together", () => {
    expect(
      provenanceForAction({
        reasoning: "engine chose nuclei",
        args: { identity: "attacker", password: "secret" },
        provenance: "llm",
      }),
    ).toEqual({ reasoning: "engine chose nuclei", identity: "attacker", source: "llm" });
  });
});
