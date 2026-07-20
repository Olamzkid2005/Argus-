# Governance, Process & Legal Documentation

> **Purpose:** Governance, process, and legal documentation for Argus operation
> **Status:** ✅ Populated — reviewed for individual/solo practitioner context
> **Organization:** David Olamijulo
> **Deployment:** Local development machine
> **Last updated:** 2026-07-19

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

### Recommended Test Targets

| Target | Setup | Difficulty | Notes |
|--------|-------|------------|-------|
| **DVWA** (Damn Vulnerable Web Application) | `docker run -d -p 80:80 vulnerables/web-dvwa` | Easy | Best first target — simple, well-documented |
| **WebGoat** | `docker run -d -p 8080:8080 webgoat/goatandwolf` | Medium | More scenarios, good for API testing |
| `test_fixtures/simple-web-app` | Local (in-repo) | Easy | Always available, no network needed |

### Prerequisites
- [ ] Argus CLI installed (verified: `argus --version`)
- [ ] Test target deployed (DVWA recommended for first run)
- [ ] Test target accessible from `http://localhost:<port>`
- [ ] Test target configured with known vulnerabilities (ground truth manifest prepared)

### Procedure

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Deploy DVWA: `docker run -d -p 80:80 vulnerables/web-dvwa` | Container running, accessible at localhost |
| 2 | Configure scope: `scope.mode: allowlist` with `localhost` | Config loads without errors |
| 3 | Run scan: `argus scan http://localhost --format json` | Scan completes within expected time |
| 4 | Compare results against DVWA ground truth manifest | All expected findings detected |
| 5 | Review false positive findings | < 20% FP rate |
| 6 | Review logs for errors/warnings | No unexpected errors |
| 7 | Verify engagement transitions to `complete` | Final state is complete |

### Success Criteria

| Metric | Target |
|--------|--------|
| True positive rate | ≥ 80% of known vulnerabilities detected |
| False positive rate | < 20% |
| Scan completion | 100% (no crashes) |
| Regression | No regressions from previous dry run |

### Sign-off

```markdown
**Dry Run Sign-off**
- Date: _______________
- Target: _______________
- Findings matched: ___ / ___ expected
- FN rate: ___ %
- FP rate: ___ %
- Operator name: David Olamijulo
- Signature: _______________
- Notes: _______________
```

---

## 2. Independent Review Process (Item 19)

### Purpose
Ensure a qualified second reviewer independently validates audit findings and blocker tallies.

### Scope
- All audit findings marked as 🔍 Inconclusive
- All blockers documented in `docs/autonomy-blockers.md`
- Any HIGH/CRITICAL findings in the 70-item audit

### Review Model (Solo Practitioner)

As a solo operator, independent review can be obtained through:

| Option | Description | Cost |
|--------|-------------|------|
| **Peer review exchange** | Partner with another security consultant for reciprocal reviews | Free (time trade) |
| **Bugcrowd / HackerOne peer** | Engage a vetted security researcher from a platform | $500–$2,000 per review |
| **Open source community** | Post anonymized findings to relevant security communities | Free |
| **Consultant engagement** | Hire a third-party security consultant for formal review | $2,000–$5,000 per review |

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
- Review model: □ Peer exchange  □ Platform  □ Community  □ Paid consultant
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
Define clear boundaries for unattended operation of Argus in a local development environment.

### Scope
This policy applies to all Argus operations performed by **David Olamijulo** as an individual security consultant operating from a local development machine.

### Mandatory Conditions

Argus SHALL NOT operate in autonomous mode unless **ALL** of the following are true:

1. **Scope constraint:** `scope.mode` is explicitly set to `allowlist` with the target domain/IP listed in `allowed_targets`
2. **Written authorization:** Signed authorization form (see Item 54) exists for the target and is stored locally
3. **Rate limits:** Outbound rate limiting is enabled (`PER_HOST_LIMITER` active with ≤ 10 req/s per host)
4. **Monitoring:** Terminal output is visible and operator is present (no fully unattended operation)
5. **Kill switch:** `Ctrl+C` or `argus emergency-stop --all` is accessible and tested
6. **Dry run:** Full supervised dry run completed within 7 days prior against DVWA or equivalent
7. **Network isolation:** Argus is running from a local machine with no exposed remote access to third parties

### Prohibited Actions

Argus MUST NOT:
- Scan targets outside the explicit allowlist
- Execute denial-of-service attacks (no aggressive rate limits, max 10 req/s per host)
- Access or exfiltrate data without explicit authorization in the testing agreement
- Modify or delete data on target systems
- Use credentials obtained during testing outside the authorized scope
- Run in autonomous mode while operator is away from the terminal

### Emergency Stop

```bash
# Immediate stop all running engagements (requires the emergency-stop command)
# If the command is not yet available, use process-level kill:
argus emergency-stop --all

# Or stop specific engagement by ID
argus emergency-stop --engagement <engagement-uuid>

# Last resort — kill all worker processes
pkill -f "argus-workers"
```

> **Note:** The `argus emergency-stop` command may need to be implemented or aliased. Verify it exists in your current build. The `pkill` fallback always works on Unix systems. On Windows, use Task Manager or `taskkill /F /IM python*` from an admin terminal.

### Local Machine Safety Checklist

Before starting any engagement from a local machine:
- [ ] VPN/firewall rules verified — no unintended network exposure
- [ ] API keys are scoped (not admin-level keys)
- [ ] Spending limits set on LLM provider accounts
- [ ] Host firewall active (no inbound connections on unexpected ports)
- [ ] Engagement expected duration logged

---

## 4. Written Authorization (Item 54)

### Purpose
Document client authorization before conducting any security testing. For a solo consultant, this is a legal safeguard that protects both you and your client.

### Authorization Form

```markdown
# ARGUS AUTHORIZED TESTING FORM

## Engagement Details
- **Consultant:** David Olamijulo
- **Target organization:** _______________________________
- **Target scope (domains/IPs):** _______________________________
- **Testing period:** From _______________ to _______________
- **Testing types:** □ Web Application  □ Network  □ API  □ Mobile
- **Maximum severity without prior approval:** _______________
- **Engagement ID:** _______________

## Authorization
I, _______________________________, represent the above-named
organization and authorize David Olamijulo to conduct automated
security testing within the scope defined above.

I understand that:
- Testing will be conducted against the specified targets only
- Testing tools may generate traffic that could trigger defensive systems
- Findings will be reported to the authorized contact listed below
- No data will be exfiltrated or stored beyond the scope of the engagement

## Findings Contact
- **Name:** _______________
- **Email:** _______________
- **Preferred severity for immediate notification:** _______________

## Signatures
**Authorizing party:**
- Name: _______________
- Title: _______________
- Organization: _______________
- Email: _______________
- Signature: _______________
- Date: _______________

**Security consultant:**
- Name: David Olamijulo
- Signature: _______________
- Date: _______________

## Commit Hash
Argus version tied to this authorization: _______________
```

> **Note:** The signature fields are intentionally left blank in the template — they should be hand-signed (or digitally signed) when the form is executed with a client.

### Storage & Enforcement

As a local operator, the authorization form should be:
1. Stored in an encrypted local directory (e.g., `~/.argus/authorizations/`)
2. Referenced by engagement ID in the Argus database
3. Name the file as `{engagement_id}-authorization.pdf` for easy lookup
4. Verified manually before each engagement — set a reminder in your calendar

### Recommended Workflow

1. Client signs the authorization form (DocuSign, Adobe Sign, or scanned PDF)
2. Store in `~/.argus/authorizations/{client_name}/`
3. Create a new engagement in Argus: `argus engagement create`
4. Note the engagement ID in the stored authorization file
5. Verify scope matches before starting the scan

---

## 5. Incident Response Runbook (Item 55)

### Purpose
Define the procedure to follow if Argus is counter-attacked during an engagement. As a solo operator running from a local machine, the primary risk is:
1. Your local machine being compromised through an engagement
2. LLM API keys being stolen and used fraudulently
3. Client data being exposed through a breach of your machine

### Incident Classification

| Level | Description | Example | Response Time |
|-------|------------|---------|---------------|
| L1 | Probe / Recon | Target scans your IP back; unusual inbound connections | Within 24h |
| L2 | Active Attack | Credential stuffing against your machine; LLM key abuse detected | Within 4h |
| L3 | Successful Breach | Attacker gains access to your local machine or data | Immediate |

### L1 Response: Probe Detection

**Indicators:**
- Unexpected inbound connections on local machine (check `netstat -an | findstr LISTEN`)
- Argus endpoint being scanned (unusual 404 responses in logs)
- LLM API keys being tested from unknown IPs (check provider dashboards)

**Actions:**
1. Log the source IP, timestamp, and pattern to `~/.argus/incidents/`
2. Add source IP to host firewall blocklist
3. No engagement interruption needed — document and continue
4. Check if the probe is target-related (client testing your security)

### L2 Response: Active Attack

**Indicators:**
- Repeated failed login attempts to local machine (SSH, RDP, etc.)
- LLM provider dashboard showing API calls from unknown IPs/locations
- Unknown outbound connections from your machine

**Actions:**
1. `argus emergency-stop --all` — Immediately stop all engagements
2. Disconnect from network (toggle Wi-Fi / unplug Ethernet)
3. Rotate ALL API keys (LLM providers, GitHub, cloud credentials)
4. Review auth logs for any successful unauthorized access
5. Contact LLM provider support to report key compromise
6. Scan local machine for malware/unauthorized access

### L3 Response: Successful Breach

**Indicators:**
- Evidence of unauthorized access to local files (modified `.argus/` directory)
- Unknown processes or scheduled tasks running
- Files encrypted (ransomware) or exfiltrated
- LLM provider confirms API key used by unknown third party with large bills

**Actions:**
1. `argus emergency-stop --all` (if still possible)
2. **Immediately disconnect from all networks**
3. Power off the machine (pull the plug) to preserve evidence
4. Boot from a trusted USB/restore from clean backup
5. Report stolen API keys to all providers immediately
6. Rotate ALL credentials (LLM, GitHub, cloud, email, banking)
7. Report incident to relevant authorities if client PII was stored locally
8. Notify affected clients within 24 hours
9. Conduct post-incident review before resuming any engagements

### Pre-Incident Mitigations (Do These Now)

- [ ] Enable MFA on all LLM provider accounts
- [ ] Set spending limits/alerts on LLM accounts (e.g., $10 max per day)
- [ ] Use scoped API keys (never admin-level keys for Argus)
- [ ] Store client authorization forms encrypted (GPG or BitLocker)
- [ ] Regular backups of `~/.argus/` directory
- [ ] Keep local OS and firewall updated
- [ ] Run Argus in a separate VM or container when possible

### Communication Template

```markdown
**Incident Communication**
- Incident ID: _______________
- Discovery time: _______________
- Current status: □ Investigating □ Contained □ Resolved
- Affected systems: _______________
- Affected clients: _______________
- Notified parties: _______________
- Next update due: _______________
```

---

## 6. Signed Sign-off Process (Item 56)

### Process

Each major release or audit milestone requires a signed sign-off tied to a specific commit hash. For a solo operator, sign-off serves as a personal accountability record.

1. **Prepare sign-off document** using the template below
2. **Record the commit hash** of the codebase at the time of review
3. **Self-sign** as the operator
4. **If peer review was obtained** (see Item 19), include the reviewer's sign-off
5. **Store** in `docs/governance/sign-offs/` with a dated filename

### Template

```markdown
# Sign-off Certificate

**Project:** Argus
**Date:** _______________
**Commit hash:** _______________
**Branch:** _______________
**Scope:** _______________

**Checklist:**
- [ ] All audit items reviewed and statuses assigned
- [ ] Blocker items documented and tracked
- [ ] Test suite passing (attach CI link or local output)
- [ ] Known limitations documented
- [ ] Governance templates reviewed and current

**Signed by:**

Operator: David Olamijulo           Date: _______________

**Peer reviewer (if applicable):**

Reviewer: ___________________       Date: _______________
```

> **Note:** Signature fields are intentionally left blank in this template — sign manually or digitally when the sign-off is executed.


### Sign-off Storage

Save sign-off files in `docs/governance/sign-offs/YYYY-MM-DD-{milestone}-signoff.md`

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

### Release Process (Solo Practitioner)

1. **Feature freeze:** Ensure all features for the release are merged and tested locally
2. **Version bump:** Update version in all source-of-truth files (check for both Python and Node)
3. **Changelog:** Update `CHANGELOG.md` with all changes since last release
4. **Run full test suite:** `pytest tests/` and `bun test` — must be green
5. **Tag:** `git tag -a v<version> -m "Release v<version>"`
6. **Push tag:** `git push origin v<version>`
7. **GitHub Release:** Draft release with changelog, known issues, and upgrade instructions from `CHANGELOG.md`
8. **Sign-off:** Complete sign-off per Item 56 and store in `docs/governance/sign-offs/`

### Hotfix Process

1. Branch from the release tag: `git checkout -b hotfix/v<version>-hotfix-1`
2. Apply fix, version bump (PATCH increment)
3. Tag and release per standard process
4. Merge hotfix back to main

---

## 8. License Compatibility Matrix (Item 58)

### Purpose
Ensure all wrapped tools in `_generated_tools.py` have licenses compatible with Argus's distribution model.

> **Note for solo practitioner:** As an individual user running Argus locally for client engagements (not redistributing), license compatibility is primarily about ensuring your use of each tool complies with its terms. Distribution/sublicensing concerns apply only if you package and sell Argus.

### Tool License Audit

| Tool | License | Compatible (Local Use) | Compatible (Distribution) | Notes |
|------|---------|------------------------|---------------------------|-------|
| nuclei | MIT | ✅ | ✅ | |
| httpx | MIT | ✅ | ✅ | |
| katana | MIT | ✅ | ✅ | |
| subfinder | MIT | ✅ | ✅ | |
| ffuf | MIT | ✅ | ✅ | |
| dalfox | MIT | ✅ | ✅ | |
| sqlmap | GPLv2 | ✅ | ⚠️ | Copyleft — must distribute source |
| nmap | NPSL | ✅ | ⚠️ | Modified NPSL — may restrict commercial use |
| wpscan | GPLv3 | ✅ | ⚠️ | Copyleft — must distribute source |
| semgrep | LGPL 2.1 | ✅ | ✅ | |
| gitleaks | MIT | ✅ | ✅ | |
| trufflehog | AGPLv3 | ✅ | ⚠️ | AGPL is network-copyleft |
| bandit | Apache 2.0 | ✅ | ✅ | |
| testssl.sh | GPLv2 | ✅ | ⚠️ | Copyleft — must distribute source |
| commix | GPLv3 | ✅ | ⚠️ | Copyleft |
| arjun | AGPLv3 | ✅ | ⚠️ | Network-copyleft |
| gospider | GPLv3 | ✅ | ⚠️ | Copyleft |
| nikto | GPLv2 | ✅ | ⚠️ | Copyleft |
| jwt_tool | GPLv3 | ✅ | ⚠️ | Copyleft |

> **Assessment for local use:** All tools are ✅ compatible for running Argus as a local security assessment tool. Redistribution requires legal review.
> **Requires legal review for distribution:** nmap (NPSL), trufflehog (AGPLv3), arjun (AGPLv3)

---

## 9. Data Retention Policy (Item 59)

### Purpose
Define how engagement data is retained and disposed of when running Argus from a local machine.

### Policy

| Data Type | Retention Period | Deletion Method | Storage Location |
|-----------|-----------------|-----------------|------------------|
| Engagement findings | 90 days post-engagement completion | Secure deletion from PostgreSQL | Local PostgreSQL DB |
| Raw scan artifacts | 30 days | Filesystem deletion | `~/.argus/artifacts/` |
| LLM API call logs | 7 days | DB cleanup | Local PostgreSQL DB |
| Auth credentials (test) | End of engagement | Programmatic wipe | In-memory / temp files |
| Client authorization forms | 2 years (or as required by contract) | Secure file deletion | `~/.argus/authorizations/` (encrypted) |
| Audit logs | 1 year | Manual archival | `~/.argus/logs/` |
| System logs | 30 days | Log rotation | stdout/stderr / log files |

### Enforcement (Local Machine)

- Automated cleanup via `cleanup_old_checkpoints()` in `checkpoint_manager.py`
- Manual enforcement: run `argus maintenance cleanup` at end of each engagement
- Configurable via `config.yaml` → `retention` section
- **Added local responsibility:** Check `~/.argus/` directory quarterly for leftover data

### Client Data Handling

When a client engagement completes:
1. Deliver final report to client
2. After 90 days (or per contract), delete engagement findings
3. After 30 days, delete raw scan artifacts (screenshots, HAR files, raw tool output)
4. Confirm deletion with client if required by contract
5. Keep only the final report and authorization form for record-keeping

### Legal Hold

If a legal hold is received for specific data (e.g., client engaged in litigation):
1. Copy relevant data to `~/.argus/legal-holds/{case-reference}/`
2. Do NOT delete any data related to the hold
3. Document the hold reference and date
4. Legal hold release must be documented before deletion

---

## 10. Third-Party Penetration Test Procedure (Item 60)

### Purpose
Engage an independent third party to penetration-test Argus itself.

### When to Test

For a solo practitioner, third-party pen testing of Argus itself is recommended:
- **Before offering Argus as a service** to multiple clients (if transitioning from solo consulting to a service model)
- **After major architectural changes** to core modules (MCP, DI container, LLM client)
- **Annually** if Argus is actively used for client engagements
- **Before public release** if open-sourcing Argus

### Budget Planning

| Test Type | Estimated Cost | Duration |
|-----------|---------------|----------|
| Basic web application scan (automated + manual review) | $2,000–$5,000 | 1–2 weeks |
| Full penetration test (manual + automated) | $5,000–$15,000 | 2–4 weeks |
| Source code review (Argus Workers only) | $3,000–$8,000 | 1–2 weeks |
| Full scope (all of the above) | $10,000–$25,000 | 3–6 weeks |

### Vendor Selection Criteria

- CREST-certified or equivalent
- Experience with automated security testing tools
- No prior relationship with Argus development
- Willing to sign NDA (since source code review is involved)

### Test Scope

| In Scope | Out of Scope |
|----------|--------------|
| Argus Workers (Python) — core agent loop, MCP, governance | Third-party APIs (OpenAI, Anthropic, Redis, PostgreSQL) |
| Argus TUI (TypeScript/Bun) — CLI commands, config loading | Wrapped tools (nuclei, sqlmap, nmap, etc.) |
| MCP transport layer | Test fixtures and test code |
| DI container and service wiring | Documentation and governance files |
| LLM integration and prompt handling | |
| Evidence chain-of-custody | |

### Recommended Schedule

| Interval | Action |
|----------|--------|
| **Initial** | Full pen test before first client engagement |
| **Annually** | Full pen test |
| **Quarterly** | Self-review using the 70-item audit checklist |
| **Per release** | Security regression check on changed modules |

---

## 11. Insurance & Liability Posture (Item 66)

### Purpose
Understand your risk profile and liability exposure as a solo security consultant operating Argus.

### Risk Profile Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Missed vulnerability leads to client breach | Medium | High | Clear scope, disclaimer in contract |
| Argus causes service disruption on target | Low | High | Rate limiting, scope controls, ethical use policy |
| LLM API key stolen and used fraudulently | Medium | Medium | Scoped keys, spending limits, MFA |
| Client data exposed through local machine breach | Low | Critical | Encryption, backups, minimal data storage |
| **Total risk score** | **Medium-Low** | | |

### Insurance Recommendations

For a solo operator, insurance decisions depend on client requirements:

| Insurance Type | When Needed | Estimated Annual Cost |
|---------------|-------------|---------------------|
| Professional Liability (Errors & Omissions) | When working with enterprise clients | $500–$1,500 |
| Cybersecurity / Data Breach | When handling sensitive client data | $1,000–$3,000 |
| General Liability | Rarely needed for solo security consultants | $300–$800 |

**Minimum recommendation for client work:** Professional Liability ($1M–$2M coverage)

### Liability Mitigations (Immediate — No Cost)

- [ ] Include a clear **scope of work** in all engagement contracts
- [ ] Include a **disclaimer of liability** for missed vulnerabilities
- [ ] Always obtain written authorization before testing (Item 54)
- [ ] Include a **limitation of liability** clause (capped at engagement fee)
- [ ] Never test without explicit written permission
- [ ] Never store client data longer than necessary (Item 59)
- [ ] Keep LLM API spending limits low ($10 max per engagement default)

---

## 12. Organizational Readiness Checklist (Item 70)

### Purpose
Track readiness milestones for operating Argus as a solo security consultant.

### Current Status

| Category | Status | Notes |
|----------|--------|-------|
| **People** | 🔲 Not Started | Need to identify peer reviewer, legal counsel |
| **Process** | ✅ Templates Complete | All process templates defined in this document |
| **Technology** | 🔲 In Progress | Encryption, backups, and API key limits need verification |
| **Legal** | 🔲 Not Started | Insurance, contracts, and disclaimers need action |
| **Audit** | ✅ Largely Complete | 50/70 items resolved; 5 refuted; 15 need org action |

### People

- [ ] Self-assessment: skills and knowledge to operate Argus safely
- [ ] Incident response plan understood and practiced
- [ ] Legal counsel identified for contract review (if needed)
- [ ] Backup/peer reviewer identified (for Items 19, 60)

### Process

- [ ] Written authorization procedure documented and tested (Item 54) — **Template complete**
- [ ] Incident response runbook reviewed (Item 55) — **Template complete**
- [ ] Escalation path defined for critical findings
- [ ] Data retention policy understood (Item 59) — **Template complete**
- [ ] Versioning and release process established (Item 57) — **Template complete**

### Technology

- [ ] Argus running on local machine with no unintended network exposure
- [ ] Host firewall active and configured
- [ ] Local backups configured (`~/.argus/` directory)
- [ ] LLM API keys configured with spending limits ($10 max per engagement default)
- [ ] Rate limiting enabled (`PER_HOST_LIMITER` active)
- [ ] Encryption enabled (`storage.encryption.enabled: true` recommended)
- [ ] MCP transport secured via stdio-only (`ARGUS_MCP_BLOCK_SOCKET=1` for extra safety)

### Legal

- [ ] Professional Liability insurance in place (recommended for client work)
- [ ] Engagement contract template created with:
  - Scope of work
  - Limitation of liability clause
  - Disclaimer for missed vulnerabilities
  - Data handling and retention terms
- [ ] Written authorization form ready (Item 54) → **Template complete**
- [ ] Terms of service / disclaimers drafted for client-facing materials

### Audit

- [ ] 70-item audit reviewed — **Complete (2026-07-17)**
- [ ] All ✅ Fixed items confirmed applied — **Complete**
- [ ] All 🔍 Inconclusive items reviewed with action plan
- [ ] Dry run completed against DVWA or WebGoat within last 7 days (Item 18)
- [ ] Sign-off obtained for current release (Item 56)

---

## Appendices

### A. Document Change Log

| Date | Author | Change |
|------|--------|--------|
| 2026-07-17 | Audit Team | Initial templates created |
| 2026-07-19 | David Olamijulo | Populated with solo practitioner context — local machine deployment, individual operator workflows, updated license matrix, risk-tailored incident response, practical insurance guidance, and organizational readiness checklist |

### B. Related Documents

- `docs/70-ITEM-FULL-REPO-AUDIT-CHECKLIST.md` — Full audit checklist (50/70 resolved)
- `docs/70-ITEM-AUDIT-VERIFICATION-REPORT.md` — Audit verification report
- `docs/80-AUDIT-FINAL-SUMMARY-REPORT.md` — Final audit summary
- `docs/AUTONOMY-GAPS-COMPLETE.md` — 30 autonomy blockers
- `docs/sandbox-isolation-plan.md` — Sandbox isolation implementation plan (Item 4)
- `docs/adv-evaluation-test-plan.md` — Adversarial evaluation test plan (Item 64)
- `docs/autonomy-blockers.md` — Full autonomy blocker analysis
