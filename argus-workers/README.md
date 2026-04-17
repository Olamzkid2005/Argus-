# Argus Workers - Python Worker System

This directory contains the Python worker system for the Argus Pentest Platform. Workers handle tool execution, parsing, and intelligence operations using Celery with Redis as the message broker.

## Architecture

```
argus-workers/
├── celery_app.py          # Celery application configuration
├── orchestrator.py        # Main orchestration logic
├── intelligence_engine.py # AI-powered decision making
├── tools/                 # Tool execution wrappers
│   ├── nuclei_tool.py
│   ├── httpx_tool.py
│   ├── subfinder_tool.py
│   ├── ffuf_tool.py
│   └── sqlmap_tool.py
├── parsers/               # Tool output parsers
│   ├── nuclei_parser.py
│   ├── httpx_parser.py
│   └── ...
├── models/                # Pydantic models
│   ├── engagement.py
│   ├── finding.py
│   └── ...
├── database/              # Database access layer
│   ├── connection.py
│   └── repositories/
└── tests/                 # Unit and integration tests
```

## Setup

### 1. Create Virtual Environment

```bash
python3 -m venv venv
source venv/bin/activate  # On macOS/Linux
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure Environment

```bash
cp .env.example .env
# Edit .env with your configuration
```

### 4. Install Security Tools

The workers require several security tools to be installed:

```bash
# Install Go (required for many tools)
brew install go

# Install security tools
go install -v github.com/projectdiscovery/nuclei/v3/cmd/nuclei@latest
go install -v github.com/projectdiscovery/httpx/cmd/httpx@latest
go install -v github.com/projectdiscovery/subfinder/v2/cmd/subfinder@latest
go install -v github.com/ffuf/ffuf/v2@latest

# Install sqlmap
brew install sqlmap
```

## Running Workers

### Start Celery Worker

```bash
celery -A celery_app worker --loglevel=info --concurrency=4
```

### Start Celery Beat (for scheduled tasks)

```bash
celery -A celery_app beat --loglevel=info
```

### Monitor with Flower

```bash
celery -A celery_app flower
```

Then open http://localhost:5555 in your browser.

## Task Types

### 1. Recon Tasks
- `tasks.recon.discover_subdomains` - Subdomain enumeration
- `tasks.recon.probe_endpoints` - HTTP probing
- `tasks.recon.discover_technologies` - Technology detection

### 2. Scan Tasks
- `tasks.scan.run_nuclei` - Vulnerability scanning with Nuclei
- `tasks.scan.fuzz_endpoints` - Directory/parameter fuzzing
- `tasks.scan.test_sql_injection` - SQL injection testing

### 3. Analysis Tasks
- `tasks.analyze.evaluate_findings` - AI-powered finding analysis
- `tasks.analyze.build_attack_graph` - Attack path construction
- `tasks.analyze.decide_next_action` - Intelligence-driven decisions

### 4. Report Tasks
- `tasks.report.generate_report` - Final report generation

## Development

### Running Tests

```bash
pytest tests/
```

### Code Style

```bash
# Format code
black .

# Lint code
flake8 .

# Type checking
mypy .
```

## Database Access

Workers connect to PostgreSQL using SQLAlchemy. Connection pooling is configured in `database/connection.py`.

## Logging

Structured logging is configured using `structlog`. All logs include:
- `trace_id` - For request tracing
- `engagement_id` - For engagement tracking
- `worker_id` - For worker identification
- `timestamp` - ISO 8601 format

## Error Handling

Workers implement:
- Automatic retry with exponential backoff
- Dead letter queue for failed tasks
- Checkpoint recovery for long-running operations
- Graceful shutdown handling

## Security

- All tool executions are sandboxed
- Scope validation before every operation
- Rate limiting per target domain
- Secrets managed via environment variables
- No sensitive data in logs

## Monitoring

Key metrics tracked:
- Task execution time
- Task success/failure rate
- Tool execution duration
- Queue depth
- Worker health

## Next Steps

1. Implement `celery_app.py` with Celery configuration
2. Create `orchestrator.py` with main orchestration logic
3. Implement tool wrappers in `tools/`
4. Create parsers in `parsers/`
5. Build intelligence engine in `intelligence_engine.py`
