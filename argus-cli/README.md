# Argus CLI

Terminal-first AI Security Agent — transforms Argus from a web application into a Claude-Code-style security platform.

## Overview

```
╔═══════════════════════════════════════════════════════════╗
║                                                           ║
║     ARGUS v4  —  Security AI Agent                       ║
║                                                           ║
║     Claude Code + OWASP Testing + Security Automation     ║
║                                                           ║
╚═══════════════════════════════════════════════════════════╝
```

## Installation

```bash
# From the argus-cli directory
pip install -e .

# Or globally
pip install argus-cli
```

## Usage

```bash
# Launch interactive TUI
argus

# Scan a target immediately
argus --target example.com

# Use specific model
argus --model claude-sonnet

# Plain CLI mode (no TUI)
argus --no-tui

# Show configuration
argus --config

# List providers
argus --providers
```

## Interactive Commands

| Command | Description | Example |
|---------|-------------|---------|
| `/scan <target>` | Full security scan | `/scan example.com` |
| `/recon <target>` | Reconnaissance only | `/recon example.com` |
| `/auth <target>` | Test authentication | `/auth example.com` |
| `/api <target>` | API security testing | `/api api.example.com` |
| `/report` | Generate report | `/report` |
| `/status` | Show status | `/status` |
| `/config` | Show configuration | `/config` |
| `/model <name>` | Change AI model | `/model gpt-5` |
| `/providers` | List providers | `/providers` |
| `/sessions` | List sessions | `/sessions` |
| `/help` | Show help | `/help` |
| `/quit` | Exit | `/quit` |

## Configuration

Configuration file: `~/.config/argus/config.toml`

```toml
provider = "openai"
model = "gpt-4o-mini"
temperature = 0.3
max_iterations = 10
timeout = 300
aggressiveness = "balanced"  # passive | balanced | aggressive
output_format = "markdown"   # markdown | html | json
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

## Environment Variables

| Variable | Description |
|----------|-------------|
| `ARGUS_PROVIDER` | Default provider |
| `ARGUS_MODEL` | Default model |
| `ARGUS_API_KEY` | API key |
| `ARGUS_API_URL` | Custom API endpoint |
| `ARGUS_TEMPERATURE` | LLM temperature |
| `ARGUS_MAX_ITERATIONS` | Max agent iterations |
| `ARGUS_TIMEOUT` | Tool timeout (seconds) |
| `ARGUS_AGGRESSIVENESS` | Scan aggressiveness |
| `ARGUS_AUTO_APPROVE` | Auto-approve destructive actions |
| `ARGUS_OUTPUT_FORMAT` | Report format |
| `ARGUS_VERBOSE` | Verbose output |

## Architecture

```
argus-cli/
├── argus_cli/
│   ├── core/          # Banner, providers, runner
│   ├── tui/           # Textual TUI app and widgets
│   ├── commands/      # Interactive command registry
│   ├── session/       # SQLite session management
│   ├── streaming/     # Real-time output streaming
│   ├── config/        # Configuration management
│   └── security/      # Argus workers bridge
```

## Model Support

- **OpenAI**: gpt-5, gpt-4o, gpt-4o-mini, o3, o4-mini
- **Anthropic**: claude-opus-4, claude-sonnet-4, claude-haiku-4
- **Google**: gemini-2.5-pro, gemini-2.5-flash, gemini-2.0-flash
- **OpenRouter**: Any model via OpenRouter
- **Ollama**: qwen3, llama3.3, deepseek-r1, codellama (local)
- **Azure**: Azure OpenAI models

## Feature Flags

Feature flags are stored in `~/.config/argus/features.yaml`:

```yaml
planner: true        # LLM-driven planning
recon: true          # Reconnaissance tools
auth: true           # Authentication testing
api_testing: true    # API security testing
reporting: true      # Report generation
llm_driven: true     # AI-driven tool selection
streaming: true      # Real-time output streaming
mcp_bridge: true     # MCP protocol bridge
swarm: false         # Multi-agent swarm (experimental)
chain_exploits: false # Chain exploit generation (experimental)
```

## Deterministic Fallback

When LLM is unavailable or disabled, Argus falls back to deterministic workflows:
- Recon: httpx → katana
- Scan: nuclei → ffuf
- No AI required — fully functional offline

## Integration with Argus Workers

The CLI integrates with the existing `argus-workers/` Python package:
- Orchestrator (workflow execution)
- ReAct Agent (LLM-driven tool selection)
- Intelligence Engine (decision-making)
- Tool Registry (security tools)
- State Machine (engagement lifecycle)
- Streaming (SSE events)
- MCP Server (tool protocol)

If `argus-workers` is not available, the CLI operates in deterministic mode.
