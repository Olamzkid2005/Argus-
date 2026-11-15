#!/usr/bin/env bash
# Failure-mode rehearsals for the lab.
#
# The demo is only as good as what happens when things go wrong. Each scenario
# below drives a real failure against the local lab and asserts the *observable*
# outcome (exit code, engagement status and the line an operator reads), never
# internal state:
#
#   1. out-of-scope target     — the run refuses before touching the target
#   2. wrong credentials       — a verifier reports nothing, it does not invent
#   3. provider unavailable    — a dead LLM endpoint degrades, it does not hang
#   4. worker interruption     — a killed MCP worker is survivable or reported,
#                                and `resume` continues from the persisted phases
#   5. cancellation            — Ctrl-C records INTERRUPTED and exits non-zero
#
# Usage: bash scripts/livefire/rehearse-failures.sh [scenario ...]
# Each scenario prints PASS/FAIL and the script exits non-zero if any failed.
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO"
OUT="${REHEARSAL_OUT:-$REPO/livefire-runs/rehearsals-$(date +%Y%m%d-%H%M%S)}"
mkdir -p "$OUT"

TARGET="${REHEARSAL_TARGET:-http://127.0.0.1:18080}"
LLM_URL="${REHEARSAL_LLM_URL:-http://127.0.0.1:18081/v1/chat/completions}"
export PATH="$REPO/.livefire/bin:$REPO/argus-workers/venv/bin:$PATH"
export DATABASE_URL="${DATABASE_URL:-postgresql://argus_user@127.0.0.1:5432/argus_pentest}"
export REDIS_URL="${REDIS_URL:-redis://:argus-livefire-redis@127.0.0.1:6379/0}"
export CELERY_BROKER_URL="$REDIS_URL"
export LLM_PROVIDER=generic
export LLM_API_URL="$LLM_URL"
export LLM_API_KEY=livefire-stub
export LLM_MODEL=gpt-4o-mini
export ARGUS_ALLOW_INTERNAL_TARGETS=1
export ARGUS_AUTO_APPROVE=1
export ARGUS_ALLOW_AMBIENT_LLM_ENV=0
export ARGUS_LLM_TRANSPORT=direct

# The MCP worker sets these for tool subprocesses; a direct tool invocation in a
# rehearsal needs the same environment or Chromium cannot start.
if [ -d "$REPO/.livefire/tools/browser-libs/usr/lib/x86_64-linux-gnu" ]; then
  export LD_LIBRARY_PATH="$REPO/.livefire/tools/browser-libs/usr/lib/x86_64-linux-gnu${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
  export FONTCONFIG_FILE="$REPO/.livefire/tools/browser-libs/etc/fonts/fonts.conf"
fi
if [ -d "$REPO/.livefire/tools/ms-playwright" ]; then
  export PLAYWRIGHT_BROWSERS_PATH="$REPO/.livefire/tools/ms-playwright"
fi

fail=0
pass() { echo "PASS  $1"; }
failed() { echo "FAIL  $1 — $2"; fail=1; }

CLI=(bun "$REPO/Argus-Tui/packages/opencode/bin/argus")

engagement_status() {
  python3 - "$1" <<'PY'
import sqlite3, sys
print(list(sqlite3.connect(sys.argv[1]).execute(
    "select status from engagements order by rowid desc limit 1"))[0][0])
PY
}

run_assess() { # home log [extra env...]
  local home="$1" log="$2"
  shift 2
  env HOME="$home" ARGUS_DATA_DIR="$home/.argus" \
    ARGUS_SCOPE_MODE=allowlist ARGUS_ALLOWED_TARGETS=127.0.0.1 "$@" \
    "${CLI[@]}" assess "$TARGET" >"$log" 2>&1
}

# ── 1. Out-of-scope target ────────────────────────────────────────────────
scenario_scope() {
  local log="$OUT/1-scope.log"
  env HOME="$OUT/home-scope" ARGUS_DATA_DIR="$OUT/home-scope/.argus" \
    ARGUS_SCOPE_MODE=allowlist ARGUS_ALLOWED_TARGETS=lab.example \
    "${CLI[@]}" assess "$TARGET" >"$log" 2>&1
  local code=$?
  if [ $code -eq 0 ]; then failed "out-of-scope target" "exited 0"; return; fi
  if ! grep -qi 'scope' "$log"; then failed "out-of-scope target" "no scope refusal in the log"; return; fi
  pass "out-of-scope target refused (exit $code)"
}

# ── 2. Wrong credentials ──────────────────────────────────────────────────
scenario_credentials() {
  local log="$OUT/2-credentials.log"
  local creds="$OUT/creds-wrong.json"
  cat >"$creds" <<'JSON'
{"attacker": {"username": "user2", "password": "definitely-not-the-password"},
 "victim": {"username": "user1", "password": "welcome1"},
 "resource_pattern": "/api/data/10"}
JSON
  ( cd argus-workers && ./venv/bin/python tools/scripts/playwright_bola.py \
      --target "$TARGET" --creds-file "$creds" ) >"$log" 2>&1
  local code=$?
  if [ $code -ne 0 ]; then failed "wrong credentials" "verifier crashed (exit $code)"; return; fi
  if grep -q '"severity": 4' "$log"; then
    failed "wrong credentials" "a confirmed finding was reported for a rejected login"
    return
  fi
  pass "wrong credentials produce no finding and no crash"
}

# ── 3. LLM provider unavailable ──────────────────────────────────────────
scenario_provider() {
  local log="$OUT/3-provider.log"
  # Port 9 (discard) refuses connections. Argus is expected to degrade to
  # deterministic planning rather than hang: either a completion line or a
  # provider error is acceptable, silence until the deadline is not.
  timeout 600 env HOME="$OUT/home-provider" ARGUS_DATA_DIR="$OUT/home-provider/.argus" \
    ARGUS_SCOPE_MODE=allowlist ARGUS_ALLOWED_TARGETS=127.0.0.1 \
    LLM_API_URL="http://127.0.0.1:9/v1/chat/completions" \
    "${CLI[@]}" assess "$TARGET" >"$log" 2>&1
  local code=$?
  if [ $code -eq 124 ]; then failed "provider unavailable" "hung past 600s"; return; fi
  if grep -qE 'Assessment (complete|finished|failed)' "$log"; then
    pass "dead provider degraded to deterministic planning (exit $code)"
    return
  fi
  if grep -qiE 'llm|provider|connection refused' "$log"; then
    pass "dead provider reported (exit $code)"
    return
  fi
  failed "provider unavailable" "neither a completion line nor a provider error"
}

# ── 4. Worker interruption and resume ────────────────────────────────────
# The MCP bridge restarts a worker it loses, so losing one is survivable by
# design. What must never happen is a silently hung run: either the run
# reconnects and reports an outcome, or it ends non-zero saying what broke.
scenario_interrupt() {
  local log="$OUT/4-interrupt.log"
  local home="$OUT/home-interrupt"
  mkdir -p "$home"
  run_assess "$home" "$log" &
  local run=$!
  local worker=""
  for _ in $(seq 1 90); do
    local p pid
    for p in /proc/[0-9]*; do
      pid=${p#/proc/}
      tr '\0' '\n' <"$p/environ" 2>/dev/null | grep -qx "HOME=$home" || continue
      tr '\0' ' ' <"$p/cmdline" 2>/dev/null | grep -q 'mcp_server.py' || continue
      worker=$pid
      break
    done
    [ -n "$worker" ] && break
    sleep 1
  done
  if [ -z "$worker" ]; then
    failed "worker interruption" "no MCP worker started"
    kill -TERM $run 2>/dev/null
    return
  fi
  kill -KILL "$worker" 2>/dev/null
  wait $run 2>/dev/null
  local code=$?
  local engagement
  engagement=$(ls -t "$home/.argus/engagements" 2>/dev/null | head -1)
  if [ -z "$engagement" ]; then failed "worker interruption" "no engagement persisted"; return; fi
  if [ $code -eq 124 ]; then failed "worker interruption" "hung after its worker was killed"; return; fi
  if ! grep -qE 'Assessment (complete|finished|failed)|worker|MCP' "$log"; then
    failed "worker interruption" "the run said nothing about the lost worker"
    return
  fi
  # Resume must pick the engagement up rather than starting over.
  local resume_log="$OUT/4-resume.log"
  timeout 600 env HOME="$home" ARGUS_DATA_DIR="$home/.argus" \
    ARGUS_SCOPE_MODE=allowlist ARGUS_ALLOWED_TARGETS=127.0.0.1 \
    "${CLI[@]}" resume "$engagement" >"$resume_log" 2>&1
  if ! grep -qiE 'resum|phase|complete|nothing' "$resume_log"; then
    failed "worker interruption" "resume produced no phase output"
    return
  fi
  pass "worker killed mid-run: run said so (exit $code); resume handled $engagement"
}

# ── 5. Cancellation ──────────────────────────────────────────────────────
scenario_cancel() {
  local log="$OUT/5-cancel.log"
  local home="$OUT/home-cancel"
  mkdir -p "$home"
  # SIGINT must come from `timeout`, not from the script: bash starts a
  # background job with SIGINT ignored, so a run launched as `cmd &` never sees
  # Ctrl-C and the rehearsal "passes" against a process that was never signalled
  # (measured: the whole assessment ran to completion). `timeout` runs the CLI in
  # the foreground and delivers the signal itself; --preserve-status keeps the
  # CLI's own exit code instead of 124.
  timeout --preserve-status -s INT -k 120 45 env HOME="$home" ARGUS_DATA_DIR="$home/.argus" \
    ARGUS_SCOPE_MODE=allowlist ARGUS_ALLOWED_TARGETS=127.0.0.1 \
    "${CLI[@]}" assess "$TARGET" >"$log" 2>&1
  local code=$?
  local engagement
  engagement=$(ls -t "$home/.argus/engagements" 2>/dev/null | head -1)
  if [ -z "$engagement" ]; then failed "cancellation" "no engagement persisted"; return; fi
  local status
  status=$(engagement_status "$home/.argus/argus.db")
  if [ $code -eq 124 ]; then failed "cancellation" "ignored Ctrl-C for 120s"; return; fi
  if [ "$status" != "INTERRUPTED" ]; then failed "cancellation" "status is $status, not INTERRUPTED (exit $code)"; return; fi
  if [ $code -eq 0 ]; then failed "cancellation" "interrupted run exited 0"; return; fi
  pass "cancelled run recorded INTERRUPTED and exited $code"
}

requested=("$@")
[ ${#requested[@]} -eq 0 ] && requested=(scope credentials provider interrupt cancel)

for scenario in "${requested[@]}"; do
  "scenario_$scenario"
done

echo
if [ $fail -ne 0 ]; then
  echo "rehearsals: at least one scenario failed (logs in $OUT)"
  exit 1
fi
echo "rehearsals: all scenarios behaved as specified (logs in $OUT)"
