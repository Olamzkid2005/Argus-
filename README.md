# Argus Pentest Platform

AI-powered penetration testing platform with autonomous reconnaissance, vulnerability scanning, and intelligent analysis.

## Architecture

- **Frontend/API:** Next.js 14 (TypeScript) with App Router
- **Workers:** Python 3.11+ with Celery
- **Database:** PostgreSQL 15 with pgvector
- **Queue:** Redis
- **AI:** OpenAI GPT-4 / Anthropic Claude

## Project Structure

```
Argus-/
├── argus-platform/          # Next.js frontend and API
│   ├── src/app/            # App Router pages and API routes
│   ├── db/                 # Database schema and scripts
│   └── package.json
│
├── argus-workers/          # Python worker system
│   ├── celery_app.py      # Celery configuration
│   ├── tasks/             # Celery task definitions
│   ├── tools/             # Security tool wrappers
│   ├── parsers/           # Tool output parsers
│   ├── models/            # Pydantic data models
│   └── database/          # Database access layer
│
├── docs/                   # Documentation
│   ├── setup-progress.md  # Setup progress tracker
│   └── database-setup.md  # Database setup guide
│
└── FINAL-ARCHITECTURE.md   # Complete architecture specification
```

## Quick Start

### Prerequisites

- macOS 13+ (or Linux)
- PostgreSQL 15+
- Redis
- Python 3.11+
- Node.js 18+

### 1. Install Dependencies

**Install PostgreSQL and Redis (macOS with MacPorts):**
```bash
sudo port install postgresql15 postgresql15-server redis
```

**Initialize and start PostgreSQL:**
```bash
sudo mkdir -p /opt/local/var/db/postgresql15/defaultdb
sudo chown postgres:postgres /opt/local/var/db/postgresql15/defaultdb
sudo -u postgres /bin/sh -c 'cd /opt/local/var/db/postgresql15 && /opt/local/lib/postgresql15/bin/initdb -D /opt/local/var/db/postgresql15/defaultdb'
sudo port load postgresql15-server
```

**Start Redis:**
```bash
sudo port load redis
```

### 2. Database Setup

```bash
cd argus-platform/db
./setup.sh    # Creates database and applies schema
./verify.sh   # Verifies database setup
cd ../..
```

### 3. Install Application Dependencies

**Frontend dependencies:**
```bash
cd argus-platform
npm install
cd ..
```

**Worker dependencies:**
```bash
cd argus-workers
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
deactivate
cd ..
```

### 4. Configure Environment Variables

The `.env.local` file in `argus-platform/` is already configured with development defaults. For production or custom setups, update:

- `DATABASE_URL` - PostgreSQL connection string
- `REDIS_URL` - Redis connection string
- `NEXTAUTH_SECRET` - Secret for NextAuth.js (generate with `openssl rand -base64 32`)
- `OPENAI_API_KEY` - OpenAI API key (optional, for AI features)
- `ANTHROPIC_API_KEY` - Anthropic API key (optional, for AI features)

### 5. Run the Application

**Option A: Start Everything at Once (Recommended)**

```bash
./start-argus.sh
```

This starts both the Next.js dashboard and Celery workers. Access the dashboard at [http://localhost:3000](http://localhost:3000)

**To stop all services:**
```bash
./stop-argus.sh
```

**View logs:**
```bash
# Next.js logs
tail -f logs/nextjs.log

# Celery worker logs
tail -f logs/celery.log
```

**Option B: Start Services Manually**

If you prefer to run services in separate terminals:

**Terminal 1 - Next.js Dashboard:**
```bash
cd argus-platform
npm run dev
```

**Terminal 2 - Celery Workers:**
```bash
cd argus-workers
source venv/bin/activate
celery -A celery_app worker --loglevel=info --concurrency=4
```

**Terminal 3 - Flower (Optional - Worker Monitoring):**
```bash
cd argus-workers
source venv/bin/activate
celery -A celery_app flower
# Open http://localhost:5555
```

## How It Works

Argus is an AI-powered penetration testing platform that automates security assessments through a multi-stage pipeline:

### Architecture Overview

```
┌─────────────────┐
│   Next.js App   │  ← User Interface & API
│  (Port 3000)    │
└────────┬────────┘
         │
         ├─────────────┐
         │             │
    ┌────▼────┐   ┌───▼────────┐
    │PostgreSQL│   │   Redis    │
    │Database │   │   Queue    │
    └────┬────┘   └───┬────────┘
         │            │
         │       ┌────▼────────┐
         │       │   Celery    │
         │       │   Workers   │
         │       └─────────────┘
         │            │
         └────────────┴──────────► Security Tools
                                   (Nuclei, httpx, etc.)
```

### Workflow

1. **Engagement Creation** (Web UI)
   - User creates a penetration test engagement
   - Defines target scope (domains, IPs, URLs)
   - Uploads authorization proof
   - Sets engagement parameters

2. **Task Orchestration** (Celery Workers)
   - Engagement triggers background tasks
   - Tasks are queued in Redis
   - Workers pick up tasks and execute them

3. **Reconnaissance Phase**
   - Subdomain discovery (subfinder)
   - HTTP probing (httpx)
   - Technology detection
   - Asset inventory building

4. **Scanning Phase**
   - Vulnerability scanning (Nuclei)
   - Web fuzzing (ffuf)
   - SQL injection testing (sqlmap)
   - Custom security checks

5. **Analysis Phase** (AI-Powered)
   - Finding deduplication
   - Confidence scoring
   - False positive detection
   - Attack path construction
   - Risk prioritization

6. **Reporting**
   - Real-time finding updates
   - Attack graph visualization
   - Executive summaries
   - Technical details with remediation

### Key Components

**Frontend (Next.js)**
- Dashboard for engagement management
- Real-time finding updates
- Attack path visualization
- User authentication and authorization

**API Layer (Next.js API Routes)**
- RESTful endpoints for CRUD operations
- WebSocket support for real-time updates
- Rate limiting and security controls
- Session management

**Worker System (Python + Celery)**
- Distributed task execution
- Tool orchestration and execution
- Result parsing and normalization
- Database persistence

**Database (PostgreSQL)**
- Engagement and finding storage
- User and organization management
- Audit logging
- Vector embeddings (pgvector) for AI features

**Queue (Redis)**
- Task queue for Celery
- Caching layer
- Rate limiting storage
- Real-time event pub/sub

## Features

### Core Capabilities
- ✅ Multi-tenant organization management
- ✅ Autonomous reconnaissance (subdomain discovery, probing)
- ✅ Vulnerability scanning (Nuclei, fuzzing, SQL injection)
- ✅ AI-powered finding analysis and prioritization
- ✅ Attack path construction and risk scoring
- ✅ Intelligent decision-making with loop budgets
- ✅ Comprehensive logging and observability

### Security Features
- Scope validation and enforcement
- Rate limiting per target domain
- Authorization proof requirements
- Audit logging for all operations
- Secure credential management

### AI Intelligence
- Finding confidence scoring
- False positive likelihood estimation
- Tool agreement analysis
- Attack path risk assessment
- Autonomous decision-making with budget constraints

## Development Status

**Current Phase:** Week 1 - Core Pipeline

**Completed:**
- ✅ Next.js project initialization
- ✅ PostgreSQL database setup (18 tables)
- ✅ Redis configuration
- ✅ Python worker project structure
- ✅ Celery configuration with task queues

**In Progress:**
- 🔄 Authentication implementation (NextAuth.js)
- 🔄 Engagement management API
- 🔄 Tool execution pipeline

**Upcoming:**
- ⏳ Recon worker implementation
- ⏳ Scan worker implementation
- ⏳ Intelligence engine
- ⏳ Report generation

See [docs/setup-progress.md](docs/setup-progress.md) for detailed progress.

## API Endpoints

### Authentication
- `POST /api/auth/signup` - Create new user account
- `POST /api/auth/signin` - User login (NextAuth.js)
- `POST /api/auth/signout` - User logout
- `GET /api/auth/session` - Get current session

### Engagements
- `POST /api/engagement/create` - Create new penetration test engagement
- `GET /api/engagement/[id]` - Get engagement details
- `GET /api/engagement/[id]/findings` - Get findings for engagement
- `GET /api/engagement/[id]/timeline` - Get engagement timeline
- `GET /api/engagement/[id]/explainability` - Get AI analysis explanations
- `POST /api/engagement/[id]/approve` - Approve engagement to start testing

### Real-Time Updates
- `GET /api/ws/engagement/[id]` - WebSocket connection for live updates
- `GET /api/ws/engagement/[id]/poll` - Long-polling fallback

### Tools & Performance
- `GET /api/tools/performance` - Get tool performance metrics

## Technology Stack

### Frontend
- Next.js 14 (App Router)
- TypeScript
- Tailwind CSS
- React Query (for data fetching)

### Backend
- Next.js API Routes
- PostgreSQL 15 (with pgvector for embeddings)
- Redis (job queue and caching)

### Workers
- Python 3.11+
- Celery (distributed task queue)
- SQLAlchemy (database ORM)
- Pydantic (data validation)

### Security Tools
- Nuclei (vulnerability scanner)
- httpx (HTTP probing)
- subfinder (subdomain discovery)
- ffuf (web fuzzer)
- sqlmap (SQL injection testing)

### AI/LLM
- OpenAI GPT-4
- Anthropic Claude
- Custom intelligence engine

## Configuration

### Environment Variables

**Frontend (`argus-platform/.env.local`):**
```bash
# Database
DATABASE_URL=postgresql://argus_user:password@localhost:5432/argus_pentest

# Redis
REDIS_URL=redis://localhost:6379
REDIS_HOST=localhost
REDIS_PORT=6379

# NextAuth
NEXTAUTH_URL=http://localhost:3000
NEXTAUTH_SECRET=your_nextauth_secret_here_change_in_production

# OAuth Providers (Optional)
GOOGLE_CLIENT_ID=your_google_client_id
GOOGLE_CLIENT_SECRET=your_google_client_secret
GITHUB_CLIENT_ID=your_github_client_id
GITHUB_CLIENT_SECRET=your_github_client_secret

# AI APIs (Optional)
OPENAI_API_KEY=your_openai_api_key
ANTHROPIC_API_KEY=your_anthropic_api_key
```

**Workers (`argus-workers/.env`):**
```bash
# Database
DATABASE_URL=postgresql://argus_user:password@localhost:5432/argus_pentest

# Celery
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/0

# AI APIs
OPENAI_API_KEY=your_openai_key
ANTHROPIC_API_KEY=your_anthropic_key
```

### Security Configuration

**Generate secure secrets:**
```bash
# NextAuth secret
openssl rand -base64 32

# JWT secret
openssl rand -hex 32
```

**OAuth Setup:**
- Google: https://console.cloud.google.com/apis/credentials
- GitHub: https://github.com/settings/developers

### Tool Configuration

Security tools are configured in `argus-workers/tools/`. Each tool wrapper includes:
- Installation verification
- Command-line argument construction
- Output parsing
- Error handling

**Supported Tools:**
- Nuclei - Vulnerability scanner
- httpx - HTTP probing
- subfinder - Subdomain discovery
- ffuf - Web fuzzer
- sqlmap - SQL injection testing

## Testing

### Frontend Tests
```bash
cd argus-platform
npm test                    # Run all tests
npm run test:watch         # Watch mode
npm run test:coverage      # Coverage report
```

### Backend/Worker Tests
```bash
cd argus-workers
source venv/bin/activate
pytest                      # Run all tests
pytest tests/test_file.py  # Run specific test file
pytest -v                   # Verbose output
pytest --cov               # Coverage report
```

### API Tests
```bash
cd argus-platform
npm run test:api           # Run API integration tests
```

### End-to-End Tests
```bash
# Start the application first
./start-argus.sh

# In another terminal
cd argus-platform
npm run test:e2e
```

## Troubleshooting

### Services Won't Start

**Check if PostgreSQL is running:**
```bash
nc -z localhost 5432 && echo "PostgreSQL is running" || echo "PostgreSQL is not running"
```

**Check if Redis is running:**
```bash
redis-cli ping
# Should return: PONG
```

**Start services if needed:**
```bash
sudo port load postgresql15-server
sudo port load redis
```

### Database Connection Issues

**Verify database exists:**
```bash
psql -h localhost -U argus_user -d argus_pentest -c "SELECT version();"
```

**Reset database (WARNING: Deletes all data):**
```bash
cd argus-platform/db
./setup.sh
```

### Worker Issues

**Check Celery worker status:**
```bash
cd argus-workers
source venv/bin/activate
celery -A celery_app inspect active
```

**View worker logs:**
```bash
tail -f logs/celery.log
```

### Port Already in Use

**Find process using port 3000:**
```bash
lsof -ti:3000
```

**Kill process:**
```bash
kill -9 $(lsof -ti:3000)
```

### Clear Logs and Restart

```bash
./stop-argus.sh
rm -rf logs/*
./start-argus.sh
```

## Documentation

- [Setup Progress](docs/setup-progress.md) - Current implementation status
- [Database Setup](docs/database-setup.md) - Database installation guide
- [Architecture](FINAL-ARCHITECTURE.md) - Complete system architecture

## Contributing

This is currently a development project. Contribution guidelines will be added once the core platform is stable.

## License

TBD

## Security Notice

This platform is designed for authorized penetration testing only. Users must:
- Obtain written authorization before testing any target
- Respect scope limitations
- Comply with all applicable laws and regulations
- Use responsibly and ethically

Unauthorized use of this platform for malicious purposes is strictly prohibited and may be illegal.
