import { describe, expect, test } from "bun:test";
import { normalizeWorkerBudgetStatus } from "../../../../src/argus/bridge/mcp-client";

describe("normalizeWorkerBudgetStatus", () => {
  test("sorts and deduplicates worker ledger entries", () => {
    expect(
      normalizeWorkerBudgetStatus({
        engagementId: "ENG-1",
        toolCalls: 3,
        executedTools: ["nmap", "nuclei", "nmap"],
        identities: ["victim", "attacker", "victim"],
        sessions: 2,
      }),
    ).toEqual({
      engagementId: "ENG-1",
      toolCalls: 3,
      executedTools: ["nmap", "nuclei"],
      identities: ["attacker", "victim"],
      sessions: 2,
    });
  });

  test("rejects malformed ledgers before checkpoint persistence", () => {
    expect(() =>
      normalizeWorkerBudgetStatus({
        engagementId: "ENG-1",
        toolCalls: -1,
        executedTools: [],
        identities: [],
        sessions: 0,
      }),
    ).toThrow("malformed agent_budget ledger");
    expect(() =>
      normalizeWorkerBudgetStatus({
        engagementId: "",
        toolCalls: 1,
        executedTools: ["nuclei"],
        identities: ["attacker"],
        sessions: 1,
      }),
    ).toThrow("malformed agent_budget ledger");
  });
});
