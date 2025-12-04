# Contribution guide

## Getting Started: Step-by-Step Setup

### Prerequisites

1. **uv** package manager

   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```

2. **Telegram Bot Token** - Create via [@BotFather](https://t.me/BotFather)
3. **Letta API Access** - Sign up at https://letta.com

### Setup Steps

**1. Clone and install:**

```bash
git clone <repository-url>
cd letta-client-bot
make dev # install all dependencies
```

**2. Configure environment:**
Copy `.env.example` to `.env` and fill in your credentials.

**3. Initialize database:**

```bash
uv run gel init
uv run gel migrate
```

**4. Run the bot:**

```bash
make poll
```

### Development Workflow

**Code quality:**

```bash
make check  # Runs linting, formatting, and type checking
```

**When adding features:**

1. Modify/add `.edgeql` queries → run `gel-py`
2. Implement feature
3. Test with `make poll`
4. Run `make check`
5. Update `notes/changelog.md`

**Database schema changes:**

1. Edit `dbschema/default.esdl`
2. For development: `gel watch --migrate` (auto-applies schema changes)
3. For production: `gel migration create` → `gel migrate`

## Weird solutions

### Message sending

Telegram can't parse '.' and other characters without escaping, so I had to wrap everything inside aiogram formating

## Planned features

### Very High Priority

- Migrate to self-hosted Gel <https://github.com/geldata/gel-docker>

### High Priority

- Agent content output configuration
  - Toggle verbose/brief tool execution display
  - Toggle reasoning messages on/off
- Clear messages command (for testing clean assistants)
- Strict Telegram error handling (timeouts, message length limits, invalid characters)

### Medium Priority

- Fix rapid message handling (many messages in a row from Telegram)
- Multi-user agent from personal assistant
  - Clone personal agent
  - Shared memory blocks (some read-only)
- Run gel schema migrations automatically
- Images support
- LaTeX support
- Memory block viewing and editing
- Agent rename
- Agent tags for filtering
- Usage analytics per identity
- Add message editing support

## Technical TODOs

Local TODOs are still in code

- Try gel single-file codegen <https://docs.geldata.com/reference/using/python/api/codegen#single-file-mode>
- Wrap auth logic with multiple db queries into transactions <https://docs.geldata.com/reference/using/python#transactions>
- Implement global error handling for agent message sending using aiogram middlewares <https://docs.aiogram.dev/en/v3.22.0/dispatcher/middlewares.html>
- Replace manual MarkdownV2 escaping with automatic conversion

## GEL

This project uses gel database as a storage layer

### Migrations or Database schema

For development run

`gel watch --migrate`

this will maintain database scheme allined with migrations to add database changes to the application run

`gel migration create`

### Add new queries

To add new queries to use in the application put query.edgeql to letta_bot/queries and run

`gel-py`

## Deployment

### Docker

**Stack**: Python 3.13-slim + uv + Traefik reverse proxy

**Dockerfile** (`deploy/Dockerfile`):

- Base: `python:3.13-slim`
- Non-root user: `app`
- Dependencies: `uv sync --frozen --no-dev`
- Entry: `uv run python letta_bot/main.py` (webhook mode)

**docker-compose.yaml** (`deploy/docker-compose.yaml`):

- Service: `letta-bot`
- Exposes port 80 (internal)
- Traefik labels: TLS + Let's Encrypt (`lets-encrypt-ssl` resolver)
- Router rule: `Host(${WEBHOOK_HOST}) && PathPrefix(${WEBHOOK_PATH})`
- Network: `monitoring_monitoring` (external)
- Volume: `bot-storage` (local)

**Required env vars**:

```
BOT_TOKEN, WEBHOOK_HOST, LETTA_PROJECT_ID, LETTA_API_KEY
GEL_INSTANCE, GEL_SECRET_KEY (if using Gel Cloud)
```

**Prerequisites**: Traefik with `lets-encrypt-ssl` resolver, `monitoring_monitoring` network exists, DNS configured for `WEBHOOK_HOST`.

## Logging Policy

### DEBUG

_(Reserved for future use)_

### INFO

**Major business logic events outside agent interaction**

### WARNING

**Unexpected behavior from code logic perspective**

### ERROR

**Easily recoverable errors**

### CRITICAL

**Non-recoverable errors affecting application availability**

### General Rules

1. MUST NOT log: passwords, API keys, tokens, credentials
2. MUST include context: user telegram_id, request identifiers, resource IDs
3. Use module loggers: `logger = logging.getLogger(__name__)`
