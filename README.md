# Argus CLI

Terminal-first AI Security Agent — an OpenCode-style CLI for autonomous security testing, vulnerability scanning, and AI-powered penetration testing.

```
╔═══════════════════════════════════════════════════════════╗
║                                                           ║
║     ARGUS v4  —  Security AI Agent                       ║
║                                                           ║
║     Claude Code + OWASP Testing + Security Automation     ║
║                                                           ║
╚═══════════════════════════════════════════════════════════╝
```

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                   argus-cli                          │
│                                                      │
│  ┌─────────┐  ┌──────────┐  ┌──────────┐           │
│  │   TUI   │  │ Commands │  │ Session  │           │
│  │ Textual │  │ Registry │  │ Manager  │           │
│  └────┬────┘  └────┬─────┘  └────┬─────┘           │
│       └──────────────┼──────────────┘                │
│                      │                                │
│  ┌───────────────────┴───────────────────┐           │
│  │         Security Runner                │           │
│  │  (Integrates with argus-workers)       │           │
│  └───────────────────┬───────────────────┘           │
└──────────────────────┼────────────────────────────────┘
                       │
┌──────────────────────┼────────────────────────────────┐
│       argus-workers (Backend Engine)                   │
│                      │                                 │
│  ┌──────────┐  ┌────┴────┐  ┌───────────┐            │
│  │Orchestrator│  │ReActAgent│  │ Intelligence│         │
│  └──────────┘  └─────────┘  │   Engine    │           │
│  ┌──────────┐  ┌──────────┐  └───────────┘            │
│  │State Mach.│  │Tool Reg. │  ┌───────────┐           │
│  └──────────┘  └──────────┘  │LLM Client  │           │
│  ┌──────────┐  ┌──────────┐  ├───────────┤           │
│  │ Streaming│  │MCP Server│  │CVSS/Report│            │
│  └──────────┘  └──────────┘  └───────────┘            │
└──────────────────────┬──────────────────────────────────┘
                       │
              ┌────────▼────────┐
              │     Redis       │
              │   (Queue + Cache)│
              └─────────────────┘
```

## Quick Start

### Prerequisites

- Python 3.11+
- Redis
- (Optional) PostgreSQL 15+ for persistent findings

### 1. Install Argus CLI

**macOS / Linux:**
```bash
cd argus-cli
pip install -e .
```

**Windows:**
```powershell
cd argus-cli
pip install -e .
```

### 2. Install Worker Dependencies

**macOS / Linux:**
```bash
cd argus-workers
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

**Windows:**
```powershell
cd argus-workers
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Configure

Set your AI provider API key:

**macOS / Linux:**
```bash
export OPENAI_API_KEY=sk-...
# or
export ANTHROPIC_API_KEY=sk-ant-...
# or
export GEMINI_API_KEY=...
```

**Windows (PowerShell):**
```powershell
$env:OPENAI_API_KEY = "sk-..."
$env:ANTHROPIC_API_KEY = "sk-ant-..."
$env:GEMINI_API_KEY = "..."
```

### 4. Run

```bash
# Launch interactive TUI
argus

# Scan a target immediately
argus --target example.com

# Plain CLI mode
argus --no-tui --target example.com

# Use a specific model
argus --model claude-sonnet
```

### Start All Services (CLI + Workers + Redis)

**macOS / Linux:**
```bash
./start-argus.sh
# or
./scripts/mac/start-argus.sh
```

**Windows (PowerShell):**
```powershell
.\scripts\windows\start-argus.ps1
```

## Usage

### CLI Options

```bash
argus                          # Launch interactive TUI
argus --target example.com     # Scan immediately
argus --model claude-sonnet    # Use specific model
argus --no-tui                 # Plain CLI mode
argus --config                 # Show config path
argus --providers              # List AI providers
argus --version                # Show version
argus --help                   # Show help
```

### Interactive Commands

| Command | Description |
|---------|-------------|
| `/scan <target>` | Full security scan (recon → scan → analyze → report) |
| `/recon <target>` | Reconnaissance only (httpx, katana) |
| `/auth <target>` | Authentication testing |
| `/api <target>` | API security testing (BOLA/BOPLA) |
| `/report` | Generate security report |
| `/status` | Show engagement status |
| `/config` | Show/edit configuration |
| `/model <name>` | Change AI model |
| `/providers` | List available providers |
| `/sessions` | List saved sessions |
| `/clear` | Clear screen |
| `/quit` | Exit |

### AI Model Support

```bash
argus --model gpt-5              # OpenAI
argus --model claude-sonnet      # Anthropic
argus --model gemini             # Google
argus --model ollama:qwen3       # Local via Ollama
argus --model openrouter:...     # Any model via OpenRouter
```

## Project Structure

```
argus/
├── argus-cli/              # CLI/TUI (OpenCode-style)
│   ├── argus_cli/
│   │   ├── main.py        # Click CLI entry point
│   │   ├── core/          # Banner, providers, runner
│   │   ├── tui/           # Textual TUI app and widgets
│   │   ├── commands/      # Interactive command registry
│   │   ├── session/       # SQLite session management
│   │   ├── streaming/     # Real-time output streaming
│   │   ├── config/        # Configuration management
│   │   └── security/      # Argus workers bridge
│   ├── pyproject.toml
│   └── README.md
│
├── argus-workers/          # Python security engine
│   ├── celery_app.py      # Celery configuration
│   ├── orchestrator_pkg/  # Orchestrator execution logic
│   ├── agent/             # LLM ReAct agent
│   ├── tools/             # Security tool wrappers
│   ├── tasks/             # Celery task definitions
│   ├── parsers/           # Tool output parsers
│   ├── models/            # Pydantic data models
│   ├── database/          # Database access layer
│   └── config/            # Shared configuration
│
├── redis/                  # Redis binaries (Windows)
├── .env.example
├── docker-compose.yml
├── Makefile
├── start-argus.sh
└── stop-argus.sh
```

## Configuration

### Environment Variables

| Variable | Description |
|----------|-------------|
| `ARGUS_PROVIDER` | Default AI provider |
| `ARGUS_MODEL` | Default model |
| `ARGUS_API_KEY` | API key for provider |
| `ARGUS_API_URL` | Custom API endpoint |
| `ARGUS_TEMPERATURE` | LLM temperature |
| `ARGUS_MAX_ITERATIONS` | Max agent iterations |
| `ARGUS_TIMEOUT` | Tool timeout (seconds) |
| `ARGUS_AGGRESSIVENESS` | Scan aggressiveness |
| `ARGUS_AUTO_APPROVE` | Auto-approve destructive actions |
| `ARGUS_OUTPUT_FORMAT` | Report format |
| `ARGUS_VERBOSE` | Verbose output |

### Config File

`~/.config/argus/config.toml`:

```toml
provider = "openai"
model = "gpt-4o-mini"
temperature = 0.3
max_iterations = 10
timeout = 300
aggressiveness = "balanced"
output_format = "markdown"
stream_output = true
verbose = false
auto_approve = false

[features]
planner = true
recon = true
auth = true
api_testing = true
reporting = true
llm_driven = true
streaming = true
mcp_bridge = true
```

## Deterministic Fallback

When LLM is unavailable, Argus falls back to deterministic workflows:

- **Recon**: httpx → katana
- **Scan**: nuclei → ffuf
- **No AI required** — fully functional offline

## Workers Configuration

The CLI integrates with `argus-workers/` for:

- Orchestrator (workflow execution)
- ReAct Agent (LLM-driven tool selection)
- Intelligence Engine (findings analysis)
- Tool Registry (25+ security tools)
- State Machine (engagement lifecycle)
- Streaming (real-time events)
- MCP Server (tool protocol)

Worker config: `argus-workers/.env`

```bash
DATABASE_URL=postgresql://argus_user:password@localhost:5432/argus_pentest
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/0
OPENROUTER_API_KEY=your_openrouter_key
```

## Testing

```bash
# CLI tests
cd argus-cli
pip install -e ".[dev]"
pytest tests/

# Worker tests
cd argus-workers
source venv/bin/activate
pytest
```

## License

MIT

## Security Notice

This platform is designed for authorized penetration testing only. Users must:
- Obtain written authorization before testing any target
- Respect scope limitations
- Comply with all applicable laws and regulations

Unauthorized use for malicious purposes is strictly prohibited.
