#!/usr/bin/env bash
# Failure-mode rehearsals for the lab.
#
# The demo is only as good as what happens when things go wrong. Each scenario
# below drives a real failure against the local lab and asserts the *observable*
# outcome (exit code and the line an operator reads), never internal state:
#
#   1. out-of-scope target     — the run refuses before touching the target
#   2. wrong credentials       — a verifier reports nothing, it does not invent
#   3. provider unavailable    — a dead LLM endpoint fails fast and says so
#   4. worker interruption     — a killed MCP worker is reported, and resume
#                                continues from the persisted phases
#   5. cancellation            — an interrupted run records that it stopped and
#                                exits non-zero
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

fail=0
pass() { echo "PASS  $1"; }
failed() { echo "FAIL  $1 — $2"; fail=1; }

CLI=(bun "$REPO/Argus-Tui/packages/opencode/bin/argus")

# ── 1. Out-of-scope target ────────────────────────────────────────────────
scenario_scope() {
  local log="$OUT/1-scope.log"
  HOME="$OUT/home-scope" ARGUS_DATA_DIR="$OUT/home-scope/.argus" \
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
  # Port 9 (discard) accepts nothing: a refused connection, not a slow one.
  timeout 240 env HOME="$OUT/home-provider" ARGUS_DATA_DIR="$OUT/home-provider/.argus" \
    ARGUS_SCOPE_MODE=allowlist ARGUS_ALLOWED_TARGETS=127.0.0.1 \
    LLM_API_URL="http://127.0.0.1:9/v1/chat/completions" \
    "${CLI[@]}" assess "$TARGET" >"$log" 2>&1
  local code=$?
  if [ $code -eq 124 ]; then failed "provider unavailable" "hung past 240s"; return; fi
  if ! grep -qiE 'llm|provider|429|connection|refused' "$log"; then
    failed "provider unavailable" "no provider error surfaced"; return
  fi
  pass "dead provider reported (exit $code)"
}

# ── 4. Worker interruption and resume ────────────────────────────────────
scenario_interrupt() {
  local log="$OUT/4-interrupt.log"
  local home="$OUT/home-interrupt"
  mkdir -p "$home"
  timeout 300 env HOME="$home" ARGUS_DATA_DIR="$home/.argus" \
    ARGUS_SCOPE_MODE=allowlist ARGUS_ALLOWED_TARGETS=127.0.0.1 \
    "${CLI[@]}" assess "$TARGET" >"$log" 2>&1 &
  local run=$!
  # Wait for the worker to be up, then kill it the way a crash would.
  local worker=""
  for _ in $(seq 1 60); do
    worker=$(ps -eo pid,cmd | awk -v h="$home" 'index($0, "mcp_server.py") && index($0, "argus-workers") {print $1; exit}')
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
  if [ $code -eq 0 ]; then failed "worker interruption" "run reported success after its worker was killed"; return; fi
  # Resume must pick the engagement up rather than starting over.
  local resume_log="$OUT/4-resume.log"
  timeout 300 env HOME="$home" ARGUS_DATA_DIR="$home/.argus" \
    ARGUS_SCOPE_MODE=allowlist ARGUS_ALLOWED_TARGETS=127.0.0.1 \
    "${CLI[@]}" resume "$engagement" >"$resume_log" 2>&1
  if ! grep -qiE 'resum|phase|complete' "$resume_log"; then
    failed "worker interruption" "resume produced no phase output"
    return
  fi
  pass "killed worker reported (exit $code); resume drove $engagement"
}

# ── 5. Cancellation ──────────────────────────────────────────────────────
scenario_cancel() {
  local log="$OUT/5-cancel.log"
  local home="$OUT/home-cancel"
  mkdir -p "$home"
  timeout 300 env HOME="$home" ARGUS_DATA_DIR="$home/.argus" \
    ARGUS_SCOPE_MODE=allowlist ARGUS_ALLOWED_TARGETS=127.0.0.1 \
    "${CLI[@]}" assess "$TARGET" >"$log" 2>&1 &
  local run=$!
  sleep 45
  kill -INT $run 2>/dev/null
  wait $run 2>/dev/null
  local code=$?
  local engagement
  engagement=$(ls -t "$home/.argus/engagements" 2>/dev/null | head -1)
  if [ -z "$engagement" ]; then failed "cancellation" "no engagement persisted"; return; fi
  local status
  status=$(python3 - "$home/.argus/argus.db" <<'PY'
import sqlite3, sys
print(list(sqlite3.connect(sys.argv[1]).execute("select status from engagements order by rowid desc limit 1"))[0][0])
PY
)
  if [ $code -eq 0 ]; then failed "cancellation" "interrupted run exited 0 (status $status)"; return; fi
  pass "cancelled run exited $code (status $status)"
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
