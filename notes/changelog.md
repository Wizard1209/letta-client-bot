**CHANGELOG**

All notable changes to this project will be documented in this file.

**[Latest additions]**

**Added:**
• Image support: send photos to your assistant and it can see and analyze them (uses Letta's multimodal API with base64 encoding)
• Document upload: send files (PDF, code, text, markdown, configs) to your assistant for analysis and RAG-indexed search (~10MB limit)

**Changed:**
• Renamed `/botaccess` → `/access` with clearer description emphasizing this grants general bot access only (identity), not assistant capabilities
• Album uploads now rejected with clear "send one file at a time" message
• Reasoning messages now display in collapsible blockquote (tap to expand full reasoning)
• Message formatting migrated to native Telegram entities via custom md_tg module (replaces telegramify-markdown library)

**[1.1.0] - 2025-12-09**

**Added:**
• /attach command to request access to an existing assistant by ID
• Agent ownership system with owner-based approval for access requests
• /current command to view current assistant's information and memory usage statistics
• /context command to see detailed context window breakdown (how tokens are distributed across message history, core memory, archival memory, and system prompts)
• Multi-user proactive notifications: notify_via_telegram now sends to all users attached to an agent, with optional owner_only mode
• /notify shows 🔄 Update button to upgrade proactive messaging protocol to latest version

**Changed:**
• Renamed `/newassistant` command to `/new` for brevity
• Agent creation now tags agents with owner and creator information

**[1.0.0] - 2025-11-29**

**Added:**
• Support for voice and audio messages
• Rich formatting for all core Letta tools (memory operations, archival/conversation search, code execution, web search, notifications, and scheduling)
• Timestamp scheduling with X-Schedule-At header support for absolute time scheduling
• Expanded proactive messaging protocol memory block with scheduling patterns, timezone handling, and recurring notifications
• Rich formatting for notification and scheduling tools (schedule_message shows human-readable timing and message content, notify_via_telegram displays delivery status)
• Unified diff visualization for memory modifications (shows color-coded diffs of exactly what changed instead of old/new text blocks)
• Rich formatting for web search and webpage fetching operations (displays query parameters, filters, domain restrictions, date ranges)
• Support for new memory tool subcommands with specialized formatting (insert, str_replace, rename operations)
• Progressive "working" indicator that updates in real-time during agent processing (shows increasing hourglass symbols while waiting)
• New unified response handler module consolidating stream event processing and message formatting
• User notification system for authorization events (approval, denial, revocation)
• /access command for requesting general bot access (identity only, no assistant capabilities)
• Pending request validation to prevent duplicate identity requests
• /switch command for switching between user's assistants
• /notify command with inline buttons for enabling proactive assistant behavior (reminders, follow-ups, notifications)

**Changed:**
• Simplified command names: `/switch_assistant` → `/switch`, `/request_identity` → `/access`
• Admin commands now use separate commands (`/pending`, `/allow`, `/deny`, `/revoke`, `/users`) instead of `/admin` subcommands
• Template selection now shows vertical button layout with confirmation message after selection
• Assistant switching now updates the keyboard in-place to show current selection
• /notify command uses inline Enable/Disable buttons instead of subcommands
• Info notes now use standard Markdown with automatic conversion to Telegram MarkdownV2 (same pipeline as agent responses, eliminates need for manual escaping)
• Reworked message formatting architecture from aiogram utilities to manual MarkdownV2 strings for better rendering control
• Updated to Letta SDK v1.0 with proper async streaming support for agent message responses
• Agent responses now render with proper Telegram-compatible markdown formatting using telegramify-markdown library
• Improved message splitting with intelligent boundary detection at newlines and spaces
• Centralized Letta client operations into dedicated client module
• Improved message rendering to properly preserve Markdown formatting when splitting long messages (fixes issue where code blocks and formatting would break across message boundaries)

**[0.1.0] - 2025-11-03**

**Added:**
• Multi-user Telegram bot with Letta identity system integration
• Per-user agent isolation using identity_ids
• Template-based agent provisioning from Letta API
• Authorization flow: user registration, resource requests, admin approval/denial
• Admin commands: pending, allow, deny, list, revoke
• Info commands: privacy, help, about, contact (markdown file support)
• Real-time message streaming with formatted responses
• Gel/EdgeDB storage with auto-generated EdgeQL query modules
• Docker deployment with Traefik reverse proxy
• aiogram 3.x with MarkdownV2 formatting utilities
• uv dependency management, ruff/mypy tooling

**Fixed:**
• Message length handling for Telegram 4096 character limit
• MarkdownV2 escaping via aiogram formatting
• Callback query error handling
