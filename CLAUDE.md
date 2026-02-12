# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

**See also**: @CONTRIBUTION.md for setup instructions, planned features, technical TODOs, and detailed policies.

## Project Overview

A production-ready multi-user Telegram bot with **tag-based per-user agent isolation**. Unlike the official letta-telegram bot (chat-scoped for single-user use), this bot is user-scoped and designed for larger client deployments with custom authentication.

## High-Level Architecture Summary

### Core Concept

Multi-user Telegram bot that manages per-user Letta agents through a tag-based authorization system. Users request agents from available templates, admins approve requests, and the bot handles agent provisioning with identity tags.

### Key Principles

- Templates fetched from Letta API (no local storage)
- One pending request per user (prevents spam)

## Core Architecture

### Tag-Based Identity System

- **Single API key with per-user isolation**: Server manages one Letta API key; each Telegram user is associated with agents via tags
- **Flow**: `Telegram User → Local Identity Record → Agents with identity-tg-{telegram_id} tags`
- **Tag format**: Agents use `identity-tg-{telegram_id}` for access control, `owner-tg-{telegram_id}` for ownership, `creator-tg-{telegram_id}` for creator tracking
- **No external identity API**: Identity records are local (database only), no Letta Identity API calls needed
- **Agent operations** filter by `identity-tg-{telegram_id}` tag; access validation checks tag presence on agent
- **Selected agent tracking**: Each local identity stores `selected_agent` ID for message routing; auto-selects oldest agent if none set

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
- **Identity**: Local identity record (identifier_key, selected_agent) — no Letta identity UUID stored
- **AuthorizationRequest**: Access requests with status tracking (pending/allowed/denied)

**Generated Query Modules**:

- Auto-generated from `.edgeql` files in `letta_bot/queries/`
- Each `.edgeql` file generates a corresponding Python module with type-safe async functions
- Examples: `upsert_user`, `create_auth_request`, `get_identity`, `set_selected_agent`

### Middleware System

The bot uses **Aiogram's middleware system** for dependency injection and access control. Middlewares are called before handlers and can inject data, perform checks, or block handler execution.

**gel_client injection**: Passed via `Dispatcher(gel_client=gel_client)` workflow_data, available as `data['gel_client']` in all middlewares.

**UserMiddleware** (`middlewares.py`):

- Registers/updates users in database on every interaction
- Skips events without `from_user` (channel posts, service messages) — optional analytics
- Uses cached `upsert_user` query (12-hour TTL) to minimize database calls
- Injects `user` object into handler data

**IdentityMiddleware** (`middlewares.py`):

- Triggered by `flags={'require_identity': True}`
- **Business logic errors** (raise exceptions):
  - Unsupported event type → `TypeError`
  - Missing `from_user` → `ValueError`
  - Identity not found for authorized user → `RuntimeError`
- **Authorization** (notify + block):
  - User not authorized → `❌ No access — use /new or /access to request`
- Injects `identity: GetIdentityResult` into handler data

**MediaGroupMiddleware** (`middlewares.py`):

- Rejects Telegram media groups (albums) with a single response message
- Prevents duplicate error messages when user sends multiple files at once
- Configurable predicate to filter which events trigger rejection
- Currently registered for documents and photos in `setup_middlewares()`

**RateLimitMiddleware** (`middlewares.py`):

- Generic rate limiter with configurable key function and predicate
- Supports per-user, per-chat, or custom rate limiting strategies
- Available for use but not currently applied to any handlers

**AgentMiddleware** (`middlewares.py`):

- Triggered by `flags={'require_agent': True}` (requires `require_identity` too)
- **Validation flow**:
  1. If `selected_agent` exists: validate user has access via `identity-tg-{telegram_id}` tag
  2. If `NotFoundError`: agent deleted, trigger reselect
  3. If user's identity tag not in agent's tags: trigger reselect
  4. If no `selected_agent` or reselect needed: auto-select oldest agent via `get_oldest_agent_by_user()`
  5. Save new selection to database via `set_selected_agent_query()`
- **User notifications**:
  - First-time: `🤖 Auto-selected assistant *{name}* — you can write now`
  - Re-selection: `🔄 Switched to *{name}* (previous unavailable)`
  - No agents: `❌ No assistants yet — use /new to request one` (blocks handler)
- Injects `agent_id: str` into handler data

**Marking Handlers that Require Identity and/or Agent**:

Handlers can use flags to specify their requirements:

```python
# Handler requiring only identity (no agent needed)
@router.message(Command('switch'), flags={'require_identity': True})
async def switch(message: Message, identity: GetIdentityResult) -> None:
    # Handler receives identity as injected parameter
    pass

# Handler requiring both identity and agent
@router.message(
    Command('current'), flags={'require_identity': True, 'require_agent': True}
)
async def current(message: Message, agent_id: str) -> None:
    # Handler receives validated agent_id as injected parameter
    # Note: identity is also available if needed
    pass

# Callback query handler requiring both identity and agent
@router.callback_query(
    NotifyCallback.filter(),
    flags={'require_identity': True, 'require_agent': True}
)
async def handle_notify_callback(
    callback: CallbackQuery,
    callback_data: NotifyCallback,
    agent_id: str,
) -> None:
    # Handler receives validated agent_id
    pass

# Message handler (catch-all) requiring both identity and agent
@router.message(flags={'require_identity': True, 'require_agent': True})
async def message_handler(message: Message, bot: Bot, agent_id: str) -> None:
    # Handler receives validated agent_id
    # Agent validation and auto-selection handled by middleware
    pass
```

**Key Points**:

- `require_identity` flag: injects `identity: GetIdentityResult` parameter
- `require_agent` flag: injects `agent_id: str` parameter (requires `require_identity` too)
- `require_agent` handles all agent validation and auto-selection logic
- No need to manually check `identity.selected_agent` or call `get_default_agent()` - middleware handles this
- Middleware setup via `setup_middlewares(dp, gel_client)` in `main.py`

**Creating Custom Middlewares**:

Aiogram middlewares inherit from `BaseMiddleware` and implement `__call__` method:

```python
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
from collections.abc import Awaitable, Callable

class CustomMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, object]], Awaitable[object]],
        event: TelegramObject,
        data: dict[str, object],
    ) -> object | None:
        # Pre-processing: inject data, perform checks
        data['custom_key'] = 'custom_value'

        # Optional: check conditions and block handler
        if some_condition:
            await event.answer('Access denied')
            return None  # Block handler execution

        # Call handler
        result = await handler(event, data)

        # Post-processing (optional)
        # ... do something after handler

        return result
```

**Middleware Types**:

- **Outer middleware**: Runs before inner middleware and filters
  - Use: `dp.message.outer_middleware.register(CustomMiddleware())`
  - Example: `UserMiddleware` (registers users)
- **Inner middleware**: Runs after outer middleware but before handlers
  - Use: `dp.message.middleware(CustomMiddleware())`
  - Example: `IdentityMiddleware` (checks identity access), `AgentMiddleware` (validates agent)

**Registration Order** (`setup_middlewares(dp)`):

```python
# gel_client injected via Dispatcher workflow_data:
# dp = Dispatcher(gel_client=gel_client)

# 1. UserMiddleware (outer) - registers/updates users
dp.message.outer_middleware.register(UserMiddleware())
dp.callback_query.outer_middleware.register(UserMiddleware())

# 2. MediaGroupMiddleware (inner) - rejects albums for files/photos
dp.message.middleware(MediaGroupMiddleware(...))

# 3. IdentityMiddleware (inner) - checks identity authorization
dp.message.middleware(IdentityMiddleware())
dp.callback_query.middleware(IdentityMiddleware())

# 4. AgentMiddleware (inner) - validates/selects agent
dp.message.middleware(AgentMiddleware())
dp.callback_query.middleware(AgentMiddleware())
```

### Filters

The bot uses **Aiogram's filter system** for access control. Filters determine whether a handler should execute based on specific conditions. Unlike middleware, filters are declarative and specific to individual handlers.

**AdminOnlyFilter** (`filters.py`):

- Magic filter that restricts handler execution to admin users only
- Implementation: `MagicData(F.event_from_user.id.in_(CONFIG.admin_ids))`
- Checks if `event.from_user.id` is in the list of configured admin IDs
- If `CONFIG.admin_ids` is `None`, filter always fails (no admins configured)

**Usage Pattern**:

```python
from letta_bot.filters import AdminOnlyFilter

# Apply filter to command handler
@router.message(Command('pending'), AdminOnlyFilter)
async def pending(message: Message, gel_client: AsyncIOExecutor) -> None:
    # Only admins can access this handler
    pass
```

**Admin Commands Using This Filter**:

- `/pending` - View pending authorization requests
- `/allow <request_uuid>` - Approve authorization request
- `/deny <request_uuid> [reason]` - Deny authorization request with optional reason
- `/revoke <telegram_id>` - Revoke user's identity access
- `/users` - List all users with their allowed resources

**Key Points**:

- Filter automatically blocks non-admin users from accessing admin commands
- No error message sent to non-admin users (handler simply doesn't execute)
- Admin IDs must be configured via `ADMIN_IDS` environment variable (comma-separated list)
- If no admin IDs configured, admin commands are inaccessible to everyone

**Creating Custom Filters**:

Aiogram supports multiple filter types:

**1. Magic Filters (Recommended for simple conditions)**:

Using Aiogram's `F` (magic filter) for concise, readable conditions:

```python
from aiogram import F
from aiogram.filters.magic_data import MagicData

# Check user ID
UserIsJohn = MagicData(F.event_from_user.id == 12345)

# Check multiple IDs
PremiumUsersFilter = MagicData(F.event_from_user.id.in_([123, 456, 789]))

# Check message text pattern
HasKeywordFilter = MagicData(F.message.text.contains('keyword'))

# Combine conditions with & (AND) and | (OR)
SpecialFilter = MagicData(
    (F.event_from_user.id == 123) & (F.message.text.startswith('/'))
)
```

**2. Custom Filter Classes (For complex logic)**:

```python
from aiogram.filters import Filter
from aiogram.types import Message

class HasAttachmentFilter(Filter):
    async def __call__(self, message: Message) -> bool:
        # Return True if handler should execute
        return bool(
            message.photo
            or message.document
            or message.video
            or message.audio
        )

# Usage
@router.message(HasAttachmentFilter())
async def handle_attachment(message: Message) -> None:
    pass
```

**3. Filter with Data Injection**:

Filters can inject data into handlers by returning a dict:

```python
from aiogram.filters import Filter
from aiogram.types import Message

class ExtractMentionFilter(Filter):
    async def __call__(self, message: Message) -> bool | dict[str, object]:
        if not message.entities:
            return False

        for entity in message.entities:
            if entity.type == 'mention':
                mention = message.text[entity.offset:entity.offset + entity.length]
                return {'mentioned_user': mention}

        return False

# Handler receives injected data
@router.message(ExtractMentionFilter())
async def handle_mention(message: Message, mentioned_user: str) -> None:
    await message.answer(f'You mentioned: {mentioned_user}')
```

**Filter vs Middleware Decision**:

- **Use Filter when**: Condition is specific to a handler (e.g., admin-only command)
- **Use Middleware when**: Logic applies to many handlers (e.g., database injection, identity checks)
- **Combine both**: Middleware for common setup, filters for specific conditions

### Authorization Flow

**Phase 1: User Registration**

- User interacts with bot (any message or callback)
- UserMiddleware automatically registers/updates user in database:
  - Extracts user data from Telegram event (telegram_id, username, first_name, etc.)
  - Performs upsert operation: inserts new user or updates existing user
  - Uses 5-minute cache to avoid redundant database calls
- User sends `/start` command to view welcome message from `notes/welcome.md`
- No manual registration required - all users are automatically tracked

**Phase 2: Resource Request**

- **Identity-only request**: User runs `/access` to request general bot access (identity only, no assistant capabilities)
- **Agent request**: User runs `/new` to see available agent templates
- User selects template from inline keyboard
- System creates authorization requests:
  - Identity access request (if user doesn't have one) - resource_type: `ACCESS_IDENTITY`
  - Agent creation request for selected template - resource_type: `CREATE_AGENT_FROM_TEMPLATE`
- System prevents duplicate pending requests per user per resource type
- Admins receive notification via bot message

**Phase 3: Admin Approval**

- Admin views pending requests: `/pending`
  - Shows user details, request UUID, resource type, and resource ID
  - For each request displays quick approve command: `/allow <request_uuid>`
- Admin approves request: `/allow <request_uuid>`
  - **Identity requests**: Creates local identity record with `tg-{telegram_id}` identifier_key (no Letta API call)
  - **Agent requests**: Creates agent from template with `identity-tg-{telegram_id}`, `owner-tg-{telegram_id}`, and `creator-tg-{telegram_id}` tags
  - User receives approval notification
- Admin denies request: `/deny <request_uuid> [reason]`
  - Updates request status to denied
  - User receives notification with optional reason
  - User can submit new request after denial

**Phase 4: Message Routing and Response Processing**

- Authorized users send messages to bot
- **Message content processing** (builds multimodal content parts):
  - Text: plain text, quotes, replies, captions
  - Voice/audio: transcribed via external service, wrapped in XML tags
  - **Images**: downloaded from Telegram, encoded to base64, sent as Letta image content parts (highest resolution selected)
  - **Documents**: validated by type/size, uploaded to per-agent Letta folder, processed asynchronously with status polling
  - Unsupported: video and stickers notify user, don't block message
- **Document processing** (`documents.py`):
  - Accepts any file type (no MIME type restrictions)
  - Size limit: ~10MB (Letta API constraint)
  - Per-user concurrency control via `FileProcessingTracker` (one upload at a time per user)
  - Media groups (albums) rejected by `MediaGroupMiddleware`
  - Files uploaded to agent-specific folders (`uploads-{agent_id}`) and indexed for RAG
  - Auto-attaches `file_handling` memory block to agent on first file upload (teaches agent how to respond to files)
- System routes messages to user's selected agent (auto-selects oldest agent if none set)
- Bot streams agent responses via `client.agents.messages.stream()`
- **Response handler** (`response_handler.py`) processes stream events:
  - **assistant_message**: Main agent response converted to Telegram entities via `md_tg` module
  - **reasoning_message**: Internal agent reasoning (italic header, expandable blockquote formatting)
  - **tool_call_message**: Tool execution details (parsed from JSON arguments)
  - **ping**: Progressive heartbeat indicator (displays "⏳", "⏳⏳", "⏳⏳⏳", etc., updating same message)
  - **system_alert**: Informational messages from Letta (displayed as info text)
- **Specialized tool formatting** (consistent style with emoji, italic headers, bullet lists):
  - `archival_memory_insert`: "💾 Storing in archival memory..." with tags and markdown content
  - `archival_memory_search`: "🔍 Searching archival memory..." with query, date range, tags, and top_k limit
  - `conversation_search`: "🔍 Searching conversation history..." with query, date range, roles filter, and result limit
  - `memory` (with subcommands): Different operations formatted appropriately
    - `insert`: "📝 Updating memory..." with new content (plain text)
    - `str_replace`: "🔧 Modifying memory block..." with unified diff visualization
    - `rename`: "🏷️ Updating memory description..." or "📂 Renaming memory block..."
    - `delete`: "🧹 Removing a memory block..." with path
    - `create`: "📝 Creating new memory block..." with path, description, and optional markdown content
  - `memory_insert` (legacy): "📝 Updating memory..." with new content (plain text)
  - `memory_replace` (legacy): "🔧 Modifying memory block..." with unified diff
  - `run_code`: "⚙️ Executing code..." with language and syntax-highlighted code block
  - `web_search`: "🔍 Let me search for this..." with query, result count, category, domain filters, date range (formatted), and location
  - `fetch_webpage`: "🌐 Fetching webpage..." with URL
  - `open_files`: "📂 Opening files..." with file list and line ranges
  - `grep_files`: "🔍 Searching in files..." with pattern, filter, and context lines
  - `semantic_search_files`: "🔍 Searching by meaning..." with query and limit
  - `schedule_message`: "⏱️ Setting self activation..." with human-readable delay/cron and message
  - `list_scheduled_messages`: "📋 Checking scheduled messages..."
  - `delete_scheduled_message`: "🗑️ Canceling scheduled message..." with schedule ID
  - `notify_via_telegram`: "📲 Sending message..." with owner-only indicator
  - Generic tools: "🔧 Using tool..." with tool name and JSON arguments
- **Message formatting pipeline**:
  - Agent responses: Standard Markdown → `markdown_to_telegram()` → Telegram entities
  - Info notes: Standard Markdown files → same conversion pipeline
  - Tool outputs: Manual MarkdownV2 strings with `_escape_markdown_v2()` helper
  - Long messages: Split using `split_markdown_v2()` with intelligent boundary detection (preserves code blocks and formatting across chunks)
  - Date/time formatting: ISO datetime strings converted to readable format via `_format_datetime()` (e.g., "Jan 01, 2024" or "Jan 01, 2024 10:30")
- **Error handling**: Failed message sends logged with `LOGGER.warning()` and generic error shown to user ("❌ Something went wrong")
- Real-time message streaming with stateful ping indicator

**Phase 5: Agent Management**

- **Switch agents**: `/switch` command lists user's agents with checkmark on selected agent
- User selects agent from inline keyboard
- System updates `selected_agent` in database
- All subsequent messages route to newly selected agent

**Phase 6: Access Management**

- **List active users**: `/users`
  - Groups users by telegram_id
  - Shows all allowed resources per user with resource type and resource ID
  - Displays user information (full name, username, telegram ID)
- **Revoke access**: `/revoke <telegram_id>`
  - Revokes only identity access (sets identity request status to denied)
  - User receives revocation notification
  - User can re-request access after revocation

## Development Commands

See @CONTRIBUTION.md for complete development workflows.

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

## Devscripts

Development scripts for Letta API operations live in `devscripts/`. Scripts use **sync Letta client** (not async) and `CONFIG` from `letta_bot.config` via `bootstrap.py`.

```bash
uv run python -m devscripts.delete_agents agent-uuid1 agent-uuid2
uv run python -m devscripts.folders list
uv run python -m devscripts.test_folder_workflow        # Test folder attach/upload/detach cycle
uv run python -m devscripts.run_tool -l                 # List tools
uv run python -m devscripts.run_tool -a <agent-id> notify_via_telegram "Hello"
uv run python -m devscripts.list_users                  # List users and their agents via tags
uv run python -m devscripts.migrate_identities_to_tags  # Migrate agents from identity API to tags
uv run python -m devscripts.migrate_identities_to_tags --dry-run  # Preview migration
```

Writing conventions and bootstrap API documented in `.claude/rules/devscripts.md` (loads automatically when editing scripts).

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

The project maintains a changelog at `notes/changelog.md` in **standard Markdown format**. The file is automatically converted to Telegram MarkdownV2 when displayed to users. When updating the changelog:

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

- Use `**Added:**` for new features and capabilities
- Use `**Changed:**` for improvements to existing features
- Generally avoid `**Removed:**` section - focus on what's new and improved
- Use standard Markdown syntax (not MarkdownV2 escaping)

**Example:**

```markdown
**Added:**
- Progressive "working" indicator that updates in real-time during agent processing

**Changed:**
- Agent responses now render with proper Telegram-compatible markdown formatting
```

**Versioning Policy:**

- Keep `**[Latest additions]**` section at the top as a staging area for unreleased changes
- When releasing a version, move content from `[Latest additions]` to a new versioned section (e.g., `**[1.1.0] - 2025-12-09**`)
- Leave `[Latest additions]` empty after release to collect future changes
- Update version in three places: `notes/changelog.md`, `pyproject.toml`, `letta_bot/__init__.py`

## Adding New Commands

When adding a new bot command, update these locations:

1. **`notes/help.md`** - User-facing help documentation
2. **`notes/about.md`** - About page (if command changes "How It Works" flow)
3. **`deploy/botfather_commands.txt`** - BotFather command list for Telegram menu

## Project Structure

Current module organization:

```
letta_bot/
  main.py              # Bot entry point with webhook/polling modes, /start handler
  config.py            # Configuration management (Pydantic settings)
  middlewares.py       # Middleware for database client injection, user registration, and identity checks
  filters.py           # Filters for admin access control
  auth.py              # All authorization: user requests (/access, /new, /attach) and admin commands (/pending, /allow, /deny, /users, /revoke)
  agent.py             # Agent operations: /switch, /current, /context, and message routing to Letta agents
  client.py            # Shared Letta client instance and Letta API operations (agent, folder, tool management)
  info.py              # Info command handlers (/privacy, /help, /about, /contact)
  tools.py             # Tool management: attach/detach/configure agent tools (/notify for proactive mode)
  broadcast.py         # Bot-level messaging: admin notifications, user broadcasts
  response_handler.py  # Agent response stream processing and message formatting
  letta_sdk_extensions.py  # Extensions for missing Letta SDK methods (e.g., list_templates)
  images.py            # Image processing: download Telegram photos, convert to base64 for Letta multimodal API
  documents.py         # Document processing: download Telegram files, upload to Letta folders for RAG
  transcription.py     # Audio transcription: OpenAI Whisper and ElevenLabs Scribe engines for voice/audio messages
  utils.py             # Utility functions (async cache decorator with TTL, UUID validation)
  queries/             # EdgeQL queries and auto-generated Python modules
    upsert_user.edgeql                      # Register/update user (upsert on telegram_id)
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
md_tg/               # Markdown to Telegram entities converter
  __init__.py        # Public API: markdown_to_telegram()
  config.py          # MarkdownConfig with emoji settings
  converter.py       # AST-based chunking and conversion logic
  renderer.py        # TelegramRenderer - mistune renderer for entities
  utils.py           # UTF-16 length utilities
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
- `ADMIN_IDS` - Comma-separated list of Telegram user IDs with admin access (if not set, no admin commands available)
- `INFO_DIR` - Absolute path to directory containing info markdown files (default: `<project_root>/notes`)
- `LOGGING_LEVEL` - Logging verbosity level (default: `INFO`, options: DEBUG, INFO, WARNING, ERROR, CRITICAL)
- `OPENAI_API_KEY` - OpenAI API key for Whisper transcription (voice/audio messages)
- `WHISPER_MODEL` - OpenAI Whisper model (default: `gpt-4o-mini-transcribe`)
- `ELEVENLABS_API_KEY` - ElevenLabs API key for Scribe transcription (prioritized over OpenAI if set)
- `ELEVENLABS_STT_MODEL` - ElevenLabs Scribe model (default: `scribe_v2`)

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

**Tag Format:**
- Access control: `identity-tg-{telegram_id}` — grants user access to agent
- Ownership: `owner-tg-{telegram_id}` — identifies who owns the agent
- Creator: `creator-tg-{telegram_id}` — identifies who created the agent
- Local identifier: `tg-{telegram_id}` stored in database Identity.identifier_key

**Agent Access Validation:**
Always verify user has access via `identity-tg-{telegram_id}` tag before operations. Never trust client-provided agent IDs without checking tags.

**Error Messages:**
Be specific: "Agent not found" vs "Agent not found or you don't have access" - helps debugging while maintaining security.

## Error Handling Policy

**Never silently skip.** Three categories:

1. **Infrastructure** (DB client, Letta client, API keys) → Don't handle, let it crash early
2. **Business logic** (missing `from_user`, unexpected empty query results) → Raise error for common handler
3. **Authorization** (user not allowed, no agents) → Notify user + block handler

```python
# Infrastructure - assume exists, crash if not
gel_client: AsyncIOExecutor = data['gel_client']

# Business logic - raise error
if not event.from_user:
    raise ValueError('Event missing from_user context')

# Authorization - notify and block
await event.answer('You need to request bot access first')
return None
```

### External API Errors (Letta, Telegram, etc.)

**Don't wrap in try/except** unless you have specific recovery logic. General API errors should propagate to common error handling:

- Network errors (timeout, DNS, connection refused)
- Authentication errors (invalid/expired API key)
- Server errors (5xx responses)
- Rate limiting (429)
- Invalid configuration (wrong project ID, missing resources)

**DO handle specifically:**
- Empty results that need UX feedback (e.g., no templates → show message)
- Known error codes with user-actionable recovery
- Partial failures where some data can still be used

## Logging Policy

| Level | Use |
|-------|-----|
| DEBUG | _(Reserved)_ |
| INFO | Major business events outside agent interaction |
| WARNING | Unexpected behavior from code logic |
| ERROR | Recoverable errors |
| CRITICAL | Non-recoverable errors affecting availability |

**Rules**: Never log secrets. Always include context (telegram_id, request IDs). Use `logging.getLogger(__name__)`.

## Formatting Info Notes (notes/ directory)

Info command files (`/help`, `/privacy`, `/about`, `/contact`, `/welcome`, `/changelog`) are stored in the `notes/` directory using **standard Markdown**. Files are automatically converted to Telegram entities via `md_tg` module when sent to users.

### Formatting Rules

**Write standard Markdown - NO manual escaping needed:**

- Regular punctuation (periods, exclamation marks, hyphens, parentheses) - use as-is
- Commands like `/command` - write normally, no underscore escaping
- URLs in links - use standard format `[text](https://example.com/)`
- Math expressions - write naturally: `x = y + 5`

**Section Headers:**

- Use `**Bold Text**` for section titles (NOT `#` or `##`)
- Example: `**Available Commands**`

**Lists:**

- Use bullet symbol `•` for unordered lists (NOT `-`, `*`, or `+`)
- Example:
  ```markdown
  • First item
  • Second item
  • Third item
  ```

**Formatting Styles:**

- Bold: `**text**`
- Italic: `*text*`
- Inline code: `` `code` ``
- Code blocks: ` ```code block``` `
- Links: `[text](url)`

**Visual Elements:**

- Emoji: Use emoji for visual emphasis (✅, 🔒, 🐛, 💡, etc.)
- Horizontal separators: Use line of en-dashes `──────────────────────────────`

**Line Breaks:**

- Single line break: Just use newline in file
- Paragraph break: Use blank line

### Examples from Existing Files

**Section with list** (`help.md`):

```markdown
**Available Commands**

**Information**
/help - Display this help message
/privacy - View privacy policy and data handling practices
/about - Information about this bot
```

**Bullet list with emoji** (`welcome.md`):

```markdown
This bot connects you with a modern stateful AI assistant that:
• Remembers your conversations and preferences
• Learns from interactions and adapts to you
• Grows smarter over time through continuous memory
```

**Section with separator** (`contact.md`):

```markdown
**Contact & Support**

We use GitHub Issues as our primary communication channel.

──────────────────────────────

We're committed to keeping this bot flexible!
```

**Link formatting** (`privacy.md`):

```markdown
View Letta's privacy policy: [https://www.letta.com/privacy-policy](https://www.letta.com/privacy-policy)
```

### Testing Notes

Always test note rendering in Telegram:

1. Start bot: `uv run python letta_bot/main.py -p`
2. Send command (e.g., `/help`)
3. Verify formatting renders correctly
4. Check for parsing errors

### Key Points

- **Standard Markdown only** - write naturally, no manual escaping
- **Use `**bold**` for headers** - not `#` syntax
- **Use `•` for lists** - not `-` or `*`
- **Automatic conversion** - `markdown_to_telegram()` converts to Telegram entities via `md_tg` module
- **Same pipeline as agent responses** - info notes use identical formatting as agent message responses

## EdgeQL

Gel is a graph-relational database using EdgeQL (object-oriented query language). Queries live in `letta_bot/queries/*.edgeql` and auto-generate Python modules.

```bash
uv run gel-py   # Regenerate Python modules after modifying .edgeql files
```

EdgeQL syntax reference and patterns documented in `.claude/rules/database.md` (loads automatically when editing queries).

## Letta Python SDK API Reference

**Source of truth**: Local SDK at `.venv/lib/python3.13/site-packages/letta_client/`

- `resources/` - available client methods
- `types/` - response/request types

**Tag-based agent listing pattern**:

```python
# List agents accessible to a user
identity_tag = f'identity-tg-{telegram_id}'
async for agent in client.agents.list(tags=[identity_tag]):
    print(agent.name)

# Check if user has access to specific agent
agent = await client.agents.retrieve(agent_id=agent_id, include=['agent.tags'])
has_access = agent.tags and identity_tag in agent.tags
```

## External References

- **Letta Python SDK Changelog**: https://github.com/letta-ai/letta-python/blob/main/CHANGELOG.md
- **Letta Docs**: https://docs.letta.com/
