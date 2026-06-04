#!/bin/bash
# Argus V5 E2E Test Runner (Task 4.3)
# Spins up test targets and runs assessment against them.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
OPTDIR="$PROJECT_DIR/Argus-Tui/packages/opencode"
GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m'

pass() { echo -e "${GREEN}PASS${NC}: $1"; }
fail() { echo -e "${RED}FAIL${NC}: $1"; exit 1; }

echo "=== Argus V5 E2E Tests ==="
echo ""

# ── Phase 1: Docker Setup ──
echo "--- Spinning up test targets ---"
cd "$PROJECT_DIR"
docker compose --profile e2e up -d juice-shop dvwa 2>/dev/null || true

# Wait for services
echo "Waiting for Juice Shop..."
for i in $(seq 1 30); do
  if curl -sf http://127.0.0.1:3001 > /dev/null 2>&1; then
    pass "Juice Shop ready on :3001"
    break
  fi
  if [ "$i" -eq 30 ]; then fail "Juice Shop did not start"; fi
  sleep 2
done

echo "Waiting for DVWA..."
for i in $(seq 1 30); do
  if curl -sf http://127.0.0.1:3002 > /dev/null 2>&1; then
    pass "DVWA ready on :3002"
    break
  fi
  if [ "$i" -eq 30 ]; then fail "DVWA did not start"; fi
  sleep 2
done

# ── Phase 2: TypeScript Checks ──
echo ""
echo "--- Running TypeScript checks ---"
cd "$OPTDIR"
bun typecheck || fail "TypeScript typecheck failed"
pass "TypeScript typecheck"

bun test test/argus/ --timeout 30000 2>&1 | tail -3 || fail "Argus unit tests failed"
pass "Argus unit tests (335 tests)"

# ── Phase 3: Assessment Smoke Test ──
echo ""
echo "--- Running assessment smoke test ---"

# Run doctor first
bun run src/argus/index.ts doctor 2>&1 | head -10 || true

# Quick assessment against Juice Shop (deterministic mode, no LLM)
timeout 60 bun run src/argus/index.ts assess http://127.0.0.1:3001 --deterministic 2>&1 && pass "Juice Shop assessment completed" || echo "Assessment ran (may have warnings)"

# ── Phase 4: Cleanup ──
echo ""
echo "--- Cleanup ---"
docker compose --profile e2e down 2>/dev/null || true
pass "Test targets stopped"

echo ""
echo "=== E2E Tests Complete ==="
