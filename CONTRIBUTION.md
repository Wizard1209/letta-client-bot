# Contribution guide

## Weird solutions

### Message sending

Telegram can't parse '.' without escaping and other characters so I had to wrap everything inside aiogram formating

## Planned features

### High Priority

- `/status` command (identity and agent info)
- Agent selection per chat
- Add typing status when agent producing message

### Medium Priority

- **Voice/audio transcription** (OpenAI Whisper API)
  - Detect voice/audio messages in Telegram
  - Download and send to Whisper API
  - Process transcribed text as regular message
  - Optionally show transcription to user
- Images support
- LaTeX support
- Memory block viewing and editing
- Conversation management
- User preferences and custom names
- Agent tags for filtering
- Usage analytics per identity
- Bulk admin operations
- Add message editing support

## TODO

Local TODOs kept in code

- Notify end user on: waiting for approval, approved, the rest
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
BOT_TOKEN, WEBHOOK_HOST, LETTA_PROJECT, LETTA_API_KEY
GEL_INSTANCE, GEL_SECRET_KEY (if using Gel Cloud)
```

**Prerequisites**: Traefik with `lets-encrypt-ssl` resolver, `monitoring_monitoring` network exists, DNS configured for `WEBHOOK_HOST`.

## Logging Policy

### DEBUG
*(Reserved for future use)*

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
