# ── AgentOS Makefile ──────────────────────────────────────────────────────────
# Quick reference for common dev & ops tasks.
#
#   make help          Show this help
#   make install       Install all dependencies
#   make dev           Start development server
#   make test          Run all tests
#   make test-fast     Run fast unit tests only
#   make lint          Run linting checks
#   make format        Auto-format code
#   make build         Build Docker image
#   make up            Start full stack (docker compose)
#   make down          Stop full stack
#   make bench         Run production benchmark

.PHONY: help install dev test test-fast lint format build up down bench clean

SHELL := /bin/bash
PYTHON := python3
PIP := pip3
PYTEST := pytest
DOCKER := docker

# ── Help ───────────────────────────────────────────────────────────────

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-18s\033[0m %s\n", $$1, $$2}'

# ── Development ─────────────────────────────────────────────────────────

install: ## Install all dependencies
	$(PIP) install -e ".[dev,server,all]"

dev: ## Start development server with hot reload
	uvicorn agentos.api.server:app --reload --host 0.0.0.0 --port 8000

shell: ## Start Python REPL with AgentOS imported
	$(PYTHON) -c "import agentos; print(f'AgentOS {agentos.__version__} ready')" && $(PYTHON)

# ── Testing ─────────────────────────────────────────────────────────────

test: ## Run all tests
	$(PYTEST) tests/ -v --tb=short

test-fast: ## Run fast unit tests (no LLM calls)
	$(PYTEST) tests/ -q --tb=short \
		--ignore=tests/test_code_agent.py \
		--ignore=tests/test_e2e_tool_agent.py \
		--ignore=tests/test_function_calling.py \
		--ignore=tests/test_skills_in_agent.py \
		--ignore=tests/test_production_agent.py \
		--ignore=tests/test_pipeline.py \
		--ignore=tests/test_fusion.py

test-cov: ## Run tests with coverage report
	$(PYTEST) tests/ --cov=agentos --cov-report=html --cov-report=term

bench: ## Run production benchmark
	$(PYTHON) temp/bench_prod.py

# ── Code Quality ────────────────────────────────────────────────────────

lint: ## Run linting (ruff + mypy)
	ruff check agentos/
	mypy agentos/ --ignore-missing-imports || true

format: ## Auto-format code
	ruff format agentos/
	ruff check --fix agentos/

typecheck: ## Run mypy type checking
	mypy agentos/ --ignore-missing-imports

# ── Docker ──────────────────────────────────────────────────────────────

build: ## Build Docker image
	$(DOCKER) build -t agentos:latest .

up: ## Start full stack (Docker Compose)
	docker compose up -d

down: ## Stop full stack
	docker compose down

logs: ## Tail Docker Compose logs
	docker compose logs -f

restart: down up ## Restart full stack

# ── Database ────────────────────────────────────────────────────────────

migrate: ## Run database migrations
	$(PYTHON) -m agentos.db.migrate upgrade

migrate-create: ## Create new migration (usage: make migrate-create MSG="add users table")
	$(PYTHON) -m agentos.db.migrate create "$(MSG)"

# ── Utilities ───────────────────────────────────────────────────────────

clean: ## Remove build artifacts, caches, temp files
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .mypy_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .ruff_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name htmlcov -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name *.egg-info -exec rm -rf {} + 2>/dev/null || true
	rm -rf temp/*.pyc dist/ build/ 2>/dev/null || true

version: ## Show current version
	$(PYTHON) -c "import agentos; print(agentos.__version__)"

count: ## Count source lines of code
	find agentos -name "*.py" | xargs wc -l | tail -1
