# Argus Security Scanner Enhancements — Implementation Plan

## Architecture Overview

**Key integration points:**
- **`argus-workers/tools/web_scanner.py`** — 2147 lines, 30 check methods, `_safe_request()` uses thread-local sessions (ignores `self.session` for auth), `_add_finding(type, severity, endpoint, evidence, confidence)`, `scan()` dispatches via `ThreadPoolExecutor(max_workers=6)`
- **`argus-workers/orchestrator_pkg/scan.py`** — `execute_scan_tools()` instantiates `WebScanner` per target with `authenticated_session` (unused by `_safe_request` currently)
- **`argus-workers/tools/auth_manager.py`** — `AuthManager` + `AuthConfig` dataclass, returns authenticated `requests.Session`
- **`argus-workers/custom_rules/bugbounty_rules/`** — YAML rules auto-loaded by `CustomRuleEngine`, line-by-line regex scanning

---

## Changes Summary

| File | Action | Lines |
|------|--------|-------|
| `web_scanner.py` | Fix `_safe_request()` + 9 new check methods + update checks list | ~+550 |
| `dual_auth_scanner.py` | **NEW** — BOLA/BOPLA cross-account testing | ~250 |
| `ai_vuln_scanner.py` | **NEW** — Prompt injection + info disclosure | ~180 |
| `orchestrator_pkg/scan.py` | Wire DualAuthScanner + AIVulnScanner | ~+35 |
| `custom_rules/bugbounty_rules/data_exposure.yaml` | **NEW** — 10 plaintext detection rules | ~120 |

---

## Step 0: Fix `_safe_request()` — Add `session` Parameter

**File:** `argus-workers/tools/web_scanner.py`, method `_safe_request`

Add optional `session` parameter. When provided, use it instead of thread-local.

## Step 1: New Check Methods in `web_scanner.py`

### 1a. `check_financial_logic()` — negative/zero/massive amounts + replay
### 1b. `check_file_upload()` — PHP upload, double extension, path traversal
### 1c. `check_token_storage()` — localStorage JWT detection
### 1d. `check_session_expiration()` — JWT exp claim analysis
### 1e. `check_password_reset_strength()` — weak numeric/SHORT reset tokens
### 1f. `check_rate_limiting()` — 20 rapid requests, check for 429
### 1g. `check_race_conditions()` — 5 simultaneous requests, double-spend
### 1h. `check_bopla()` — response field scanning against sensitive field blocklist
### 1i. `check_predictable_identifiers()` — entropy analysis of sequential IDs
### Extend: `check_graphql_introspection()` — depth limit + SQLi resolver test

## Step 2: Create `tools/dual_auth_scanner.py`

## Step 3: Create `tools/ai_vuln_scanner.py`

## Step 4: Create `custom_rules/bugbounty_rules/data_exposure.yaml`

## Step 5: Wire into `orchestrator_pkg/scan.py`
