# Database Setup

This directory contains the database schema and setup scripts for the Argus Pentest Platform.

## Quick Start

### Option 1: Docker Compose (Recommended for Development)

The easiest way to get started is using Docker Compose:

```bash
# From the project root
docker-compose up -d postgres redis

# Wait for PostgreSQL to be ready
docker-compose ps

# Verify the database is set up
docker-compose exec postgres psql -U argus_user -d argus_pentest -c "\dt"
```

The schema will be automatically applied when the container starts.

**Connection Details:**

- Host: `localhost`
- Port: `5432`
- Database: `argus_pentest`
- User: `argus_user`
- Password: `changeme`
- Connection String: `postgresql://argus_user:changeme@localhost:5432/argus_pentest`

### Option 2: Local PostgreSQL Installation

If you prefer to install PostgreSQL locally:

```bash
# 1. Install PostgreSQL 15+ (see docs/database-setup.md for detailed instructions)
brew install postgresql@15  # macOS
# or
sudo apt-get install postgresql-15  # Linux

# 2. Start PostgreSQL
brew services start postgresql@15  # macOS
# or
sudo systemctl start postgresql  # Linux

# 3. Run the setup script
cd argus-platform/db
./setup.sh
```

The setup script will:

- Create the `argus_pentest` database
- Create the `argus_user` user
- Apply the schema (tables, indexes, functions)
- Verify pgvector extension is installed
- Test the connection

## Files

- **schema.sql** - Complete database schema with all tables, indexes, and functions
- **setup.sh** - Automated setup script for local installations
- **README.md** - This file

## Database Schema Overview

### Core Tables

- **organizations** - Multi-tenant organization data
- **users** - User accounts with authentication
- **engagements** - Penetration testing sessions
- **findings** - Discovered vulnerabilities
- **attack_paths** - Risk-scored attack chains
- **loop_budgets** - Budget tracking per engagement

### State Management

- **engagement_states** - State machine transition history
- **job_states** - Job queue tracking
- **decision_snapshots** - Immutable state snapshots for intelligence engine
- **checkpoints** - Partial results for recovery

### Logging & Monitoring

- **execution_logs** - Structured logs with trace IDs
- **execution_spans** - Timing data for observability
- **tool_metrics** - Tool performance statistics
- **execution_failures** - Failure tracking with retry counts
- **raw_outputs** - Unparseable tool outputs for manual review

### Security & Compliance

- **scope_violations** - Security audit trail
- **rate_limit_events** - Rate limiting activity
- **ai_explainability_traces** - AI decision traceability

## Environment Variables

Create a `.env` file in the `argus-platform` directory:

```env
# Database
DATABASE_URL=postgresql://argus_user:changeme@localhost:5432/argus_pentest
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=argus_pentest
POSTGRES_USER=argus_user
POSTGRES_PASSWORD=changeme

# Redis
REDIS_URL=redis://localhost:6379
REDIS_HOST=localhost
REDIS_PORT=6379

# Application
NODE_ENV=development
PORT=3000
```

## Migrations

For production deployments, consider using a migration tool like:

- **Prisma** - Type-safe ORM with migrations
- **Knex.js** - SQL query builder with migrations
- **node-pg-migrate** - PostgreSQL-specific migrations
- **Flyway** - Database migration tool

Example with Prisma:

```bash
# Install Prisma
npm install prisma @prisma/client

# Initialize Prisma
npx prisma init

# Generate Prisma schema from existing database
npx prisma db pull

# Generate Prisma Client
npx prisma generate
```

## Testing the Connection

### Using psql

```bash
psql postgresql://argus_user:changeme@localhost:5432/argus_pentest -c "SELECT version();"
```

### Using Node.js

```javascript
const { Pool } = require("pg");

const pool = new Pool({
  connectionString: process.env.DATABASE_URL,
});

pool.query("SELECT NOW()", (err, res) => {
  console.log(err ? err : res.rows[0]);
  pool.end();
});
```

## Troubleshooting

### Connection Refused

```bash
# Check if PostgreSQL is running
docker-compose ps  # Docker
brew services list | grep postgresql  # macOS
sudo systemctl status postgresql  # Linux

# Check PostgreSQL logs
docker-compose logs postgres  # Docker
tail -f /usr/local/var/log/postgresql@15.log  # macOS
sudo tail -f /var/log/postgresql/postgresql-15-main.log  # Linux
```

### Permission Denied

```bash
# Grant superuser privileges (development only)
psql postgres -c "ALTER USER argus_user WITH SUPERUSER;"
```

### pgvector Extension Not Found

```bash
# Docker - use pgvector/pgvector image (already included)
docker-compose up -d postgres

# Homebrew
brew install pgvector

# Linux
sudo apt-get install postgresql-15-pgvector

# Verify installation
psql argus_pentest -c "SELECT * FROM pg_extension WHERE extname = 'vector';"
```

### Reset Database

```bash
# Docker
docker-compose down -v  # Removes volumes
docker-compose up -d postgres

# Local
dropdb argus_pentest
./setup.sh
```

## Production Considerations

1. **Connection Pooling** - Use PgBouncer or configure max_connections appropriately
2. **SSL/TLS** - Enable SSL for all connections in production
3. **Backups** - Set up automated backups (pg_dump, WAL archiving, or cloud provider backups)
4. **Monitoring** - Enable pg_stat_statements extension for query performance monitoring
5. **Read Replicas** - Consider read replicas for scaling read operations
6. **Security** - Use strong passwords, restrict network access, enable audit logging

## Useful Commands

```bash
# List all tables
psql argus_pentest -c "\dt"

# Describe a table
psql argus_pentest -c "\d engagements"

# Count records in a table
psql argus_pentest -c "SELECT COUNT(*) FROM engagements;"

# Check database size
psql argus_pentest -c "SELECT pg_size_pretty(pg_database_size('argus_pentest'));"

# List all indexes
psql argus_pentest -c "\di"

# Show active connections
psql argus_pentest -c "SELECT * FROM pg_stat_activity;"
```

## Next Steps

After setting up the database:

1. Install dependencies: `cd argus-platform && npm install`
2. Configure environment variables in `.env`
3. Start the development server: `npm run dev`
4. Access the application at `http://localhost:3000`

For more detailed information, see:

- [Database Setup Guide](../../docs/database-setup.md)
- [Design Document](.kiro/specs/argus-pentest-platform/design.md)
- [Requirements Document](.kiro/specs/argus-pentest-platform/requirements.md)
