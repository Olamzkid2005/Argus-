# PostgreSQL Database Setup Guide

## Requirements

- PostgreSQL 15+ with pgvector extension
- Database name: `argus_pentest`
- User with appropriate permissions

## Installation Options

### Option 1: Homebrew (macOS)

```bash
# Install PostgreSQL 15
brew install postgresql@15

# Start PostgreSQL service
brew services start postgresql@15

# Add PostgreSQL to PATH
echo 'export PATH="/usr/local/opt/postgresql@15/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc
```

### Option 2: Docker (All Platforms)

```bash
# Run PostgreSQL with pgvector in Docker
docker run -d \
  --name argus-postgres \
  -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_DB=argus_pentest \
  -p 5432:5432 \
  pgvector/pgvector:pg15

# Verify it's running
docker ps | grep argus-postgres
```

### Option 3: Native Installation (Linux)

```bash
# Ubuntu/Debian
sudo apt-get update
sudo apt-get install -y postgresql-15 postgresql-contrib-15

# Start PostgreSQL
sudo systemctl start postgresql
sudo systemctl enable postgresql
```

## Database Setup

Once PostgreSQL is installed, run these commands:

```bash
# Create database and user
psql postgres -c "CREATE DATABASE argus_pentest;"
psql postgres -c "CREATE USER argus_user WITH PASSWORD 'your_secure_password';"
psql postgres -c "GRANT ALL PRIVILEGES ON DATABASE argus_pentest TO argus_user;"

# Install pgvector extension
psql argus_pentest -c "CREATE EXTENSION IF NOT EXISTS vector;"

# Verify installation
psql argus_pentest -c "SELECT version();"
psql argus_pentest -c "SELECT * FROM pg_extension WHERE extname = 'vector';"
```

## Connection Configuration

Create a `.env` file in the project root:

```env
DATABASE_URL=postgresql://argus_user:your_secure_password@localhost:5432/argus_pentest
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=argus_pentest
POSTGRES_USER=argus_user
POSTGRES_PASSWORD=your_secure_password
```

## Connection Pooling

For production, configure connection pooling in `postgresql.conf`:

```conf
max_connections = 100
shared_buffers = 256MB
effective_cache_size = 1GB
maintenance_work_mem = 64MB
checkpoint_completion_target = 0.9
wal_buffers = 16MB
default_statistics_target = 100
random_page_cost = 1.1
effective_io_concurrency = 200
work_mem = 2621kB
min_wal_size = 1GB
max_wal_size = 4GB
```

## Testing Connection

Test the database connection:

```bash
# Using psql
psql -h localhost -U argus_user -d argus_pentest -c "SELECT 1;"

# Using Node.js (from argus-platform directory)
node -e "const { Pool } = require('pg'); const pool = new Pool({ connectionString: process.env.DATABASE_URL }); pool.query('SELECT NOW()', (err, res) => { console.log(err ? err : res.rows[0]); pool.end(); });"
```

## Next Steps

After setting up PostgreSQL:

1. Run database migrations: `npm run migrate` (from argus-platform directory)
2. Seed initial data (if needed): `npm run seed`
3. Start the development server: `npm run dev`

## Troubleshooting

### Connection Refused

```bash
# Check if PostgreSQL is running
brew services list | grep postgresql  # macOS
sudo systemctl status postgresql      # Linux
docker ps | grep argus-postgres       # Docker

# Check PostgreSQL logs
tail -f /usr/local/var/log/postgresql@15.log  # macOS Homebrew
sudo tail -f /var/log/postgresql/postgresql-15-main.log  # Linux
docker logs argus-postgres  # Docker
```

### Permission Denied

```bash
# Grant permissions to user
psql postgres -c "ALTER USER argus_user WITH SUPERUSER;"
```

### pgvector Extension Not Found

```bash
# Install pgvector (Homebrew)
brew install pgvector

# Install pgvector (Linux)
sudo apt-get install postgresql-15-pgvector

# Install pgvector (Docker - already included in pgvector/pgvector image)
```

## Production Deployment

For production deployment (Railway, AWS RDS, etc.):

1. Use environment variables for all connection details
2. Enable SSL/TLS connections
3. Configure connection pooling (recommended: 10-20 connections per worker)
4. Set up automated backups
5. Monitor query performance with pg_stat_statements extension
6. Use read replicas for scaling read operations

### Railway Deployment

```bash
# Add PostgreSQL plugin in Railway dashboard
# Railway will automatically set DATABASE_URL environment variable

# Enable pgvector extension
railway run psql $DATABASE_URL -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

### AWS RDS Deployment

```bash
# Create RDS PostgreSQL 15 instance
# Enable pgvector in parameter group
# Update security group to allow connections from your application

# Connect and enable extension
psql -h your-rds-endpoint.amazonaws.com -U postgres -d argus_pentest -c "CREATE EXTENSION IF NOT EXISTS vector;"
```
