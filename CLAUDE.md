# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A production-ready multi-user Telegram bot that leverages **Letta's identity system** for per-user agent isolation. Unlike the official letta-telegram bot (chat-scoped for single-user use), this bot is user-scoped and designed for larger client deployments with custom authentication.

## High-Level Architecture Summary

### Core Concept

Multi-user Telegram bot that manages per-user Letta agents through an identity-based authorization system. Users request agents from available templates, admins approve requests, and the bot handles identity creation and agent provisioning.

### Key Principles

- Templates fetched from Letta API (no local storage)
- One pending request per user (prevents spam)

## Core Architecture

### Letta Identity System

- **Single API key with per-user isolation**: Server manages one Letta API key; each Telegram user maps to a unique Letta identity
- **Flow**: `Telegram User → Letta Identity → Agents with identity_ids`
- **Identity format**: Identities use `tg-{telegram_id}` prefix as `identifier_key` (e.g., `tg-123456789`)
- **Identity creation with retry logic**: Attempts creation first; if identity exists, retrieves it by identifier_key
- **Agent operations** use `identity_ids=[identity.id]` for automatic scoping; list agents via identity-specific endpoints
- **Selected agent tracking**: Each identity stores `selected_agent` ID for message routing; auto-selects oldest agent if none set

### Agent Templates

- Available agent templates are fetched from Letta API at runtime
- Users request personal agent(s) from specific template architecture
- Agent created from template upon admin approval
- Template selection via inline keyboard with callback data containing template name and version

### Storage Strategy

**Gel/EdgeDB Database** (graph-relational database):

- Uses EdgeQL for queries (object-oriented graph query language)
- Async client via `gel.create_async_client()`
- Auto-generated query modules from `.edgeql` files in `letta_bot/queries/`
- Connection configured via environment variables (`GEL_INSTANCE`, `GEL_SECRET_KEY`)

**Database Schema (Object Types)**:

- **User**: Telegram user information (telegram_id, username, first_name, full_name)
- **Identity**: Letta identity mapping (identifier_key, identity_id, selected_agent)
- **AuthorizationRequest**: Access requests with status tracking (pending/allowed/denied)

**Generated Query Modules**:

- Auto-generated from `.edgeql` files in `letta_bot/queries/`
- Each `.edgeql` file generates a corresponding Python module with type-safe async functions
- Examples: `register_user`, `create_auth_request`, `get_identity`, `set_selected_agent`

### Authorization Flow

**Phase 1: User Registration**

- User sends `/start` to bot
- System registers new users in database
- Bot shows greeting message from `notes/welcome.md`

**Phase 2: Resource Request**

- **Identity-only request**: User runs `/request_identity` to request identity access without agent
- **Agent request**: User runs `/new_agent_from_template` to see available agent templates
- User selects template from inline keyboard
- System creates authorization requests:
  - Identity access request (if user doesn't have one) - resource_type: `ACCESS_IDENTITY`
  - Agent creation request for selected template - resource_type: `CREATE_AGENT_FROM_TEMPLATE`
- System prevents duplicate pending requests per user per resource type
- Admins receive notification via bot message

**Phase 3: Admin Approval**

- Admin views pending requests: `/admin pending`
  - Shows user details, request UUID, resource type, and resource ID
- Admin approves request: `/admin allow <request_uuid>`
  - **Identity requests**: Creates Letta identity with `tg-{telegram_id}` format, stores in database
  - **Agent requests**: Creates agent from template using `client.templates.agents.create()`
  - User receives approval notification
- Admin denies request: `/admin deny <request_uuid> [reason]`
  - Updates request status to denied
  - User receives notification with optional reason
  - User can submit new request after denial

**Phase 4: Message Routing and Response Processing**

- Authorized users send messages to bot
- System routes messages to user's selected agent (auto-selects oldest agent if none set)
- Bot streams agent responses via `client.agents.messages.create()` with `streaming=True`
- **Response handler** (`response_handler.py`) processes stream events:
  - **assistant_message**: Main agent response (formatted with bold "Agent response:" header)
  - **reasoning_message**: Internal agent reasoning (italic header, blockquote formatting)
  - **tool_call_message**: Tool execution details (parsed from JSON arguments)
  - **ping**: Heartbeat messages (displayed as "⏳Working on it⏳")
- **Specialized tool formatting**:
  - `archival_memory_insert`: "Agent remembered:" with blockquote content
  - `archival_memory_search`: "Agent searching:" with query
  - `memory_insert`: "Agent updating memory:" with new content
  - `memory_replace`: "Agent modifying memory:" showing old vs new
  - `run_code`: "Agent ran code:" with syntax-highlighted code block
  - Generic tools: Display tool name with JSON arguments
- Real-time message streaming with typing indicator

**Phase 5: Agent Management**

- **Switch agents**: `/switch_agent` command lists user's agents with checkmark on selected agent
- User selects agent from inline keyboard
- System updates `selected_agent` in database
- All subsequent messages route to newly selected agent

**Phase 6: Access Management**

- **List active users**: `/admin list`
  - Groups users by telegram_id
  - Shows all allowed resources per user
- **Revoke access**: `/admin revoke <telegram_id>`
  - Revokes only identity access (sets identity request status to denied)
  - User receives revocation notification
  - User can re-request access after revocation

## Development Commands

**Dependency management**: Use `uv` exclusively (NOT pip or poetry)

Common commands:

```bash
# Install dependencies
uv sync

# Install dev dependencies
uv sync --group dev

# Run linting
uv run ruff check .

# Run type checking
uv run mypy .

# Format code
uv run ruff format .

# Run the bot locally (polling mode)
uv run python letta_bot/main.py -p

# Run with custom info directory (via environment variable)
INFO_DIR=/path/to/notes uv run python letta_bot/main.py -p
```

**Docker deployment**:

```bash
# Build Docker image
docker build -t letta-client-bot:latest -f deploy/Dockerfile .

# Start with docker-compose
docker-compose -f deploy/docker-compose.yaml up -d

# View logs
docker-compose -f deploy/docker-compose.yaml logs -f letta-bot

# Stop containers
docker-compose -f deploy/docker-compose.yaml down

# Rebuild and restart
docker-compose -f deploy/docker-compose.yaml up -d --build
```

## Code Quality Standards

### Ruff Configuration

- Line length: 88 characters
- Target: Python 3.13
- Enabled linters: pycodestyle, pyflakes, isort, flake8-bugbear, pyupgrade, annotations, comprehensions, simplify
- Quote style: **single quotes** (not double)
- Import sorting: known-first-party is `letta_client_bot`

### MyPy Configuration

- Strict mode enabled
- Require type annotations for all functions (except tests)
- Check untyped definitions
- No implicit optional
- Warn on redundant casts, unused ignores, unreachable code

### Important Notes

- Module for Letta client imports: Mark as `ignore_missing_imports = true` in mypy config
- Test files: Type annotations optional

## Changelog Maintenance

The project maintains a changelog at `notes/changelog.md` in Telegram MarkdownV2 format. When updating the changelog:

**What to Include:**

- **User-facing features**: New commands, UI improvements, user-visible functionality
- **Key technical improvements**: Performance enhancements, architecture changes, integration updates
- **Feature descriptions**: Clear explanations of what the feature does for users (not just technical names)
  - Good: "Progressive 'working' indicator that updates in real-time during agent processing (shows increasing hourglass symbols while waiting)"
  - Bad: "Smart ping indicator system" (unclear what it does)

**What to Exclude:**

- Internal/meta changes: Updates to CONTRIBUTION.md, README.md, internal documentation
- Code organization details: File renames, module consolidations (unless they represent a major architectural change)
- Development tooling changes: Unless they affect how contributors work with the project

**Structure:**

- Use `*Added:*` for new features and capabilities
- Use `*Changed:*` for improvements to existing features
- Generally avoid `*Removed:*` section - focus on what's new and improved

**Example:**

```markdown
_Added:_
• Progressive "working" indicator that updates in real-time during agent processing

_Changed:_
• Agent responses now render with proper Telegram-compatible markdown formatting
```

## Project Structure

Current module organization:

```
letta_bot/
  main.py              # Bot entry point with webhook/polling modes, /start handler
  config.py            # Configuration management (Pydantic settings)
  auth.py              # Admin authorization handlers (/admin pending, allow, deny, list, revoke)
  agent.py             # Agent request handlers, message routing, and Letta API integration
  client.py            # Shared Letta client instance and Letta API operations
  info.py              # Info command handlers (/privacy, /help, /about, /contact)
  notification.py      # Notification and scheduling tool management handlers
  response_handler.py  # Agent response stream processing and message formatting
  letta_sdk_extensions.py  # Extensions for missing Letta SDK methods (e.g., list_templates)
  queries/             # EdgeQL queries and auto-generated Python modules
    register_user.edgeql                    # Register new user
    is_registered.edgeql                    # Check if user is registered
    get_telegram_ids.edgeql                 # Get all telegram IDs
    create_auth_request.edgeql              # Create authorization request
    list_auth_requests_by_status.edgeql     # List auth requests by status
    resolve_auth_request.edgeql             # Resolve (approve/deny) auth request
    create_identity.edgeql                  # Create Letta identity record
    get_identity.edgeql                     # Get user's identity
    get_allowed_identity.edgeql             # Check if user has allowed identity
    set_selected_agent.edgeql               # Set user's selected agent
    revoke_user_access.edgeql               # Revoke user access
    *_async_edgeql.py                       # Auto-generated query modules
notes/                 # Markdown files for info commands (optional, at project root)
  welcome.md           # Welcome message (/start)
  privacy.md           # Privacy policy
  help.md              # Help documentation
  about.md             # About the bot
  contact.md           # Contact information
deploy/
  Dockerfile           # Multi-stage Python 3.13 image with uv
  docker-compose.yaml  # Production deployment with Traefik
```

**Deployment Structure**:

- Docker container runs as non-root user (`app`)
- Uses `uv` for dependency management in container
- Exposes port 80 for webhook
- Traefik labels for HTTPS with Let's Encrypt
- Connected to external `monitoring` network

## Configuration

Environment variables via `.env` (provide `.env.example`):

**Required**:

- `BOT_TOKEN` - Telegram bot token from BotFather
- `WEBHOOK_HOST` - Hostname for webhook (e.g., `ltgmc.online`)
- `LETTA_PROJECT_ID` - Letta project ID (UUID)
- `LETTA_API_KEY` - Letta API key for authentication

**Optional**:

- `WEBHOOK_PATH` - Path for webhook endpoint (default: empty string, e.g., `/bot`)
- `BACKEND_HOST` - Host to bind the webhook server (default: `0.0.0.0`)
- `BACKEND_PORT` - Port for the webhook server (default: `80`)
- `GEL_INSTANCE` - Gel/EdgeDB instance identifier (required for Gel storage)
- `GEL_SECRET_KEY` - Gel/EdgeDB authentication secret key (required for Gel storage)
- `SCHEDULER_URL` - Scheduler service base URL for schedule_message tool (delayed message delivery)
- `SCHEDULER_API_KEY` - Scheduler API key for schedule_message tool (delayed message delivery)
- `ADMIN_IDS` - Comma-separated list of Telegram user IDs with admin access (if not set, no admin commands available)
- `INFO_DIR` - Absolute path to directory containing info markdown files (default: `<project_root>/notes`)
- `LOGGING_LEVEL` - Logging verbosity level (default: `INFO`, options: DEBUG, INFO, WARNING, ERROR, CRITICAL)

## Deployment

**Production: Docker + docker-compose + Traefik**

The bot is deployed using Docker with Traefik as a reverse proxy for HTTPS webhook endpoints.

**Dockerfile** (`deploy/Dockerfile`):

- Base: `python:3.13-slim`
- Installs `uv` from official image
- Runs as non-root user `app`
- Working directory: `/app`
- Entry point: `uv run python letta_bot/main.py`

**docker-compose.yaml** (`deploy/docker-compose.yaml`):

- Service name: `letta-bot`
- Image: `letta-client-bot:latest`
- Container name: `letta-telegram-bot`
- Restart policy: `unless-stopped`
- Exposes port 80 (internal)
- Traefik configuration:
  - Router rule: `Host(${WEBHOOK_HOST}) && PathPrefix(${WEBHOOK_PATH})`
  - TLS enabled with Let's Encrypt (`lets-encrypt-ssl` resolver)
- Network: External `monitoring` network
- Volume: `bot-storage` for persistence

**Build and Deploy Commands**:

```bash
# Build Docker image
docker build -t letta-client-bot:latest -f deploy/Dockerfile .

# Start services
docker-compose -f deploy/docker-compose.yaml up -d

# View logs
docker-compose -f deploy/docker-compose.yaml logs -f

# Stop services
docker-compose -f deploy/docker-compose.yaml down
```

**Development Mode**:

- Run locally with polling: `uv run python letta_bot/main.py -p`
- With custom info directory: `INFO_DIR=/path/to/notes uv run python letta_bot/main.py -p`

**CLI Arguments**:

- `-p, --polling` - Enable polling mode instead of webhook

## Key Technical Considerations

**Identity ID Format:**
Use consistent identifier_key format: telegram user ID as-is. Letta generates the actual identity.id UUID.

**Agent Ownership Validation:**
Always verify agent belongs to user's identity before operations. Never trust client-provided agent IDs without checking.

**Error Messages:**
Be specific: "Agent not found" vs "Agent not found or you don't have access" - helps debugging while maintaining security.

**Tags for Agents:**
Recommend tagging all agents with `["telegram", "user:{telegram_id}"]` for additional filtering/analytics even beyond identity system.

## MarkdownV2 for Long Notes and Info Commands

When creating content for info commands (`/help`, `/privacy`, `/about`, `/contact`) stored in the `notes/` directory, understand that **Telegram MarkdownV2 is NOT standard Markdown**. Notes are loaded as raw text and sent directly to Telegram, so you must **manually write proper MarkdownV2 escaping** in the source `.md` files.

### Critical Differences from Standard Markdown

**Unsupported Features** (do NOT use these in notes):

1. **Headers** (`#`, `##`, etc.) - Use `*bold text*` instead
2. **Tables** (pipe-based) - Use code blocks with aligned text
3. **Standard lists** (`-`, `*`, `+`, `1.`) - Use Unicode bullets (•) or emoji
4. **Nested formatting** (`***text***`) - Cannot combine bold+italic

**Supported Features**:

- `*bold*` - Bold text
- `_italic_` - Italic text
- `__underline__` - Underlined text
- `~strikethrough~` - Strikethrough
- `` `code` `` - Inline code
- ` ```code block``` ` - Code blocks
- `[text](url)` - Links

### Special Character Escaping in Note Files

These 17 characters **must be escaped** with backslash in `.md` note files:

```
\ _ * [ ] ( ) ~ ` > # + - = | { } . !
```

**Examples:**

```markdown
Regular sentence ends with period\.
Price is $9\.99\!
Date range: 2024\-01\-15
Email: user@example\.com
Math: x \= y \+ 5
```

**Escaping in Links:**

```markdown
Visit [our site](https://example.com/) for info\.
```

**Line Breaks:**

- Single line break: Just use newline in file
- Paragraph break: Use blank line in file (converted to `\n\n` when loaded)

### Writing Note Files

**Structure example** (`notes/help.md`):

```markdown
_Welcome to Bot_

This bot helps you manage agents\. Here are the key features:

• Request agent access via /request_resource
• Send messages directly to your agent
• View privacy policy with /privacy

_Getting Started_

1\. Register with /start
2\. Request an agent
3\. Wait for admin approval
4\. Start chatting\!

Visit [documentation](https://docs.example.com/) for more details\.
```

**Key points:**

- Escape ALL periods, exclamation marks, hyphens, etc.
- Use `*bold*` instead of `# headers`
- Use `•` or emoji instead of `-` for lists
- Use plain newlines for line breaks (file I/O handles conversion)
- Escape underscores in commands: `/request\_resource`

### Common Pitfalls

1. **Forgetting to escape periods** - Most common error
   - Wrong: `This is a sentence.`
   - Right: `This is a sentence\.`

2. **Using markdown headers** - They render as literal `# Title`
   - Wrong: `## Section Title`
   - Right: `*Section Title*`

3. **Standard list syntax** - Renders as plain text with dashes
   - Wrong: `- Item one`
   - Right: `• Item one`

4. **Unescaped underscores in commands** - Triggers italic formatting
   - Wrong: `/request_resource`
   - Right: `/request\_resource`

5. **URLs without escaping** - Breaks link parsing
   - Wrong: `[link](http://example.com/)`
   - Right: `[link](http://example\.com/)`

### Testing Notes

Always test note rendering in Telegram before committing:

1. Start bot in polling mode: `uv run python letta_bot/main.py -p`
2. Send info command (e.g., `/help`)
3. Verify formatting renders correctly
4. Check for "can't parse entities" errors

### Reference

- Telegram MarkdownV2 docs: https://core.telegram.org/bots/api#markdownv2-style

## EdgeQL Quick Reference

**Database**: Gel is a graph-relational database. EdgeQL is its query language, blending object-oriented, graph, and relational concepts.

### Core Concepts

**Objects and Links (not Tables and Foreign Keys)**:

- Schema uses **object types** with **properties** and **links** (relations)
- Example:

  ```edgeql
  type Person {
    required name: str;
  }

  type Movie {
    required title: str;
    multi actors: Person;
  }
  ```

**Structured Results (not Flat Rows)**:

- Queries return nested objects, not flat row lists
- No need for explicit JOINs - use shapes to fetch related data
- Example:
  ```edgeql
  select Movie {
    title,
    actors: { name }
  }
  filter .title = "The Matrix"
  ```

**Composable and Strongly Typed**:

- Embed queries within queries (subqueries, nested mutations)
- Strongly typed - schema enforces consistency
- Shape expressions (curly braces) dictate result structure

### Syntax Patterns

**Data Retrieval**:

```edgeql
# Basic select with nested data
select Issue {
  number,
  status: { name },
  assignee: { firstname, lastname }
}
filter .status.name = "Open"
```

**Data Modification**:

```edgeql
# Insert
insert Person {
  name := "Alice"
}

# Nested insert with links
insert Movie {
  title := "The Matrix Resurrections",
  actors := (
    select Person
    filter .name in {"Keanu Reeves", "Carrie-Anne Moss"}
  )
}

# Update
update Person
filter .name = "Alice"
set {
  name := "Alice Smith"
}

# Delete
delete Person
filter .name = "Alice Smith"
```

**WITH Blocks (temporary views)**:

```edgeql
with
  active_users := select User filter .is_active
select active_users {
  firstname,
  friends: { firstname }
}
```

### Best Practices

1. **Embrace Object Modeling**: Model data with object types and links; avoid translating legacy relational schemas directly
2. **Favor Composability**: Use shapes and subqueries for readable, reusable query fragments
3. **Leverage Nested Fetching**: Fetch complex object graphs directly using shapes instead of manual joins
4. **Use Transactions**: Rely on transaction statements (`start transaction`, `commit`, `rollback`) for multi-step operations
5. **Consistent Typing**: Maintain clear, strict type definitions in schemas

- always use make check for mandatory pipeline
- we have development_scripts folder for this project scripting
