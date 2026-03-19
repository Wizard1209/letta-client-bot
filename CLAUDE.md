# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

@CONTRIBUTION.md

## What This Is

A multi-user Telegram bot bridging users to Letta AI agents. Built on aiogram 3.x (Telegram), Gel/EdgeDB (persistence), and the Letta SDK (AI agents). Supports multimodal input (text, images, voice, documents), agent isolation per user via tag-based identity, and an admin approval workflow for access control.

## Commands

```bash
make dev          # Install all deps (including ruff, mypy, pytest)
make check        # Format + lint + typecheck (run before committing)
make poll         # Run bot locally in polling mode

# Tests
uv run pytest                                # Run all tests
uv run pytest tests/test_md_tg_converter.py  # Single test file
uv run pytest -k "test_name"                 # Single test by name

# Database
gel watch --migrate                    # Dev: auto-apply schema changes
gel migration create && gel migrate    # Prod: create + apply migration
uv run gel-py                          # Regenerate Python from .edgeql files

# Devscripts (sync-only utilities)
uv run python -m devscripts.<script_name> [args]
```

## Architecture

**Entry point:** `letta_bot/main.py` — webhook (default) or polling (`--polling` flag).

**Message flow:**
```
Telegram → Middleware (user upsert, agent load, photo buffering)
  → Router (auth | info | agent commands | agent messages)
  → Letta client streaming → Response handler → md_tg formatter → Telegram
```

**Key modules:**
- `client.py` — Shared async Letta client. Tag-based user-agent association (`identity-tg-{id}`, `owner-tg-{id}`, `creator-tg-{id}`) instead of Letta Identity API.
- `agent.py` — Message context building, multimodal content, streaming response handling, file/image/voice processing.
- `response_handler.py` — Markdown→Telegram conversion via `md_tg`, message chunking (4096 char limit), streaming progressive updates.
- `auth.py` — Identity model mapping Telegram users to `tg-{telegram_id}`, admin approval workflow for shared agents.
- `middlewares.py` — User identity upsert, agent selection, access validation, photo batching (PhotoBuffer with ~1s delay for album support), typing indicators.
- `client_tools/` — Registry pattern for custom tools (e.g., `generate_image`). Tools register at import time.
- `md_tg/` — Custom Markdown→Telegram MessageEntity converter. UTF-16 aware offsets, smart chunking at block boundaries.
- `transcription.py` — Voice→text via OpenAI Whisper or ElevenLabs Scribe.

**Database:** Gel (EdgeDB) with schema in `dbschema/default.gel`. Three types: `User`, `Identity`, `AuthorizationRequest`. Queries in `letta_bot/queries/*.edgeql` with auto-generated Python via `gel-py`.

**Config:** Pydantic Settings in `letta_bot/config.py`, reads from `.env`. Required: `telegram_bot_token`, `webhook_host`, `letta_project_id`, `letta_api_key`.

## Code Style

- **Strict mypy**: `disallow_untyped_defs`, `disallow_any_generics`, `strict_equality`. All code must be fully typed.
- **Ruff**: Line length 92, Python 3.13 target.
- **Devscripts excluded** from mypy (see pyproject.toml overrides).
- **Async everywhere** in bot code; devscripts are sync-only.
