#!/bin/bash

# Argus Pentest Platform - Database Setup Script
# This script sets up the PostgreSQL database with all required tables and extensions

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Default values
DB_NAME="${POSTGRES_DB:-argus_pentest}"
DB_USER="${POSTGRES_USER:-argus_user}"
DB_PASSWORD="${POSTGRES_PASSWORD:-changeme}"
DB_HOST="${POSTGRES_HOST:-localhost}"
DB_PORT="${POSTGRES_PORT:-5432}"

echo -e "${GREEN}=== Argus Pentest Platform - Database Setup ===${NC}\n"

# Check if PostgreSQL is installed
if ! command -v psql &> /dev/null; then
    echo -e "${RED}Error: psql command not found${NC}"
    echo "Please install PostgreSQL 15+ first. See docs/database-setup.md for instructions."
    exit 1
fi

# Check if PostgreSQL is running
if ! pg_isready -h "$DB_HOST" -p "$DB_PORT" &> /dev/null; then
    echo -e "${RED}Error: PostgreSQL is not running on $DB_HOST:$DB_PORT${NC}"
    echo "Please start PostgreSQL first:"
    echo "  macOS (Homebrew): brew services start postgresql@15"
    echo "  Linux: sudo systemctl start postgresql"
    echo "  Docker: docker start argus-postgres"
    exit 1
fi

echo -e "${GREEN}✓${NC} PostgreSQL is running"

# Create database if it doesn't exist
echo -e "\n${YELLOW}Creating database '$DB_NAME'...${NC}"
psql -h "$DB_HOST" -p "$DB_PORT" -U postgres -tc "SELECT 1 FROM pg_database WHERE datname = '$DB_NAME'" | grep -q 1 || \
    psql -h "$DB_HOST" -p "$DB_PORT" -U postgres -c "CREATE DATABASE $DB_NAME;"
echo -e "${GREEN}✓${NC} Database '$DB_NAME' ready"

# Create user if it doesn't exist
echo -e "\n${YELLOW}Creating user '$DB_USER'...${NC}"
psql -h "$DB_HOST" -p "$DB_PORT" -U postgres -tc "SELECT 1 FROM pg_roles WHERE rolname = '$DB_USER'" | grep -q 1 || \
    psql -h "$DB_HOST" -p "$DB_PORT" -U postgres -c "CREATE USER $DB_USER WITH PASSWORD '$DB_PASSWORD';"
echo -e "${GREEN}✓${NC} User '$DB_USER' ready"

# Grant privileges
echo -e "\n${YELLOW}Granting privileges...${NC}"
psql -h "$DB_HOST" -p "$DB_PORT" -U postgres -c "GRANT ALL PRIVILEGES ON DATABASE $DB_NAME TO $DB_USER;"
psql -h "$DB_HOST" -p "$DB_PORT" -U postgres -d "$DB_NAME" -c "GRANT ALL ON SCHEMA public TO $DB_USER;"
echo -e "${GREEN}✓${NC} Privileges granted"

# Run schema SQL
echo -e "\n${YELLOW}Creating tables and indexes...${NC}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
psql -h "$DB_HOST" -p "$DB_PORT" -U postgres -d "$DB_NAME" -f "$SCRIPT_DIR/schema.sql"
echo -e "${GREEN}✓${NC} Schema created successfully"

# Verify pgvector extension
echo -e "\n${YELLOW}Verifying pgvector extension...${NC}"
if psql -h "$DB_HOST" -p "$DB_PORT" -U postgres -d "$DB_NAME" -tc "SELECT 1 FROM pg_extension WHERE extname = 'vector'" | grep -q 1; then
    echo -e "${GREEN}✓${NC} pgvector extension is installed"
else
    echo -e "${RED}✗${NC} pgvector extension is NOT installed"
    echo "Please install pgvector:"
    echo "  macOS (Homebrew): brew install pgvector"
    echo "  Linux: sudo apt-get install postgresql-15-pgvector"
    echo "  Docker: Use pgvector/pgvector:pg15 image"
fi

# Test connection
echo -e "\n${YELLOW}Testing database connection...${NC}"
if psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -c "SELECT 1;" &> /dev/null; then
    echo -e "${GREEN}✓${NC} Connection successful"
else
    echo -e "${RED}✗${NC} Connection failed"
    echo "Please check your credentials and try again"
    exit 1
fi

# Display connection string
echo -e "\n${GREEN}=== Setup Complete ===${NC}\n"
echo "Database URL:"
echo "  postgresql://$DB_USER:$DB_PASSWORD@$DB_HOST:$DB_PORT/$DB_NAME"
echo ""
echo "Add this to your .env file:"
echo "  DATABASE_URL=postgresql://$DB_USER:$DB_PASSWORD@$DB_HOST:$DB_PORT/$DB_NAME"
echo ""
echo -e "${GREEN}Next steps:${NC}"
echo "  1. Update your .env file with the DATABASE_URL"
echo "  2. Run 'npm install' to install dependencies"
echo "  3. Run 'npm run dev' to start the development server"
