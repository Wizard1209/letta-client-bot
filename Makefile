# Letta Telegram Bot - Development & Deployment Commands

.PHONY: help install dev lint format typecheck check test poll build up down logs restart clean

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
	@echo "  make clean      - Stop containers and remove volumes"

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

check: format lint typecheck
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
	docker compose -f deploy/docker-compose.yaml --env-file .env logs -f

restart: down build up
	@echo "Bot restarted successfully"

clean:
	docker compose -f deploy/docker-compose.yaml --env-file .env down -v
