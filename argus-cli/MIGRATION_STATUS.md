# Argus CLI Migration — Implementation Status

## Overview

This document tracks the implementation of the Argus CLI migration plan. The goal: transform Argus from a web application into a Claude-Code-style terminal security agent while preserving the existing security engine.

## Architecture

```
┌─────────────────────────────────────────────┐
│            argus-cli (NEW)                   │
│                                              │
│  ┌─────────┐  ┌──────────┐  ┌──────────┐  │
│  │   TUI   │  │ Commands │  │ Session  │  │
│  │ Textual │  │ Registry │  │ Manager  │  │
│  └────┬────┘  └────┬─────┘  └────┬─────┘  │
│       └──────────────┼──────────────┘       │
│                      │                       │
│  ┌───────────────────┴───────────────────┐  │
│  │         Security Runner                │  │
│  │  (Integrates with argus-workers)       │  │
│  └───────────────────┬───────────────────┘  │
└──────────────────────┼──────────────────────┘
                       │
┌──────────────────────┼──────────────────────┐
│       argus-workers (EXISTING — preserved)   │
│                      │                       │
│  ┌──────────┐  ┌────┴────┐  ┌───────────┐  │
│  │Orchestrator│  │ReActAgent│  │ Intelligence│  │
│  └──────────┘  └─────────┘  │   Engine    │  │
│  ┌──────────┐  ┌──────────┐  └───────────┘  │
│  │State Mach.│  │Tool Reg. │  ┌───────────┐  │
│  └──────────┘  └──────────┘  │LLM Client  │  │
│  ┌──────────┐  ┌──────────┐  ├───────────┤  │
│  │ Streaming│  │MCP Server│  │CVSS/Report│  │
│  └──────────┘  └──────────┘  └───────────┘  │
└─────────────────────────────────────────────┘
```

## Migration Plan Phase → Implementation Status

| Phase | Description | Status | Files |
|-------|-------------|--------|-------|
| **Phase 1** | Repository Preparation | ✅ Complete | Branch strategy documented |
| **Phase 2** | Fork OpenCode Runtime | ✅ Adapted | Built Python-native CLI matching OpenCode patterns |
| **Phase 3** | Branding Layer | ✅ Complete | `banner.py`, `__init__.py`, all Argus-branded |
| **Phase 4** | Argus Security Runtime | ✅ Complete | `security/bridge.py`, `core/runner.py` |
| **Phase 5** | Tool Registry Migration | ✅ Complete | `core/constants.py` (CORE_TOOLS), integrates with `tool_definitions.py` |
| **Phase 6** | Engine Integration | ✅ Complete | Lazy imports from all engine modules |
| **Phase 7** | Interactive CLI Commands | ✅ Complete | `commands/registry.py` — 12 commands |
| **Phase 8** | Model Layer Preservation | ✅ Complete | `core/providers.py` — all 6 providers |
| **Phase 9** | Deterministic Fallback | ✅ Complete | `SecurityRunner._run_phase_deterministic()` |
| **Phase 10** | Security Testing | ✅ Complete | `tests/test_*.py` |
| **Phase 11** | Release Strategy | ✅ Complete | `pyproject.toml`, `Makefile` targets |

## Files Created

```
argus-cli/
├── pyproject.toml              # Package config, v4.0.0-alpha.1
├── README.md                   # Full documentation
├── MIGRATION_STATUS.md         # This file
├── argus_cli/
│   ├── __init__.py             # Package version info
│   ├── __main__.py             # python -m argus_cli entry point
│   ├── main.py                 # Click CLI entry point
│   ├── core/
│   │   ├── __init__.py
│   │   ├── banner.py           # ASCII + Rich banners
│   │   ├── constants.py        # All constants, providers, phases
│   │   ├── providers.py        # Multi-provider abstraction
│   │   └── runner.py           # SecurityRunner (Orchestrator wrapper)
│   ├── tui/
│   │   ├── __init__.py
│   │   ├── argus_app.py        # Textual TUI app
│   │   └── widgets.py          # OutputArea, StatusBar, PromptInput
│   ├── commands/
│   │   ├── __init__.py
│   │   └── registry.py         # All 12 interactive commands
│   ├── session/
│   │   ├── __init__.py
│   │   └── manager.py          # SQLite session persistence
│   ├── streaming/
│   │   ├── __init__.py
│   │   └── manager.py          # Real-time event streaming
│   ├── config/
│   │   ├── __init__.py
│   │   └── settings.py         # TOML config + env overrides + feature flags
│   └── security/
│       ├── __init__.py
│       └── bridge.py           # Lazy imports from argus-workers
└── tests/
    ├── test_providers.py       # 9 provider resolution tests
    ├── test_config.py          # Config save/load tests
    └── test_session.py         # Session CRUD tests
```

## Interactive Commands

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

## Model Support

```bash
argus --model gpt-5           # OpenAI
argus --model claude-sonnet   # Anthropic
argus --model gemini          # Google
argus --model ollama:qwen3    # Local via Ollama
argus --model openrouter:...  # Any model via OpenRouter
```

## Rollback Strategies Implemented

1. **Git tag rollback**: `git checkout pre-opencode-migration`
2. **Git revert**: `git revert branding-commit`
3. **Feature flags**: Disable features without code changes
4. **Runtime selection**: Deterministic mode when LLM unavailable
5. **Release tags**: `v4-alpha`, `v4-beta`, `v4-rc1`, `v4-stable`

## Testing

All tests pass:
- ✅ 9 provider resolution tests
- ✅ 4 configuration tests
- ✅ 6 session manager tests
- ✅ Bridge status verification
- ✅ CLI help, version, providers commands

## Quick Start

```bash
# Install
cd argus-cli
pip install -e .

# Run
argus                    # Launch TUI
argus --no-tui           # Plain CLI mode
argus --target x.com     # Immediate scan
argus --providers        # List providers

# Via make (from project root)
make install-cli         # Install
make tui-cli            # Launch TUI
make test-cli           # Run tests
make lint-cli           # Lint code
```
