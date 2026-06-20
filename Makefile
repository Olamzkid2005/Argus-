.PHONY: dev stop test lint build clean docker-up docker-down help

# Default target
help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

# ── Development ──

dev: ## Start all services (Next.js + Celery workers)
	@./start-argus.sh

stop: ## Stop all services
	@./stop-argus.sh

dev-worker: ## Start only Celery workers
	cd argus-workers && source venv/bin/activate && celery -A celery_app worker --loglevel=info --concurrency=4

dev-flower: ## Start Flower (Celery monitoring)
	cd argus-workers && source venv/bin/activate && celery -A celery_app flower

# ── Testing ──

test: test-v5 test-backend ## Run all tests (V5 TUI tests + Python backend tests)

test-backend: ## Run backend tests
	cd argus-workers && source venv/bin/activate && pytest tests/ -q --tb=short

test-coverage: ## Run tests with coverage reports (V5 + Python backend)
	cd Argus-Tui/packages/opencode && bun test test/argus/ --coverage --timeout 30000
	cd argus-workers && source venv/bin/activate && pytest tests/ --cov=. --cov-report=html

# ── Linting ──

lint: lint-v5 lint-backend ## Run all linters

lint-backend: ## Lint backend code
	cd argus-workers && source venv/bin/activate && ruff check . --fix

# ── Build (V5 CLI — argus-platform was removed during v5 migration) ──
# `make build` was removed because argus-platform/ no longer exists.
# The V5 CLI is run directly via `bun run` — no build step is needed.
# If you need to bundle the CLI, see: Argus-Tui/package.json for bundling scripts.

typecheck: typecheck-v5 ## TypeScript type checking

# ── Docker ──

e2e-up: ## Start E2E test targets (Juice Shop, DVWA)
	docker compose --profile e2e up -d juice-shop dvwa

e2e-down: ## Stop E2E test targets
	docker compose --profile e2e down

e2e: ## Run full E2E test suite
	./scripts/e2e-test.sh

docker-up: ## Start all services with Docker Compose
	docker-compose up -d --build

docker-down: ## Stop Docker Compose services
	docker-compose down

docker-logs: ## View Docker Compose logs
	docker-compose logs -f

# ── Database (migrations run via Python runner) ──

db-migrate: ## Run database migrations
	cd argus-workers && python3 -m database.migrations.runner

# ── Cleanup ──

clean: clean-v5 ## Clean build artifacts and caches
	cd argus-workers && rm -rf __pycache__ .pytest_cache .semgrep_cache
	rm -rf logs/*.log

clean-all: clean ## Deep clean (including node_modules and venv)
	cd Argus-Tui/packages/opencode && rm -rf node_modules
	cd argus-workers && rm -rf venv

# ── Installation ──

install: install-v5 install-backend ## Install all dependencies

install-backend: ## Install backend dependencies
	cd argus-workers && python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt

# ── V5 TypeScript CLI ──

install-v5: ## Install V5 CLI dependencies
	cd Argus-Tui && bun install

typecheck-v5: ## Type-check V5 TypeScript code
	cd Argus-Tui/packages/opencode && bun typecheck

test-v5: ## Run V5 CLI tests (280+ tests)
	cd Argus-Tui/packages/opencode && bun test test/argus/ --timeout 30000

test-v5-ci: ## Run V5 CLI tests with JUnit output
	cd Argus-Tui/packages/opencode && bun test test/argus/ --timeout 30000 --reporter=junit

assess-v5: ## Run V5 assessment against a target (usage: make assess-v5 TARGET=https://example.com)
	cd Argus-Tui/packages/opencode && bun run src/argus/index.ts assess $(TARGET)

doctor-v5: ## Run V5 health checks
	cd Argus-Tui/packages/opencode && bun run src/argus/index.ts doctor

doctor-v5-online: ## Run V5 health checks with LLM connectivity test
	cd Argus-Tui/packages/opencode && bun run src/argus/index.ts doctor --online

lint-v5: ## Lint V5 TypeScript code
	cd Argus-Tui/packages/opencode && bun typecheck

clean-v5: ## Clean V5 build artifacts
	cd Argus-Tui/packages/opencode && rm -rf .artifacts

# ── Security ──

self-scan: ## Run Argus self-security scan
	cd argus-workers && source venv/bin/activate && python3 -c "from tasks.self_scan import run_self_scan; run_self_scan()"
