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

1. Edit `dbschema/default.gel`
2. For development: `gel watch --migrate` (auto-applies schema changes)
3. For production: `gel migration create` → `gel migrate`

## Claude Code Skills

Project-specific skills live in `.claude/skills/`. These are markdown prompts that automate common development workflows. Works with any LLM, but Claude Code natively triggers and supports them.

**Available skills:**

| Skill | What it does |
|-------|--------------|
| `update-changelog` | Drafts changelog entries from git history |
| `update-docs` | Syncs CLAUDE.md with code changes |
| `merge-readiness` | Pre-merge checklist (conflicts, migrations, tests, docs) |
| `manual-review` | Reviews a diff or PR with concrete feedback |
| `use-railway` | Deploy and operate the bot on Railway |

**Usage:** Just ask naturally or use trigger phrases. Skills auto-activate based on context.

**Adding new skills:**

1. Create `.claude/skills/<skill-name>/SKILL.md`
2. Add frontmatter with `name` and `description` (include trigger phrases)
3. Write concise instructions (skills share context window)

See [Claude Code Skills docs](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices) for detailed guidance.

## Weird solutions

### Message sending

Telegram can't parse '.' and other characters without escaping, so I had to wrap everything inside aiogram formating

## Planned features

### Very High Priority

### High Priority

- Agent content output configuration
  - Toggle verbose/brief tool execution display
  - Toggle reasoning messages on/off

### Medium Priority

- Fix rapid message handling (many messages in a row from Telegram)
- Multi-user agent from personal assistant
  - Clone personal agent
  - Shared memory blocks (some read-only)
- LaTeX support
- Memory block editing (viewing is done — see `/current`)
- Agent rename
- Usage analytics per identity
- Add message editing support

## Devscripts

Development scripts for Letta API operations live in `devscripts/`. All scripts use **sync clients** and `CONFIG` from `letta_bot.config` via `bootstrap.py`.

### Running Scripts

```bash
uv run python -m devscripts.<script_name> [args]
```

Fleet operations. The writing ones are dry-run by default — `--execute` applies:

| Script | What it does | Writes |
|--------|--------------|--------|
| `context_headroom` | Report per-agent context headroom | no |
| `detect_compaction_loop` | Find agents stuck summarizing themselves | no |
| `sync_custom_tools` | Push tool sources, backfill `LETTA_API_KEY` | `--execute` |
| `cancel_stuck_runs` | Cancel non-terminal runs that block new messages | `--execute` |
| `raise_context_window` | Widen context windows kept from an older model | `--execute` |
| `migrate_sonnet5` | Move agents to a newer model and notify them | `--execute` |

### Writing New Scripts

**Standard pattern** - use `bootstrap.py`:

```python
"""Short description of what the script does.

Usage:
    uv run python -m devscripts.my_script [args]
"""

from devscripts.bootstrap import letta, gel, print_config, resolve_agent_id
from letta_bot.config import CONFIG


def main() -> None:
    """Main entry point."""
    print_config()  # Always print key inputs first

    # Use sync Letta client
    agents = letta.agents.list()

    # Use sync Gel client
    users = gel.query('select User { telegram_id }')


if __name__ == '__main__':
    main()
```

**Key principles:**

1. **Sync clients only** - no `async`/`await`, no `asyncio.run()`
2. **Import clients from bootstrap** - `from devscripts.bootstrap import letta, gel, print_config`
3. **Use `CONFIG.field`** for env vars already in Config (e.g., `CONFIG.openai_api_key`)
4. **Use `resolve_agent_id()`** for agent ID resolution (CLI > env > .agent_id file)
5. **Always call `print_config()`** at script start (pass extra kwargs for script-specific inputs)
6. **Module docstring** - include usage example at top of file
7. **argparse for CLI args** - when script accepts arguments

**Available from bootstrap:**

- `letta` - sync Letta client (created at import time)
- `gel` - sync Gel client (created at import time)
- `print_config(**extra)` - print masked config values for verification
- `resolve_agent_id(cli_arg=None)` - resolve agent ID from CLI > env > .agent_id file

### Testing Custom Tools

`run_tool.py` runs a custom tool locally, or on the platform with `--remote`:

```bash
# List available tools
uv run python -m devscripts.run_tool -l

# Run with agent ID from CLI
uv run python -m devscripts.run_tool -a <agent-id> notify_via_telegram "Hello"

# Run (reads agent ID from LETTA_AGENT_ID env or .agent_id file)
uv run python -m devscripts.run_tool search_x_posts "TzKT" 24 20
```

**Tool execution environment:**

- `LETTA_AGENT_ID` - agent ID, the only env var the sandbox sets by itself
- everything else in the environment comes from the agent's `secrets`:
  `LETTA_API_KEY`, `TELEGRAM_BOT_TOKEN`
- `LETTA_PROJECT_ID` - project ID (local runs only, from .env)

The sandbox does define a `client` global, but it is built from
`LETTA_API_KEY` — and Letta Cloud never sets that variable, so on an agent
without the key in its `secrets` `client` is `None`. Measured on 2026-08-19 with
a throwaway agent and a probe tool returning its own globals:

| agent secrets | `client` | `Letta` | `agent_state` | env |
| --- | --- | --- | --- | --- |
| none | `None` | class available | absent | `LETTA_AGENT_ID` |
| `LETTA_API_KEY` set | live client | class available | absent | `LETTA_AGENT_ID`, `LETTA_API_KEY` |

Tools here build the client themselves from `LETTA_API_KEY` instead of using the
global. It is the same credential, but a missing key returns an error string
rather than an `AttributeError` on `None` — and it survives the injection
changing shape again, which it did once already without notice.

`agent_state` is never injected on Cloud; declaring it only adds a parameter.

Running locally executes the file on disk; the sandbox executes whatever source
is registered on the platform. The two drift. `--remote` runs the registered
source as the agent and is the only check that means anything:

```bash
uv run python -m devscripts.run_tool -r -a <agent-id> notify_via_telegram "test"
```

Note that a tool returning an error string still reports `status: "success"` —
read the payload, not the status.

**Publishing tool changes:**

```bash
uv run python -m devscripts.sync_custom_tools            # dry-run
uv run python -m devscripts.sync_custom_tools --execute  # push + backfill secrets
```

It updates tools by id rather than upserting: `tools.upsert()` names a tool
after the first top-level function in the file, so a file with a helper above
the tool function would register under the helper's name and leave the real
tool — and every agent attached to it — on the old source.

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
- Entry: `uv run --no-dev python -m letta_bot.main` (webhook mode)

**docker-compose.yaml** (`deploy/docker-compose.yaml`):

- Service: `letta-bot`
- Exposes port 80 (internal)
- Traefik labels: TLS + Let's Encrypt (`lets-encrypt-ssl` resolver)
- Router rule: `Host(${WEBHOOK_HOST}) && PathPrefix(${WEBHOOK_PATH})`
- Network: `monitoring_monitoring` (external)
- Second service `gel`: self-hosted GelDB, applies migrations on start, own
  Traefik router

**Required env vars**:

```
TELEGRAM_BOT_TOKEN, WEBHOOK_HOST, LETTA_PROJECT_ID, LETTA_API_KEY
GEL_HOST, GEL_PORT, GEL_PASSWORD, GEL_CLIENT_TLS_SECURITY  (self-hosted gel)
GEL_INSTANCE, GEL_SECRET_KEY                               (Gel Cloud instead)
```

**Prerequisites**: Traefik with `lets-encrypt-ssl` resolver, `monitoring_monitoring` network exists, DNS configured for `WEBHOOK_HOST`.

### Railway

`deploy/railway.toml` and `deploy/gel.Dockerfile` cover the Railway path — the
`use-railway` skill drives it.

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

**Step-by-step tracing inside one request** — middleware decisions, streaming
chunks, document handling. Off in production.

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
