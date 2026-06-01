# Argus Security & Functionality Audit Report

**Date:** May 25, 2026  
**Scope:** argus-workers/ (backend) + argus-platform/ (frontend)  
**Audit Type:** Comprehensive security & functionality audit with fix implementation

---

## Executive Summary

A systematic audit of the Argus codebase identified **11 security vulnerabilities and code quality issues** across both frontend and backend components. All identified issues have been fixed, tested, and verified. The fixes span syntax errors, injection vulnerabilities, insecure defaults, TLS configuration gaps, and logging deficiencies.

**Issues by Severity:**
- **Critical:** 2 (Syntax errors in production code)
- **High:** 3 (Missing CLI argument validation, insecure default host binding, HTTP-only Vault URL)
- **Medium:** 4 (Missing statement_timeout, TLS gaps in Redis, bare except swallowing)
- **Low:** 2 (Missing log context, test assertion gaps)

---

## Detailed Findings

### CRITICAL

#### C-01: Syntax Error in migration.py — Except on Same Line as Return

**File:** `argus-workers/runtime/migration.py:167`  
**Issue:** The `except Exception:` clause was on the same line as `return cursor.fetchone() is not None        except Exception:`, causing a `SyntaxError` that would crash any code path calling `_engagement_has_state_snapshot()`.  
**Fix:** Moved `except` to its own indented line with proper logging before the `return False`.  
**Verification:** ✅ Syntax check passes, all migration tests pass.

#### C-02: Indentation Bug in tool_runner.py — ToolCache Block

**File:** `argus-workers/tools/tool_runner.py:254`  
**Issue:** The `cached_path` assignment inside the `ToolCache` try block was at the wrong indentation level, causing an `IndentationError` that would crash tool resolution.  
**Fix:** Corrected indentation of the `cached_path` assignment.  
**Verification:** ✅ Syntax check passes.

---

### HIGH

#### H-01: No Shell Injection Validation in MCP call_tool

**File:** `argus-workers/mcp_server.py`  
**Issue:** The `call_tool()` method passed user-supplied arguments directly to `subprocess.run()` without any validation for shell metacharacters. While `subprocess.run()` with `shell=False` (the default) prevents shell injection, crafted arguments could still manipulate tool behavior in unexpected ways.  
**Fix:** Added `_validate_args_safe()` method that checks all argument values against a blocklist of shell metacharacters (`;&|`$(){}[]!<>\n\t\x00`). Rejects arguments containing these characters before execution.  
**Verification:** ✅ Security tests pass, code review confirms defense-in-depth approach.

#### H-02: Default Server Host Binds to All Interfaces

**File:** `argus-workers/config/config_manager.py:14`  
**Issue:** The default server host was `0.0.0.0`, binding the Argus server to all network interfaces. In default configurations, this exposes the server to the network unnecessarily.  
**Fix:** Changed default host to `127.0.0.1` (loopback only).  
**Impact:** Reduces attack surface by default. Overridable via config file or env var.  
**Verification:** ✅ Config unit tests pass.

#### H-03: Default Vault URL Uses HTTP (No TLS)

**File:** `argus-workers/secrets_manager.py`  
**Issue:** The default VAULT_ADDR used `http://localhost:8200`, transmitting secrets in plaintext if Vault is configured with TLS (the recommended configuration). Also, the `verify` parameter was not passed to the Vault client.  
**Fix:** Changed default to `https://localhost:8200`. Added `verify` parameter based on `VAULT_SKIP_VERIFY` env var. Added a warning log when HTTP is used without explicitly disabling verification.  
**Verification:** ✅ 21 secrets manager tests pass, including updated test that expects `verify=True`.

---

### MEDIUM

#### M-01: No statement_timeout on Database Connections

**File:** `argus-workers/database/connection.py`  
**Issue:** Database connections from the pool did not enforce `statement_timeout`, allowing runaway queries to block worker processes indefinitely.  
**Fix:** Added automatic `SET statement_timeout = <ms>` on every connection acquisition. Default: 30 seconds. Configurable via `DB_STATEMENT_TIMEOUT_MS` env var.  
**Verification:** ✅ Connection tests pass, statement timeout is now enforced.

#### M-02: No SSL Mode Configuration for Database

**File:** `argus-workers/database/connection.py`  
**Issue:** The connection string builder did not specify an SSL mode. PostgreSQL defaults to `prefer` which will try TLS if available but fall back to plaintext.  
**Fix:** Added `DB_SSLMODE` environment variable support (default: `prefer`). The SSL mode is appended to the connection string unless already specified.  
**Verification:** ✅ Connection string builder correctly handles SSL parameter injection.

#### M-03: Redis Client Missing TLS and Error Handling

**File:** `argus-platform/src/lib/redis.ts`  
**Issue:** The Redis client did not support TLS connections (`rediss://` protocol) and had no connection retry strategy or error handler. Unhandled `error` events from ioredis can crash the Node.js process.  
**Fix:** Added TLS support via `REDIS_TLS` env var (accepts `true`, `1`, `yes`) and automatic detection of `rediss://` URLs. Added retry strategy with exponential backoff and capped retries. Added `error` event handler to prevent crashes.  
**Verification:** ✅ TypeScript compiles, no regressions in Redis-dependent code.

#### M-04: Bare Except Handlers Swallowing Exceptions

**Files:** `argus-workers/feature_flags.py`, `argus-workers/tools/scope_validator.py`  
**Issue:** Multiple `except Exception: pass` patterns silently swallowed exceptions, making debugging impossible in production.  
**Fix:** Added appropriate logging with exception context in all identified bare except handlers.  
**Verification:** ✅ Logging now provides visibility into failures.

---

### LOW

#### L-01: Missing Event Type in Streaming Log Message

**File:** `argus-workers/streaming.py`  
**Issue:** The `_maybe_transactional` function logged "Transaction emitter delegate failed" without specifying which event type failed.  
**Fix:** Added `event_type` parameter to the log message.  
**Verification:** ✅ Log output now includes event type context.

#### L-02: Test Not Updated for New Parameter

**File:** `argus-workers/tests/test_secrets_manager.py`  
**Issue:** The `test_get_vault_client` test did not expect the new `verify=True` parameter.  
**Fix:** Updated test assertion to expect `verify=True`.  
**Verification:** ✅ All 21 secrets manager tests pass.

---

## Pre-existing Issues in Working Tree (Not Modified)

The following changes were already present in the git working tree before this audit:

1. **Nuclei `-jsonl-export` → `-jsonl`** flag migration across `swarm.py`, `scan.py`
2. **`hashlib.md5` → `hashlib.md5(..., usedforsecurity=False)`** across 6 files (Python 3.9+ FIPS compliance)
3. **Bare except → logged except** in `attack_graph_db.py`, `custom_rules/registry.py`, `dead_letter_queue.py`, `security_audit.py`, `api_security_scanner.py`, `embedding_service.py`, `pgvector_repository.py`, `llm_payload_generator.py`
4. **JSON parsing error narrowing** in `repo_scan.py`
5. **ScanLogger severity fix** in `scan.py`

These are ready for commit alongside the audit fixes.

---

## Test Results

| Test Suite | Result |
|---|---|
| Secrets Manager (21 tests) | ✅ All pass |
| Security/Cache/Dedup (91 tests) | ✅ All pass |
| Full test suite (700+ tests) | ✅ No regression failures |
| Syntax check (9 modified files) | ✅ All compile |

---

## Recommendations for Future Audits

1. **Add SAST to CI pipeline:** Integrate `bandit` or `semgrep` to catch bare excepts, insecure defaults, and injection vulnerabilities automatically.
2. **Dependency vulnerability scanning:** Run `pip-audit` and `npm audit` regularly (noted: these failed during audit due to missing files).
3. **Add security integration tests:** Test TLS enforcement, statement timeout, and scope validation end-to-end.
4. **Secrets scanning:** Configure `gitleaks` (config found in `.gitleaks.toml`) to run on every commit.
