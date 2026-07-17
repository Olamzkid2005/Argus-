# Governance, Process & Legal Documentation Templates

> **Purpose:** Templates for governance, process, and legal documentation required by Audit Items 18–20, 54–60, 66, 70.
> **Status:** 📋 Templates created — populate with organization-specific details
> **Last updated:** 2026-07-17

---

## Table of Contents

1. [Dry Run Procedure (Item 18)](#1-dry-run-procedure-item-18)
2. [Independent Review Process (Item 19)](#2-independent-review-process-item-19)
3. [Autonomy Policy (Item 20)](#3-autonomy-policy-item-20)
4. [Written Authorization Enforcement (Item 54)](#4-written-authorization-enforcement-item-54)
5. [Incident Response Runbook (Item 55)](#5-incident-response-runbook-item-55)
6. [Signed Sign-off Process (Item 56)](#6-signed-sign-off-process-item-56)
7. [Versioning & Release Process (Item 57)](#7-versioning--release-process-item-57)
8. [License Compatibility Matrix (Item 58)](#8-license-compatibility-matrix-item-58)
9. [Data Retention Policy (Item 59)](#9-data-retention-policy-item-59)
10. [Third-Party Penetration Test Procedure (Item 60)](#10-third-party-penetration-test-procedure-item-60)
11. [Insurance & Liability Posture (Item 66)](#11-insurance--liability-posture-item-66)
12. [Organizational Readiness Checklist (Item 70)](#12-organizational-readiness-checklist-item-70)

---

## 1. Dry Run Procedure (Item 18)

### Purpose
Validate Argus behavior against a deliberately vulnerable target before authorizing autonomous production use.

### Prerequisites
- [ ] Argus CLI installed (verified: `argus --version`)
- [ ] Test target deployed (DVWA, WebGoat, or `test_fixtures/simple-web-app`)
- [ ] Test target URL accessible from Argus host
- [ ] Test target configured with known vulnerabilities (manifest available)

### Procedure

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Configure scope: `scope.mode: allowlist` with test target URL | Config loads without errors |
| 2 | Run scan: `argus scan <target_url> --format json` | Scan completes without errors |
| 3 | Compare results against ground truth manifest | All expected findings detected |
| 4 | Review false positive findings | < 20% FP rate |
| 5 | Review logs for errors/warnings | No unexpected errors |
| 6 | Verify engagement transitions to `complete` | Final state is complete |

### Sign-off

```markdown
**Dry Run Sign-off**
- Date: _______________
- Target: _______________
- Findings matched: ___ / ___ expected
- FN rate: ___ %
- FP rate: ___ %
- Operator name: _______________
- Signature: _______________
```

---

## 2. Independent Review Process (Item 19)

### Purpose
Ensure a qualified second reviewer independently validates audit findings and blocker tallies.

### Scope
- All audit findings marked as 🔍 Inconclusive
- All blockers documented in `docs/autonomy-blockers.md`
- Any HIGH/CRITICAL findings in the 70-item audit

### Reviewer Qualifications
- Minimum 3 years security engineering experience
- Familiarity with automated security testing tools
- No direct involvement in the original audit

### Process

1. **Blind review:** Second reviewer receives the audit checklist **without** the original status markings
2. **Independent assessment:** Reviewer independently assesses each item
3. **Reconciliation:** Compare original and independent assessments
4. **Dispute resolution:** For any disagreement (>1 severity level difference), a third reviewer breaks the tie

### Template

```markdown
**Independent Review Report**
- Reviewer name: _______________
- Review date: _______________
- Items reviewed: ___
- Agreements with original: ___ / ___
- Disagreements: ___ / ___
- Critical disagreements: ___
- Notes: _______________
- Reviewer signature: _______________
```

---

## 3. Autonomy Policy (Item 20)

### Purpose
Define clear boundaries for unattended operation of Argus.

### Policy Statement

Argus SHALL NOT operate in autonomous mode unless:

1. **Scope constraint:** `scope.mode` is set to `allowlist` (never `all`)
2. **Written authorization:** Signed authorization form (see Item 54) exists for the target
3. **Rate limits:** Outbound rate limiting is enabled (`PER_HOST_LIMITER` active)
4. **Monitoring:** Health endpoint is accessible and monitored
5. **Kill switch:** Emergency stop mechanism is tested and accessible
6. **Dry run:** Full supervised dry run completed within 7 days prior

### Prohibited Actions

Argus MUST NOT:
- Scan targets outside the explicit allowlist
- Execute denial-of-service attacks (no aggressive rate limits)
- Access or exfiltrate data without explicit authorization
- Modify or delete data on target systems
- Use credentials obtained without authorization

### Emergency Stop

```bash
# Immediate stop all running engagements
argus emergency-stop --all

# Or stop specific engagement
argus emergency-stop --engagement <id>
```

---

## 4. Written Authorization Enforcement (Item 54)

### Authorization Form Template

```markdown
# ARGUS AUTHORIZED TESTING FORM

## Engagement Details
- **Target organization:** _______________________________
- **Target scope (domains/IPs):** _______________________________
- **Testing period:** From _______________ to _______________
- **Testing types:** □ Web Application  □ Network  □ API  □ Social Engineering
- **Maximum severity without prior approval:** _______________

## Authorization
I, _______________________________, authorize Argus to conduct
security testing within the scope defined above.

I understand that:
- Testing will be conducted against the specified targets only
- Testing tools may generate traffic that could trigger defensive systems
- Findings will be reported to the authorized contact

## Signatures
**Authorizing party:**
- Name: _______________
- Title: _______________
- Organization: _______________
- Signature: _______________
- Date: _______________

**Argus operator:**
- Name: _______________
- Organization: _______________
- Signature: _______________
- Date: _______________

## Commit Hash
Authorization tied to commit: _______________
```

### Enforcement

The authorization form should be:
1. Stored in a secure, access-controlled repository
2. Referenced by engagement ID in the Argus database
3. Verified before engagement start (configurable: `require_authorization: true`)

---

## 5. Incident Response Runbook (Item 55)

### Purpose
Define the procedure to follow if Argus is counter-attacked during an engagement.

### Incident Classification

| Level | Description | Example | Response Time |
|-------|------------|---------|---------------|
| L1 | Probe / Recon | Target scans Argus back | Within 24h |
| L2 | Active Attack | Credential stuffing against Argus host | Within 4h |
| L3 | Successful Breach | Attacker gains access to Argus infrastructure | Immediate |

### L1 Response: Probe Detection

**Indicators:**
- Unexpected inbound connections on Argus host
- Argus endpoint being scanned (HTTP 404 floods)
- LLM API keys being tested from unknown IPs

**Actions:**
1. Log the source IP, timestamp, and pattern
2. Add source IP to firewall blocklist
3. No engagement interruption needed

### L2 Response: Active Attack

**Indicators:**
- Repeated failed login attempts to Argus endpoints
- Database connection attempts from unusual sources
- Distributed scan detection

**Actions:**
1. `argus emergency-stop --all` — Immediately stop all engagements
2. Rotate all API keys and credentials
3. Enable `ARGUS_MCP_BLOCK_SOCKET=1` to prevent MCP network exposure
4. Review auth logs for any successful unauthorized access
5. Notify security team

### L3 Response: Successful Breach

**Indicators:**
- Evidence of unauthorized access to Argus data
- Modified system files or configurations
- Unknown processes running on Argus host

**Actions:**
1. `argus emergency-stop --all`
2. Isolate the affected host from network immediately
3. Preserve logs and system state for forensic analysis
4. Rotate ALL credentials (API keys, database passwords, SSH keys, cloud credentials)
5. Report to relevant authorities if PII/data was exposed
6. Conduct post-incident review within 72 hours

### Communication

```markdown
**Incident Communication Template**
- Incident ID: _______________
- Discovery time: _______________
- Current status: □ Investigating □ Contained □ Resolved
- Affected systems: _______________
- Notified parties: _______________
- Next update due: _______________
```

---

## 6. Signed Sign-off Process (Item 56)

### Process

Each major release or audit milestone requires a signed sign-off tied to a specific commit hash:

1. **Prepare sign-off document** using the template below
2. **Record the commit hash** of the codebase at the time of review
3. **Obtain signatures** from:
   - Lead engineer
   - Security reviewer (if applicable)
   - Authorizing manager
4. **Store** in a signed, timestamped file in the repository or secure document storage

### Template

```markdown
# Sign-off Certificate

**Project:** Argus
**Date:** _______________
**Commit hash:** _______________
**Branch:** _______________
**Scope:** _______________

**Reviewed by:**
- [ ] All audit items verified
- [ ] Blockers documented and tracked
- [ ] Test suite passing (attached CI link)
- [ ] Known limitations documented

**Signatures:**

Lead Engineer: ___________________ Date: _______________
Security Reviewer: ___________________ Date: _______________
Authorizing Manager: ___________________ Date: _______________
```

---

## 7. Versioning & Release Process (Item 57)

### Versioning Scheme

Argus follows **Semantic Versioning 2.0.0**:

```
MAJOR.MINOR.PATCH
```

| Increment | When | Example |
|-----------|------|---------|
| MAJOR | Breaking changes (API, config format, DB schema) | 2.0.0 |
| MINOR | New features, no breaking changes | 1.3.0 |
| PATCH | Bug fixes, security patches | 1.2.1 |

### Version Source of Truth

The canonical version is stored in:
- `argus-workers/version.py` — `VERSION = "1.0.0"`
- `Argus-Tui/packages/opencode/package.json` — `"version": "1.0.0"`

### Release Process

1. **Feature freeze:** All features for the release must be merged and tested
2. **Version bump:** Update version in all source-of-truth files
3. **Changelog:** Update `CHANGELOG.md` with all changes
4. **Tag:** `git tag -a v<version> -m "Release v<version>"`
5. **CI build:** GitHub Actions builds and publishes artifacts
6. **Release notes:** Draft GitHub Release with changelog, known issues, upgrade instructions
7. **Sign-off:** Obtain sign-off per Item 56 procedure
8. **Publish:** Push tag and publish GitHub Release

### Hotfix Process

1. Branch from the release tag: `git checkout -b hotfix/v<version>-hotfix-1`
2. Apply fix, version bump (PATCH increment)
3. Tag and release per standard process
4. Merge hotfix back to main

---

## 8. License Compatibility Matrix (Item 58)

### Purpose
Ensure all 65+ wrapped tools in `_generated_tools.py` have licenses compatible with Argus's distribution model.

### Tool License Audit

| Tool | License | Compatible | Notes |
|------|---------|------------|-------|
| nuclei | MIT | ✅ | |
| httpx | MIT | ✅ | |
| katana | MIT | ✅ | |
| subfinder | MIT | ✅ | |
| ffuf | MIT | ✅ | |
| dalfox | MIT | ✅ | |
| sqlmap | GPLv2 | ✅ | Copyleft — distribute source |
| nmap | NPSL | ⚠️ Modified | Not GPL-compatible in all cases |
| wpscan | GPLv3 | ✅ | |
| semgrep | LGPL 2.1 | ✅ | |
| gitleaks | MIT | ✅ | |
| trufflehog | AGPLv3 | ⚠️ | AGPL is network-copyleft |
| bandit | Apache 2.0 | ✅ | |
| testssl.sh | GPLv2 | ✅ | |

> **Review required for:** nmap (NPSL), trufflehog (AGPLv3)
> **Action:** Consult legal counsel for distribution terms

---

## 9. Data Retention Policy (Item 59)

### Policy

| Data Type | Retention Period | Deletion Method | Notes |
|-----------|-----------------|-----------------|-------|
| Engagement findings | 90 days post-engagement completion | Secure deletion from DB | Can be extended via config |
| Raw scan artifacts | 30 days | Filesystem deletion | Screenshots, raw output |
| LLM API call logs | 7 days | DB cleanup | No PII expected |
| Auth credentials (test) | End of engagement | Programmatic wipe | |
| Audit logs | 1 year | Archival | For compliance |
| System logs | 30 days | Log rotation | stdout/stderr |

### Enforcement

- Automated cleanup via `cleanup_old_checkpoints()` in `checkpoint_manager.py`
- Celery beat task: `cleanup_expired_data` runs daily
- Configurable via `config.yaml` → `retention` section

### Legal Hold

If a legal hold is received for specific data:
1. Tag relevant engagements with `legal_hold: true`
2. Retention period is suspended for tagged data
3. Legal hold release must be documented

---

## 10. Third-Party Penetration Test Procedure (Item 60)

### Purpose
Engage an independent third party to penetration-test Argus itself.

### Vendor Selection Criteria

- CREST-certified or equivalent
- Experience with automated security testing tools
- No prior relationship with Argus development team

### Test Scope

| In Scope | Out of Scope |
|----------|--------------|
| Argus TUI (TypeScript/Bun) | Third-party APIs (OpenAI, Redis, DB) |
| Argus Workers (Python) | Wrapped tools (nuclei, sqlmap, etc.) |
| MCP transport layer | Infrastructure (CI, containers, cloud) |
| DI container and service wiring | Test fixtures |
| LLM integration and prompt handling | |

### Frequency

- **Full penetration test:** Annually, or after major architectural changes
- **Limited scope:** After security-relevant feature additions

---

## 11. Insurance & Liability Posture (Item 66)

### Recommended Coverage

| Insurance Type | Coverage | Recommended Limit |
|---------------|----------|-------------------|
| Professional Liability (Errors & Omissions) | Claims arising from missed vulnerabilities or incorrect findings | $2M |
| Cybersecurity / Data Breach | Claims from data exposure during testing | $2M |
| General Liability | Bodily injury or property damage (unlikely for software) | $1M |

### Risk Mitigations

- Clear scope of work in all engagement contracts
- Disclaimer of liability for missed vulnerabilities
- Requirement for written authorization (Item 54)
- Limitation of liability clause (capped at engagement fee)

---

## 12. Organizational Readiness Checklist (Item 70)

### People

- [ ] Dedicated security team or point of contact
- [ ] Incident response team identified
- [ ] Training on Argus operation completed
- [ ] Legal counsel reviewed authorization process

### Process

- [ ] Written authorization procedure documented and tested
- [ ] Incident response runbook reviewed by team
- [ ] Escalation path defined for critical findings
- [ ] Data retention policy communicated to stakeholders
- [ ] Versioning and release process established

### Technology

- [ ] Argus deployed in isolated environment (no access to production unless scoped)
- [ ] Monitoring and alerting configured
- [ ] Backup and restore tested
- [ ] LLM API keys configured with spending limits
- [ ] Rate limiting enabled

### Legal

- [ ] Insurance coverage in place
- [ ] License compliance verified for all wrapped tools
- [ ] Terms of service / disclaimers drafted
- [ ] Data processing agreement with LLM providers reviewed

### Audit

- [ ] Latest 70-item audit reviewed and action items tracked
- [ ] Third-party penetration test scheduled
- [ ] Sign-off obtained for current release (tied to commit hash)

---

## Appendices

### A. Document Change Log

| Date | Author | Change |
|------|--------|--------|
| 2026-07-17 | Audit Team | Initial templates created |

### B. Related Documents

- `docs/70-ITEM-FULL-REPO-AUDIT-CHECKLIST.md` — Full audit checklist
- `docs/70-ITEM-AUDIT-VERIFICATION-REPORT.md` — Audit verification report
- `docs/80-AUDIT-FINAL-SUMMARY-REPORT.md` — Final audit summary
- `docs/AUTONOMY-GAPS-COMPLETE.md` — Autonomy blocker documentation
- `docs/sandbox-isolation-plan.md` — Sandbox isolation plan
- `docs/adv-evaluation-test-plan.md` — Adversarial evaluation plan
