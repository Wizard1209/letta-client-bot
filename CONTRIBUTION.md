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
5. Update `notes/changelog.md` (add to `[Latest additions]` section)

**Releasing a version:**

1. Move content from `[Latest additions]` to new versioned section (e.g., `[1.1.0] - 2025-12-09`)
2. Leave `[Latest additions]` empty for future changes
3. Update version in `pyproject.toml` and `letta_bot/__init__.py`

**Database schema changes:**

1. Edit `dbschema/default.esdl`
2. For development: `gel watch --migrate` (auto-applies schema changes)
3. For production: `gel migration create` → `gel migrate`

## Weird solutions

### Message sending

Telegram can't parse '.' and other characters without escaping, so I had to wrap everything inside aiogram formating

## Planned features

### Very High Priority

### High Priority

- Agent content output configuration
  - Toggle verbose/brief tool execution display
  - Toggle reasoning messages on/off
- Clear messages command (for testing clean assistants)

### Medium Priority

- Fix rapid message handling (many messages in a row from Telegram)
- Multi-user agent from personal assistant
  - Clone personal agent
  - Shared memory blocks (some read-only)
- Images support
- LaTeX support
- Memory block viewing and editing
- Agent rename
- Usage analytics per identity
- Add message editing support

## Devscripts

Development scripts for Letta API operations live in `devscripts/`. All scripts use **sync clients** and **plain env loading** via `bootstrap.py`.

### Running Scripts

```bash
uv run python -m devscripts.<script_name> [args]
```

### Writing New Scripts

**Standard pattern** - use `bootstrap.py`:

```python
"""Short description of what the script does.

Usage:
    uv run python -m devscripts.my_script [args]
"""

import argparse

from devscripts.bootstrap import env, letta, gel


def main() -> None:
    """Main entry point."""
    # Access env vars
    project_id = env('LETTA_PROJECT_ID')
    optional_var = env('OPTIONAL_VAR', 'default')

    # Use sync Letta client
    agents = letta.agents.list()

    # Use sync Gel client
    users = gel.query('select User { telegram_id }')


if __name__ == '__main__':
    main()
```

**Key principles:**

1. **Sync clients only** - no `async`/`await`, no `asyncio.run()`
2. **Import from bootstrap** - `from devscripts.bootstrap import env, letta, gel`
3. **Plain env access** - `env('VAR')` or `env('VAR', 'default')`
4. **No CONFIG** - don't import `letta_bot.config.CONFIG`, use `env()` directly
5. **Module docstring** - include usage example at top of file
6. **argparse for CLI args** - when script accepts arguments

**Available from bootstrap:**

- `env(key, default=None)` - get env var (raises KeyError if not set and no default)
- `letta` - sync Letta client (lazy-loaded)
- `gel` - sync Gel client (lazy-loaded)

### Testing Custom Tools

`run_tool.py` tests Letta custom tools with same injected context as cloud runtime:

```bash
# List available tools
uv run python -m devscripts.run_tool -l

# Run with agent ID from CLI
uv run python -m devscripts.run_tool -a <agent-id> notify_via_telegram "Hello"

# Run (reads agent ID from LETTA_AGENT_ID env or .agent_id file)
uv run python -m devscripts.run_tool search_x_posts "TzKT" 24 20
```

**Injected context (same as Letta cloud):**

- `client` - Letta SDK client (injected as global)
- `LETTA_AGENT_ID` - agent ID (env var)
- `LETTA_PROJECT_ID` - project ID (from .env)

**Agent ID resolution order:**

1. `--agent-id` / `-a` CLI argument
2. `LETTA_AGENT_ID` environment variable
3. `.agent_id` file in project root (single line with agent UUID)

**Setting up .agent_id:**

```bash
echo "agent-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx" > .agent_id
```

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

## Error Handling Policy

### Infrastructure Errors

**Not handled in code** - these are critical preconditions that MUST exist:

- Database client (`gel_client`)
- Letta client
- Bot token, API keys
- Required middleware dependencies

If missing, the application should crash early. Don't wrap in try/except or check for None.

```python
# WRONG - defensive checking for infrastructure
gel_client = data.get('gel_client')
if not gel_client:
    LOGGER.error('gel_client not found')
    return None  # Silent failure

# RIGHT - assume infrastructure exists, let it crash if not
gel_client: AsyncIOExecutor = data['gel_client']
```

### Business Logic Errors

**Raise exceptions** - missing business objects should raise errors that propagate to common error handler:

- `from_user` is None (Telegram event without user context)
- Identity not found for authorized user
- Database query returned unexpected empty result

```python
# WRONG - silent skip
if not event.from_user:
    return None

# RIGHT - raise error for common handler
if not event.from_user:
    raise ValueError('Event missing from_user context')
```

### Authorization Failures

**User-facing** - notify user and block handler:

- User not authorized (no identity access)
- User has no agents available

```python
# Notify user, then block
await event.answer('You need to request bot access first using /access')
return None
```

### Key Principle

**Never silently skip.** Either:
1. Crash (infrastructure) - fail fast, fix deployment
2. Raise error (business logic) - common handler notifies user
3. Notify + block (authorization) - user knows what to do

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
