"""
This E2E test has been removed.

The previous test required a running Next.js frontend (argus-platform),
PostgreSQL, Redis, and browser-use-direct CLI, making it non-portable.

A CLI-focused E2E test now lives in argus-cli/tests/test_cli_e2e.py,
which tests the actual CLI behavior using click.testing.CliRunner
and the CommandRegistry directly — no external services required.
"""
