# Argus

```
    █████╗ ██████╗  ██████╗ ██╗   ██╗███████╗
   ██╔══██╗██╔══██╗██╔════╝ ██║   ██║██╔════╝
   ███████║██████╔╝██║  ███╗██║   ██║███████╗
   ██╔══██║██╔══██╗██║   ██║██║   ██║╚════██║
   ██║  ██║██║  ██║╚██████╔╝╚██████╔╝███████║
   ╚═╝  ╚═╝╚═╝  ╚═╝ ╚═════╝  ╚═════╝ ╚══════╝
```

Autonomous Security Assessment Platform.

Terminal-first security agent for autonomous vulnerability discovery, reconnaissance, and AI-powered penetration testing. Built on OpenCode's TUI infrastructure with a custom security assessment engine.

## Quick Start

```bash
# Install dependencies
cd Argus-Tui && bun install

# Run the interactive TUI
bun dev

# Run health checks (via launcher script — recommended)
./start-argus.sh doctor

# Or run health checks directly (from the package directory)
cd Argus-Tui/packages/opencode && bun run src/argus/main.ts doctor

# Run an assessment
./start-argus.sh assess https://example.com

# Make the `argus` CLI available globally (optional)
cd Argus-Tui/packages/opencode && bun link
argus doctor           # now works anywhere

# Run tests
make test-v5
```

## Usage

### CLI Mode

> **Note:** The `argus` CLI is available after running `bun link` from `Argus-Tui/packages/opencode`.
> Alternatively, use `./start-argus.sh <command>` or `bun run src/argus/main.ts <command>` from the package directory.

| Command | Description |
|---------|-------------|
| `argus` | Launch interactive TUI |
| `argus doctor` | Health checks: runtime, Python, MCP worker, toolchain, LLM |
| `argus assess <target>` | Full autonomous security assessment |
| `argus report <id>` | Generate report from stored findings |
| `argus resume <id>` | Resume a paused engagement |
| `argus verify <finding-id>` | Re-run browser verification |
| `argus evidence <action>` | Browse and manage evidence |
| `argus config` | Show configuration |

### TUI Slash Commands

Inside the interactive TUI (launched with `argus` or `bun dev`):

| Command | Description |
|---------|-------------|
| `/assess <target>` | Run full assessment |
| `/recon <target>` | Run reconnaissance only |
| `/doctor` | Run health checks |
| `/status` | Show system status |
| `/findings` | Browse assessment findings |
| `/engagements` | List saved engagements |
| `/report <id>` | Generate report |
| `/tools` | Show registered MCP tools |
| `/workflows` | Show workflow definitions |
| `/config` | Show configuration |
| `/help` | Show all commands |

Natural language also works — type `"assess https://example.com"` or `"find vulnerabilities in example.com"`.

## Architecture

```
argus                         # CLI + TUI entry point
  │
  ├── argus doctor            # Health checks
  ├── argus assess <target>   # Assessment mode
  └── (no args)               # Interactive TUI
        │
        ├── ArgusIntentClassifier
        │   ├── slash command? → route to handler
        │   └── natural language? → classify intent
        │
        ├── WorkflowRunner        # Assessment execution
        │   ├── Planner            # Capability-based workflow planning
        │   ├── WorkersBridge      # MCP client → Python workers
        │   ├── InProcessExecutor  # Phase execution engine
        │   └── ConfidenceEngine   # Finding confidence promotion
        │
        └── TUI Routes
            ├── Home (dashboard)
            ├── Scan (live progress)
            └── Findings (browser)

argus-workers/               # Python MCP server
  ├── mcp_server.py           # MCP protocol server
  ├── tools/definitions/      # 65 YAML tool definitions
  │   ├── nuclei.yaml         #  with capabilities,
  │   ├── sqlmap.yaml         #  signal_quality,
  │   ├── nmap.yaml           #  requires gates,
  │   └── ...                 #  priority, cost
  └── tool_definitions.py     # Legacy Python registry
```

## Project Structure

```
├── Argus-Tui/
│   └── packages/opencode/
│       ├── src/
│       │   ├── argus/           # Argus security platform
│       │   │   ├── agent.ts          # Agent facade
│       │   │   ├── intent-classifier.ts  # NL intent detection
│       │   │   ├── workflow-runner.ts    # Assessment execution
│       │   │   ├── tui-commands.ts       # Slash command defs
│       │   │   ├── tui/                  # TUI routes
│       │   │   │   ├── routes/scan.tsx       # Scan dashboard
│       │   │   │   ├── routes/findings.tsx   # Findings viewer
│       │   │   │   └── navigator.ts          # Route navigation
│       │   │   ├── planner/            # Workflow planning
│       │   │   ├── bridge/             # MCP client
│       │   │   ├── commands/           # CLI commands
│       │   │   ├── engagement/         # State store
│       │   │   ├── evidence/           # Evidence capture
│       │   │   ├── reporting/          # Report generation
│       │   │   ├── browser/            # Playwright verification
│       │   │   └── workflows/          # YAML workflow defs
│       │   ├── cli/                # OpenCode runtime (internal)
│       │   └── index.ts            # OpenCode TUI entry (internal)
│       └── package.json
│
├── argus-workers/            # Python MCP server
│   ├── mcp_server.py              # Tool execution server
│   └── tools/definitions/         # 65 tool YAML definitions
│
├── start-argus.sh             # Interactive TUI/CLI launcher
├── stop-argus.sh              # Cleanup script
├── Makefile                   # Build/test targets
└── .github/workflows/lint.yml  # CI: typecheck, tests, lint
```

## Development

```bash
# Run all Argus tests (~4,000 tests: 3,284 Python + 689 TypeScript)
make test-v5

# Type check
make typecheck-v5

# Run specific test file
cd Argus-Tui/packages/opencode
bun test test/argus/unit/commands/doctor.test.ts

# Lint Python workers
cd argus-workers && ruff check .
```

## Requirements

- **Bun** 1.x — TypeScript runtime
- **Python** 3.11+ — MCP worker
- **Security tools** — nuclei, nmap, nikto, httpx, subfinder, etc.
- **Playwright** — Browser verification (`npx playwright install chromium`)
- **Docker** — Containerized deployment (optional, for docker-compose)
- **PostgreSQL** — Database for engagement/finding storage (docker-compose or local)
- **Redis** — Cache and Celery message broker (docker-compose or local)
- **pgvector** — Vector similarity search for AI analysis (PostgreSQL extension)

## License

MIT

## Security Notice

This platform is designed for authorized penetration testing only. Users must:
- Obtain written authorization before testing any target
- Respect scope limitations
- Comply with all applicable laws and regulations

Unauthorized use for malicious purposes is strictly prohibited.
