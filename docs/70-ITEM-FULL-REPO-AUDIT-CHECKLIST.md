# Argus — 70-Item Full Repo Audit Checklist

> **Status:** Self-review audit  
> **Scope:** Full repository safety, correctness, operational completeness, and readiness assessment

---

## Scope & Safety Defaults (1–3)

1. **Fix scope.mode default** (warn → hard-fail/allowlist in autonomous mode).
2. **Encryption default** — storage/encryption\* has dedicated code plus nightly Linux/macOS CI (`encryption-linux.yml`, `encryption-macos.yml`) testing the file-based fallback. The real gap is narrower: it's just **off by default** (`enabled: false`). Flip the default or force it on in autonomous mode.
3. **Wire the dead global assessment timer** — `assessmentStartTime` never assigned.

## Self-Attack-Surface Hardening (4–6)

4. Replace the bare-subprocess "sandbox" in chain-exploit verification with real isolation.
5. Add pacing/backoff to credential-spray attempts in `_replay_password`.
6. Extend cross-tool rate limiting into the Python post-exploitation loops.

## Browser Verification Correctness (7–11)

7. Stop `bola.ts` from proceeding on failed login.
8. Add a positive auth-success signal to `detectAuthSuccess`.
9. Wire the OAuth/SSO cookie-injection fallback that's currently a dead end.
10. Fix cookie injection's hardcoded `secure: true` default.
11. Handle multi-step login flows.

## Coverage & Operational Completeness (12–17)

12. Confirm `verifyFindings` fires end-to-end on a live target.
13. Actually run the full test suite and get it green.
14. Resolve tool-definition/script mismatches (`testssl`, Playwright, `_generated_tools.py` drift).
15. Verify the slash-command bleed fix actually landed.
16. Make emitted health/LLM-degradation signals actually change orchestrator behavior.
17. Confirm the ~14 "operational" blockers fail closed, not just fail.

## Process, Not Code (18–20)

18. Full supervised dry run against a deliberately vulnerable target.
19. Independent second-reviewer re-verification of the blocker tally.
20. Explicit written policy on unattended autonomy boundaries.

## Data Isolation, Secrets, and Injection Defense (21–30)

21. **Audit all repository classes** (not just `finding_repository.py`, which checks out) for consistent `engagement_id` scoping — one confirmed clean, others unchecked.
22. **Adversarially test `_sanitize_for_llm()`** — it's real (3000-char truncation, control-char stripping, pattern-based injection + secret redaction, single entry point for all external data) but regex-based defenses are bypassable by novel phrasing; needs red-teaming, not just code review.
23. **Determine what actually backs `secrets_manager.py`** (env vars vs KMS vs encrypted file) — module and tests exist, backing mechanism unverified.
24. **Verify checkpoint/resume** (`checkpoint_manager.py`, `decision_checkpoint.py`, `auth_checkpoint.py`) recovers cleanly from a mid-tool-call crash, not just a mid-phase one.
25. **Cost tracking** (`runtime/governance.py`) is in-memory only — `_total_cost_usd` is a plain instance attribute with no persistence found. A worker restart resets spend tracking to zero, so cumulative budget could be exceeded across a crash-and-resume.
26. **Track down whether `LlmCostTracker`** (referenced in `governance.py`'s docstring) actually exists anywhere as a persisted tracker, or is aspirational documentation — not found in the search performed.
27. **Confirm embeddings** in `pgvector_repository.py`/`embedding_service.py` are scoped per-engagement, so one client's harvested creds/findings can't surface in another engagement's LLM memory context.
28. **Verify LLM API keys** are never included in the 3000-char sanitized context that gets sent back into the LLM's own prompt (a subtle round-trip leak if `_SECRET_REDACTION_PATTERNS` misses an unusual key format).
29. **Check that `test_fixtures/simple-web-app`** (a full test fixture app) isn't reachable from or bundled into any production deployment path.
30. **Audit the 65 tool definitions** in `_generated_tools.py` for `risk_level`/`signal_quality` accuracy — these drive autonomous tool selection; a mis-rated destructive tool is a direct safety issue. Only the first ~30 lines were sampled.

## Reporting & Evidence Integrity (31–36)

31. **Review `llm_report_generator.py`** for whether it routes through `_sanitize_for_llm` before generating client-facing text — if not, injected content that survived scanning could land verbatim in a deliverable.
32. **Audit `compliance_reporting.py`** for whether framework mappings (PCI/SOC2/etc.) are accurate or LLM-guessed with false-confidence presentation.
33. **Review `executive_report_generator.py` and `bugbounty_report_generator.py`** for evidence-to-finding traceability — can a report misattribute a finding to the wrong host/engagement?
34. **Verify finding deduplication logic** (`finding_repository.py`, `tasks/diff.py`) doesn't silently merge two genuinely distinct vulnerabilities that happen to share an `(engagement_id, endpoint, type)` fingerprint.
35. **Confirm the four separate report generators** don't produce contradictory severity/confidence for the same finding when run independently.
36. **Check whether raw target response bodies** (potentially containing injected content) ever flow into a report without going through redaction first.

## Repo Hygiene & Attack Surface Reduction (37–42)

37. **New, significant finding:** The `Argus-Tui/packages/console` directory is unmodified upstream OpenCode SaaS boilerplate — a SolidStart billing console with mail templates, a "zen" hosted-LLM-proxy API (`routes/zen/v1/chat`, `models.ts`, trial/rate limiters, Redis-backed usage batching) — none of it Argus-specific (confirmed via its README, which is the generic SolidStart template README). This is real, unreviewed, unused attack surface sitting in the repo. Strip it or explicitly document it as out-of-scope/disabled.
38. If the console package is ever deployed rather than just present in the repo, **audit its own auth** (`ipRateLimiter.ts`, `keyRateLimiter.ts`) — these are upstream OpenCode's concerns, not written or reviewed by anyone working on Argus's threat model.
39. **Sweep for other un-stripped upstream fork remnants** beyond the console package — given how much dead SaaS code was found in one directory, there are likely more.
40. **Check whether CI (`lint.yml`) actually gates merges** on the full test suite, or only a "smoke" job — the workflow I read only shows a smoke job by name; confirm this isn't the entire safety net.
41. **Add dependency vulnerability scanning** (`pip-audit`, `npm audit`/Dependabot) to CI — none observed; ironic gap for a security tool to have unscanned dependencies.
42. **Confirm Python dependencies** in `requirements.txt` are pinned to exact versions, not loose ranges that could silently pull in a compromised transitive update.

## Concurrency, Infra, and Deployment (43–48)

43. **Audit `di_container.py`** for shared mutable state (like item 25's in-memory cost tracker) that could leak or race across concurrently-running engagements in the same process.
44. **Confirm the MCP server's stdio transport** (verified local-only, no network listener currently) has an explicit test/assertion preventing it from ever being exposed over network without auth in a future deployment change.
45. **Review Celery task concurrency settings** for whether two workers could pick up conflicting tasks on the same engagement (double-execution of a destructive action).
46. **Check Redis usage across the codebase** (engagement cancellation flags, console rate limiters, Celery broker) for a single shared instance risk — if console (item 37) and Argus workers share the same Redis, a console-side issue could touch Argus's cancellation/task state.
47. **Verify database migration ordering and rollback safety** (27 migration files exist) — confirm there's a tested rollback path, not just forward-only migrations.
48. **Confirm `pause_project`/infra-lifecycle style operations** (if any exist for the Postgres/Redis stack) can't be triggered accidentally by an autonomous run.

## LLM Behavior & Prompt Quality (49–53)

49. **Review the actual prompt templates** in `agent_prompts.py` for bias or leading language that could push the LLM toward over- or under-reporting findings.
50. **Check whether the LLM is ever given the ability to mark its own output as "verified"** without independent tool confirmation — conflating LLM confidence with actual verification would inflate false-positive-with-high-confidence findings.
51. **Audit `intent_parser.py` and `llm_parser_fallback.py`** for what happens when LLM output doesn't parse as expected — silent fallback to a default action, or hard failure?
52. **Confirm token/cost estimates** in `_estimate_token_usage` (`governance.py`) are realistic — if underestimated, the cost guard in item 25 undercounts spend even before the persistence problem.
53. **Review `ai_explainer.py` and `poc_generator.py`** (both flagged as prompt-injection-aware) for whether generated PoC code is also subject to the same subprocess-isolation gap as item 4.

## Legal, Process, and Governance (54–60)

54. **Confirm the system enforces or logs proof of written authorization** before an autonomous run starts, not just documents it as an operator responsibility in the README.
55. **Formal incident-response runbook** for Argus itself being detected/counter-attacked mid-engagement.
56. **Get a dated sign-off tied to a specific commit hash**, given how fast this repo moves — the roadmap doc and the blockers doc have already diverged from each other within days.
57. **Define a clear versioning/release process** so "is it ready" has a stable target instead of a continuously moving master.
58. **Confirm license compatibility for all 65 wrapped security tools** (nuclei, sqlmap, etc.) — some have licenses with usage restrictions that could matter for a commercial/autonomous product wrapping them.
59. **Document data retention policy** — how long are client engagement findings, credentials, and LLM conversation logs kept, and is there a deletion mechanism.
60. **Third-party penetration test of Argus itself**, performed by someone outside the project, before any claim of "full autonomous red-team readiness" — every item above is still self-review; an external adversarial test is the actual bar, not a checklist.

## Supply Chain & Data Residency (61–63)

61. **Add binary/supply-chain integrity checking** for the 65 wrapped tools. No checksum/signature verification of nuclei, sqlmap, ffuf, etc. exists in `tool_runner.py`. Even with everything else fixed, Argus trusts whatever binary is on `$PATH` under that name — a compromised or trojaned tool binary on the host is invisible to it. Add checksum pinning or at minimum a `--version` sanity check against known-good output.

62. **Document LLM data-residency implications** as a client-facing disclosure. The LLM provider is env-driven and defaults to `gpt-4o-mini` via OpenAI, with Gemini as an alternate path (`llm_client.py`). Target recon data, discovered credentials (post-redaction), and vulnerability details leave the pentester's environment to a third-party API by design. This may be contractually unacceptable for some client engagements regardless of redaction quality.

63. **Add HTML output sanitization to all report generators.** Only `compliance_reporting.py` shows any escaping/sanitization awareness; the other three report generators have not been confirmed. If executive/bug-bounty reports embed raw finding data (which can contain attacker-influenced strings, e.g. an XSS payload the tool itself discovered) into an HTML report without escaping, opening that report in a browser could re-trigger the very vulnerability class it's documenting.

## Adversarial Resilience & Long-Run Quality (64–70)

64. **Conduct adversarial evaluation** against a target that's actively trying to fingerprint and evade Argus — everything so far assumes a passive/vulnerable target. A red-team tool eventually meets defended targets that detect automated tooling and either feed it false data or actively counter-probe.

65. **Build a behavioral regression suite** pinned to expected outputs to catch model behavior drift across LLM provider/version changes. A provider-side model update could silently change replanning behavior, risk tolerance, or false-positive rate without any code change on Argus's side.

66. **Define insurance/liability posture** — once this is genuinely capable of autonomous lateral movement and credential replay against real infrastructure, "who is liable if it causes an outage or data exposure during an authorized engagement" needs professional liability coverage and contract language.

67. **Implement chain-of-custody for evidence** — if findings from this tool are ever used in a legal or compliance context (breach notification, regulatory audit), the evidence needs a defensible chain of custody (who ran it, when, against what scope, with what tool versions).

68. **Benchmark false-negative rate** against a known-vulnerable corpus with known ground truth. This entire review has focused on false positives because that's what's visible in code. False negatives (missing a real vulnerability because a tool timed out, a verifier fell back silently, or scope was too conservative) are harder to audit and arguably more dangerous for a client relying on this for assurance.

69. **Test for long-run engagement drift** — an autonomous engagement running for many hours accumulates context, hypotheses, and state. Verify whether quality degrades over a long run (context window pressure, stale hypotheses crowding out new signal, memory bloat) versus a short one.

70. **Address organizational readiness, not just tool readiness** — even a perfect tool needs an operator who knows when to intervene, understands its failure modes, and can read its output critically. At some point "is Argus ready" stops being a code question and becomes "is the team running it ready."

---

## Summary

| Category | Items |
|---|---|
| Scope & Safety Defaults | 1–3 |
| Self-Attack-Surface Hardening | 4–6 |
| Browser Verification Correctness | 7–11 |
| Coverage & Operational Completeness | 12–17 |
| Process, Not Code | 18–20 |
| Data Isolation, Secrets, and Injection Defense | 21–30 |
| Reporting & Evidence Integrity | 31–36 |
| Repo Hygiene & Attack Surface Reduction | 37–42 |
| Concurrency, Infra, and Deployment | 43–48 |
| LLM Behavior & Prompt Quality | 49–53 |
| Legal, Process, and Governance | 54–60 |
| Supply Chain & Data Residency | 61–63 |
| Adversarial Resilience & Long-Run Quality | 64–70 |
| **Total** | **70** |
