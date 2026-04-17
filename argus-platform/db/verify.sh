#!/bin/bash

# Argus Pentest Platform - Database Verification Script
# This script verifies that the database is set up correctly

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Default values
DB_NAME="${POSTGRES_DB:-argus_pentest}"
DB_USER="${POSTGRES_USER:-argus_user}"
DB_HOST="${POSTGRES_HOST:-localhost}"
DB_PORT="${POSTGRES_PORT:-5432}"

echo -e "${GREEN}=== Database Verification ===${NC}\n"

# Test connection
echo -e "${YELLOW}Testing connection...${NC}"
if psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -c "SELECT 1;" &> /dev/null; then
    echo -e "${GREEN}✓${NC} Connection successful"
else
    echo -e "${RED}✗${NC} Connection failed"
    exit 1
fi

# Check extensions
echo -e "\n${YELLOW}Checking extensions...${NC}"
EXTENSIONS=("uuid-ossp" "pgcrypto" "vector")
for ext in "${EXTENSIONS[@]}"; do
    if psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -tc "SELECT 1 FROM pg_extension WHERE extname = '$ext'" | grep -q 1; then
        echo -e "${GREEN}✓${NC} Extension '$ext' is installed"
    else
        echo -e "${RED}✗${NC} Extension '$ext' is NOT installed"
    fi
done

# Check tables
echo -e "\n${YELLOW}Checking tables...${NC}"
TABLES=(
    "organizations"
    "users"
    "engagements"
    "findings"
    "attack_paths"
    "loop_budgets"
    "engagement_states"
    "job_states"
    "decision_snapshots"
    "checkpoints"
    "execution_logs"
    "execution_spans"
    "tool_metrics"
    "execution_failures"
    "raw_outputs"
    "scope_violations"
    "rate_limit_events"
    "ai_explainability_traces"
)

MISSING_TABLES=()
for table in "${TABLES[@]}"; do
    if psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -tc "SELECT 1 FROM information_schema.tables WHERE table_name = '$table'" | grep -q 1; then
        echo -e "${GREEN}✓${NC} Table '$table' exists"
    else
        echo -e "${RED}✗${NC} Table '$table' is missing"
        MISSING_TABLES+=("$table")
    fi
done

# Check indexes
echo -e "\n${YELLOW}Checking key indexes...${NC}"
INDEXES=(
    "idx_engagements_org_id"
    "idx_findings_engagement_id"
    "idx_execution_logs_trace_id"
    "idx_tool_metrics_tool_name"
)

for index in "${INDEXES[@]}"; do
    if psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -tc "SELECT 1 FROM pg_indexes WHERE indexname = '$index'" | grep -q 1; then
        echo -e "${GREEN}✓${NC} Index '$index' exists"
    else
        echo -e "${RED}✗${NC} Index '$index' is missing"
    fi
done

# Check functions
echo -e "\n${YELLOW}Checking functions...${NC}"
if psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -tc "SELECT 1 FROM pg_proc WHERE proname = 'update_updated_at_column'" | grep -q 1; then
    echo -e "${GREEN}✓${NC} Function 'update_updated_at_column' exists"
else
    echo -e "${RED}✗${NC} Function 'update_updated_at_column' is missing"
fi

# Check triggers
echo -e "\n${YELLOW}Checking triggers...${NC}"
TRIGGERS=(
    "update_organizations_updated_at"
    "update_users_updated_at"
    "update_engagements_updated_at"
    "update_loop_budgets_updated_at"
)

for trigger in "${TRIGGERS[@]}"; do
    if psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -tc "SELECT 1 FROM pg_trigger WHERE tgname = '$trigger'" | grep -q 1; then
        echo -e "${GREEN}✓${NC} Trigger '$trigger' exists"
    else
        echo -e "${RED}✗${NC} Trigger '$trigger' is missing"
    fi
done

# Database statistics
echo -e "\n${YELLOW}Database statistics:${NC}"
echo -n "  Tables: "
psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -tc "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'public' AND table_type = 'BASE TABLE'"

echo -n "  Indexes: "
psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -tc "SELECT COUNT(*) FROM pg_indexes WHERE schemaname = 'public'"

echo -n "  Functions: "
psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -tc "SELECT COUNT(*) FROM pg_proc WHERE pronamespace = (SELECT oid FROM pg_namespace WHERE nspname = 'public')"

echo -n "  Database size: "
psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -tc "SELECT pg_size_pretty(pg_database_size('$DB_NAME'))"

# Summary
echo -e "\n${GREEN}=== Verification Complete ===${NC}\n"

if [ ${#MISSING_TABLES[@]} -eq 0 ]; then
    echo -e "${GREEN}✓${NC} All checks passed! Database is ready."
    exit 0
else
    echo -e "${RED}✗${NC} Some checks failed. Please run setup.sh to fix issues."
    exit 1
fi
