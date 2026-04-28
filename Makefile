.PHONY: dev stop test lint build clean docker-up docker-down help

# Default target
help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

# ── Development ──

dev: ## Start all services (Next.js + Celery workers)
	@./start-argus.sh

stop: ## Stop all services
	@./stop-argus.sh

dev-platform: ## Start only Next.js dashboard
	cd argus-platform && npm run dev

dev-worker: ## Start only Celery workers
	cd argus-workers && source venv/bin/activate && celery -A celery_app worker --loglevel=info --concurrency=4

dev-flower: ## Start Flower (Celery monitoring)
	cd argus-workers && source venv/bin/activate && celery -A celery_app flower

# ── Testing ──

test: test-frontend test-backend ## Run all tests

test-frontend: ## Run frontend tests
	cd argus-platform && npm test -- --passWithNoTests --ci

test-backend: ## Run backend tests
	cd argus-workers && source venv/bin/activate && pytest tests/ -q --tb=short

test-e2e: ## Run E2E tests (requires running services)
	cd argus-platform && npm run test:e2e

test-coverage: ## Run tests with coverage reports
	cd argus-platform && npm run test:coverage
	cd argus-workers && source venv/bin/activate && pytest tests/ --cov=. --cov-report=html

# ── Linting ──

lint: lint-frontend lint-backend ## Run all linters

lint-frontend: ## Lint frontend code
	cd argus-platform && npm run lint

lint-backend: ## Lint backend code
	cd argus-workers && source venv/bin/activate && ruff check . --fix

typecheck: ## TypeScript type checking
	cd argus-platform && npx tsc --noEmit

# ── Build ──

build: ## Build Next.js for production
	cd argus-platform && npm run build

# ── Docker ──

docker-up: ## Start all services with Docker Compose
	docker-compose up -d --build

docker-down: ## Stop Docker Compose services
	docker-compose down

docker-logs: ## View Docker Compose logs
	docker-compose logs -f

# ── Database ──

db-setup: ## Set up database
	cd argus-platform/db && ./setup.sh

db-verify: ## Verify database setup
	cd argus-platform/db && ./verify.sh

db-reset: ## Reset database (WARNING: deletes all data)
	cd argus-platform/db && ./setup.sh

# ── Cleanup ──

clean: ## Clean build artifacts and caches
	cd argus-platform && rm -rf .next node_modules/.cache
	cd argus-workers && rm -rf __pycache__ .pytest_cache .semgrep_cache
	rm -rf logs/*.log

clean-all: clean ## Deep clean (including node_modules and venv)
	cd argus-platform && rm -rf node_modules
	cd argus-workers && rm -rf venv

# ── Installation ──

install: install-frontend install-backend ## Install all dependencies

install-frontend: ## Install frontend dependencies
	cd argus-platform && npm install

install-backend: ## Install backend dependencies
	cd argus-workers && python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt

# ── Security ──

self-scan: ## Run Argus self-security scan
	cd argus-workers && source venv/bin/activate && python3 -c "from tasks.self_scan import run_self_scan; run_self_scan()"
