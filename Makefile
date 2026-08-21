# Letta Telegram Bot - Development & Deployment Commands

.PHONY: help install dev lint format typecheck check poll build up down logs restart

help:
	@echo "Available commands:"
	@echo "  make install    - Install dependencies with uv"
	@echo "  make dev        - Install with dev dependencies"
	@echo "  make lint       - Run ruff linter"
	@echo "  make format     - Format code with ruff"
	@echo "  make typecheck  - Run mypy type checker"
	@echo "  make check      - Run format, lint, and typecheck"
	@echo "  make poll       - Run bot in polling mode (local development)"
	@echo ""
	@echo "Docker commands:"
	@echo "  make build      - Build Docker image"
	@echo "  make up         - Start bot with docker-compose"
	@echo "  make down       - Stop containers"
	@echo "  make logs       - View container logs"
	@echo "  make restart    - Rebuild and restart (pull + build + down + up)"

# Development
install:
	uv sync --no-dev

dev:
	uv sync --group dev

lint:
	uv run ruff check . --fix

format:
	uv run ruff format .

typecheck:
	uv run mypy .

# lab/ is gitignored, so ruff skips it by default while mypy does not. The
# subproject carries its own gate; run it here too when it is present, or the
# root gate reports green on code it never linted.
check: format lint typecheck
	@if [ -d lab ]; then $(MAKE) -C lab check; fi
	@echo "All checks passed!"

poll:
	uv run python -m letta_bot.main -p

# Docker deployment
build:
	docker compose -f deploy/docker-compose.yaml --env-file .env build

up:
	docker compose -f deploy/docker-compose.yaml --env-file .env up -d

down:
	docker compose -f deploy/docker-compose.yaml --env-file .env down

logs:
	docker compose -f deploy/docker-compose.yaml --env-file .env logs -f letta-bot

logs-db:
	docker compose -f deploy/docker-compose.yaml --env-file .env logs -f gel

pull:
	git pull

r: pull build up

restart: build down up
	@echo "Bot restarted successfully"
