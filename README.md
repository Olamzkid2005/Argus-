# Argus SOC Platform

AI-powered cybersecurity operations center with autonomous vulnerability scanning, threat intelligence, and collaborative remediation workflows.

## Architecture

- **Frontend:** Next.js 14 (TypeScript) with App Router
- **Workers:** Python 3.11+ with Celery
- **Database:** PostgreSQL 15 with pgvector
- **Queue:** Redis
- **AI:** OpenRouter API (Multi-provider: Anthropic, OpenAI, Google, Meta, DeepSeek, Mistral, Qwen, NVIDIA, Perplexity)

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
│   ├── database-setup.md  # Database setup guide
│   ├── IMPROVEMENTS.md    # Comprehensive improvement recommendations
│   └── PENTEST-AGENTS-INTEGRATION.md  # Pentest agents integration guide
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
- ✅ Real-time engagement monitoring with WebSocket connections
- ✅ Vulnerability scanning with configurable aggressiveness (Default, High, Extreme)
- ✅ AI-powered vulnerability explanations and attack chain analysis
- ✅ Asset inventory management with risk scoring
- ✅ Custom detection rule engine with YAML-based rules
- ✅ Scheduled report generation with email delivery
- ✅ Team collaboration with assignments, comments, and approvals
- ✅ Activity feed and notification system
- ✅ Comprehensive analytics with trend visualization
- ✅ Multi-provider AI model selection (Anthropic, OpenAI, Google, Meta, DeepSeek, Mistral, Qwen, NVIDIA, Perplexity)

### Pages & Modules
- **Dashboard**: Real-time intelligence hub with engagement monitoring, threat feed, execution timeline, and scanner activities
- **Engagements**: Security assessment initiation with URL and repository scan types
- **Findings**: Comprehensive vulnerability management with AI analysis, verification, and evidence display
- **Analytics**: Vulnerability trends, severity distribution, and scheduled report management
- **Reports**: Report generation (PDF, HTML, JSON) with status tracking and sharing
- **Collaboration**: Team management, finding discussions, assignment workflows, and approval processes
- **Settings**: API key configuration, AI model selection, and scan aggressiveness presets
- **Rules**: Custom YAML-based detection rule creation and management
- **Assets**: Asset inventory with type-based filtering, risk levels, and lifecycle tracking

### Security Features
- Session management with NextAuth.js
- Scope validation and enforcement
- Rate limiting with Upstash Redis
- Audit logging for all operations
- Secure credential management

## Development Status

**Current Phase:** Production-Ready Frontend with Backend Infrastructure

**Completed:**
- ✅ Next.js 14 frontend with all pages implemented
- ✅ PostgreSQL database setup with comprehensive schema
- ✅ Redis configuration for caching and queuing
- ✅ Python worker project structure with Celery
- ✅ NextAuth.js authentication system
- ✅ Real-time WebSocket connections for engagement monitoring
- ✅ AI integration with OpenRouter multi-provider support
- ✅ Comprehensive test suite (frontend, backend, E2E)
- ✅ Automated start/stop scripts for services

**Frontend Pages:**
- ✅ Landing page with hero and features
- ✅ Authentication (sign-in, sign-up)
- ✅ Dashboard with real-time monitoring
- ✅ Engagements (scan initiation)
- ✅ Findings (vulnerability management)
- ✅ Analytics (trends and reports)
- ✅ Reports (generation and management)
- ✅ Collaboration (team, comments, assignments)
- ✅ Settings (API keys, AI models)
- ✅ Rules (custom detection rules)
- ✅ Assets (inventory management)

**Backend Infrastructure:**
- ✅ API routes for all CRUD operations
- ✅ WebSocket support for real-time updates
- ✅ Rate limiting with Upstash Redis
- ✅ Celery task queue system
- ✅ Security tool wrappers (Nuclei, httpx, subfinder, ffuf, sqlmap)
- ✅ Output parsers for security tools
- ✅ Database models and migrations

**Testing:**
- ✅ Frontend feature tests with Playwright
- ✅ Backend unit tests with pytest
- ✅ API integration tests
- ✅ E2E test scenarios

## API Endpoints

### Authentication
- `POST /api/auth/signup` - Create new user account
- `POST /api/auth/signin` - User login (NextAuth.js)
- `POST /api/auth/signout` - User logout
- `GET /api/auth/session` - Get current session

### Engagements
- `POST /api/engagement/create` - Create new security engagement
- `GET /api/engagement/[id]` - Get engagement details
- `GET /api/engagement/[id]/findings` - Get findings for engagement
- `GET /api/engagement/[id]/timeline` - Get engagement timeline
- `GET /api/engagement/[id]/explainability` - Get AI analysis explanations
- `POST /api/engagement/[id]/approve` - Approve engagement to start testing

### Findings
- `GET /api/findings` - List all findings with filtering
- `GET /api/findings/[id]` - Get specific finding details
- `POST /api/findings/[id]/verify` - Verify a finding
- `DELETE /api/findings/[id]` - Delete a finding
- `POST /api/findings/[id]/explain` - Request AI explanation

### Analytics
- `GET /api/analytics/trends` - Get vulnerability trends
- `GET /api/analytics/distribution` - Get severity distribution
- `POST /api/analytics/reports/schedule` - Schedule a report
- `GET /api/analytics/reports` - List scheduled reports

### Reports
- `POST /api/reports/generate` - Generate a new report
- `GET /api/reports` - List all reports
- `GET /api/reports/[id]/download` - Download a report
- `DELETE /api/reports/[id]` - Delete a report

### Collaboration
- `GET /api/collaboration/team` - Get team members
- `POST /api/collaboration/team/invite` - Invite team member
- `DELETE /api/collaboration/team/[id]` - Remove team member
- `GET /api/collaboration/comments` - Get comments for finding
- `POST /api/collaboration/comments` - Add comment
- `GET /api/collaboration/assignments` - Get assignments
- `POST /api/collaboration/assignments` - Create assignment
- `GET /api/collaboration/approvals` - Get approval requests
- `POST /api/collaboration/approvals/[id]/approve` - Approve request
- `GET /api/collaboration/activity` - Get activity feed
- `POST /api/collaboration/notifications/read` - Mark notifications as read

### Settings
- `GET /api/settings` - Get user settings
- `PUT /api/settings` - Update user settings
- `POST /api/settings/api-key` - Update API key
- `POST /api/settings/model` - Update AI model preference

### Rules
- `GET /api/rules` - List custom rules
- `POST /api/rules` - Create new rule
- `GET /api/rules/[id]` - Get rule details
- `PUT /api/rules/[id]` - Update rule
- `DELETE /api/rules/[id]` - Delete rule

### Assets
- `GET /api/assets` - List assets with filtering
- `POST /api/assets` - Create new asset
- `GET /api/assets/[id]` - Get asset details
- `PUT /api/assets/[id]` - Update asset
- `DELETE /api/assets/[id]` - Delete asset

### Real-Time Updates
- `GET /api/ws/engagement/[id]` - WebSocket connection for live updates
- `GET /api/ws/engagement/[id]/poll` - Long-polling fallback

### Tools & Performance
- `GET /api/tools/performance` - Get tool performance metrics

## Technology Stack

### Frontend
- Next.js 14 (App Router)
- TypeScript
- Tailwind CSS with custom theme
- Radix UI components
- Framer Motion for animations
- Lucide React icons
- Recharts for data visualization
- React Query for data fetching
- NextAuth.js for authentication
- next-themes for theme switching

### Backend
- Next.js API Routes
- PostgreSQL 15 (with pgvector for embeddings)
- Redis (job queue and caching)
- Upstash Redis for rate limiting

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
- OpenRouter API (multi-provider gateway)
- Supported providers: Anthropic, OpenAI, Google, Meta, DeepSeek, Mistral, Qwen, NVIDIA, Perplexity
- Custom intelligence engine for vulnerability analysis

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

# AI APIs (Optional - OpenRouter)
OPENROUTER_API_KEY=your_openrouter_api_key
```

**Workers (`argus-workers/.env`):**
```bash
# Database
DATABASE_URL=postgresql://argus_user:password@localhost:5432/argus_pentest

# Celery
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/0

# AI APIs (OpenRouter)
OPENROUTER_API_KEY=your_openrouter_key
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
- [Improvement Recommendations](docs/IMPROVEMENTS.md) - Comprehensive improvement roadmap
- [Pentest Agents Integration](docs/PENTEST-AGENTS-INTEGRATION.md) - Pentest agents integration guide
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
