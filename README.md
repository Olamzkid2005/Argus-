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

### 1. Database Setup

```bash
# Install PostgreSQL and Redis (macOS with MacPorts)
sudo port install postgresql15 postgresql15-server redis

# Initialize and start PostgreSQL
sudo mkdir -p /opt/local/var/db/postgresql15/defaultdb
sudo chown postgres:postgres /opt/local/var/db/postgresql15/defaultdb
sudo -u postgres /bin/sh -c 'cd /opt/local/var/db/postgresql15 && /opt/local/lib/postgresql15/bin/initdb -D /opt/local/var/db/postgresql15/defaultdb'
sudo port load postgresql15-server

# Start Redis
sudo port load redis

# Create database and apply schema
cd argus-platform/db
./setup.sh
./verify.sh
```

### 2. Frontend Setup

```bash
cd argus-platform
npm install
cp .env.local.example .env.local  # Edit with your configuration
npm run dev
```

Open [http://localhost:3000](http://localhost:3000)

### 3. Worker Setup

```bash
cd argus-workers
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # Edit with your configuration

# Start Celery worker
celery -A celery_app worker --loglevel=info --concurrency=4

# Optional: Start Flower for monitoring
celery -A celery_app flower
# Open http://localhost:5555
```

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

## API Endpoints (Planned)

### Authentication
- `POST /api/auth/login` - User login
- `POST /api/auth/logout` - User logout
- `GET /api/auth/session` - Get current session

### Engagements
- `POST /api/engagement/create` - Create new engagement
- `GET /api/engagement/[id]` - Get engagement details
- `GET /api/engagement/[id]/findings` - Get findings
- `GET /api/engagement/[id]/attack-paths` - Get attack paths
- `POST /api/engagement/[id]/pause` - Pause engagement
- `POST /api/engagement/[id]/resume` - Resume engagement

### Findings
- `GET /api/findings` - List all findings
- `GET /api/findings/[id]` - Get finding details
- `PATCH /api/findings/[id]` - Update finding (verify, mark false positive)

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

**Frontend (.env.local):**
```bash
DATABASE_URL=postgresql://argus_user:password@localhost:5432/argus_pentest
REDIS_URL=redis://localhost:6379
NEXTAUTH_SECRET=your_secret_here
NEXTAUTH_URL=http://localhost:3000
```

**Workers (.env):**
```bash
DATABASE_URL=postgresql://argus_user:password@localhost:5432/argus_pentest
REDIS_URL=redis://localhost:6379
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/0
OPENAI_API_KEY=your_openai_key
ANTHROPIC_API_KEY=your_anthropic_key
```

## Testing

```bash
# Frontend tests
cd argus-platform
npm test

# Worker tests
cd argus-workers
source venv/bin/activate
pytest tests/
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
