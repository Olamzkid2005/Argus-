# Argus CLI

Terminal-first AI Security Agent — an OpenCode-style CLI for autonomous security testing, vulnerability scanning, and AI-powered penetration testing.

```
╔═══════════════════════════════════════════════════════════╗
║                                                           ║
║     ARGUS v5  —  Security AI Agent                       ║
║                                                           ║
║     TypeScript CLI · OpenCode Fork · Security Automation  ║
║                                                           ║
╚═══════════════════════════════════════════════════════════╝
```

## Quick Start (V5 TypeScript CLI)

```bash
# Install dependencies
cd Argus-Tui && bun install

# Run health checks
make doctor-v5

# Run an assessment
make assess-v5 TARGET=https://example.com

# With browser verification (opt-in via feature flags)
cd Argus-Tui/packages/opencode && bun run src/argus/index.ts assess https://example.com --enable-browser --creds ./creds.json

# Run tests (290+ tests, 0 failures expected)
make test-v5

# Available commands
cd Argus-Tui/packages/opencode && bun run src/argus/index.ts --help
```

## V5 CLI Commands

| Command | Description |
|---------|-------------|
| `assess <target>` | Full autonomous security assessment (planner → MCP bridge → verifiers → evidence → report) |
| `doctor [--online]` | Health checks: runtime, Python, MCP worker, Playwright, DB, credentials, toolchain, LLM provider |
| `verify <finding-id>` | Re-run browser verification for a specific finding |
| `report <engagement-id> [--format]` | Generate markdown/JSON/SARIF/HTML report from stored findings |
| `evidence <action> [args]` | Browse (`list`), inspect (`show`), prune old (`prune`), or verify integrity (`verify-package`) |
| `resume <engagement-id>` | Resume a paused/running engagement from the last incomplete phase |
| `config [filter]` | Show effective configuration with source annotations |

### Feature Flags (all opt-in by default)

| Flag | Env Var | Description |
|------|---------|-------------|
| `--enable-browser` | `ARGUS_FEATURE_BROWSER_VERIFICATION` | Browser-based verification (BOLA, XSS, PrivEsc) |
| `--enable-workflow-registry` | `ARGUS_FEATURE_WORKFLOW_REGISTRY` | Capability-based workflow planning |
| `--enable-engagement-store` | `ARGUS_FEATURE_ENGAGEMENT_STORE` | SQLite engagement persistence |
| `--enable-approval-gates` | `ARGUS_FEATURE_APPROVAL_GATES` | Interactive approval prompts for destructive actions |

### Example: Full Assessment with All Features

```bash
bun run src/argus/index.ts assess https://juice-shop.example.com \
  --enable-browser \
  --enable-approval-gates \
  --creds ./creds.json \
  --format html
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

## Project Structure

```
argus/
├── Argus-Tui/              # TypeScript CLI (OpenCode fork)
│   └── packages/opencode/  # V5 security assessment engine
│       ├── src/
│       │   ├── argus/      # Argus-specific modules
│       │   │   ├── planner/      # Workflow planning
│       │   │   ├── browser/      # Playwright verification
│       │   │   ├── evidence/     # Evidence capture
│       │   │   ├── reporting/    # Report generation
│       │   │   ├── bridge/       # MCP client → Python workers
│       │   │   ├── workflows/    # YAML workflow definitions
│       │   │   ├── engagement/   # State store
│       │   │   └── commands/     # Security CLI commands
│       │   └── ...               # OpenCode runtime
│       └── package.json
│
├── argus-workers/          # Python security engine
│   ├── mcp_server.py       # MCP protocol server
│   ├── orchestrator_pkg/   # Orchestrator execution
│   ├── tools/              # Security tool wrappers
│   └── ...
│
├── docs/                    # Architecture docs & ADRs
├── .env.example
├── docker-compose.yml
├── Makefile
├── start-argus.sh
└── stop-argus.sh
```

## License

MIT

## Security Notice

This platform is designed for authorized penetration testing only. Users must:
- Obtain written authorization before testing any target
- Respect scope limitations
- Comply with all applicable laws and regulations

Unauthorized use for malicious purposes is strictly prohibited.
