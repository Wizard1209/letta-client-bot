**CHANGELOG**

All notable changes to this project will be documented in this file.

**[Latest additions]**

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
• /request_identity command for requesting identity access independently
• Pending request validation to prevent duplicate identity requests
• /switch_agent command for switching between user's agents
• /notify command enabling agent communication tools: scheduled self-messaging for internal reminders and proactive user notifications

**Changed:**
• Info notes now use standard Markdown with automatic conversion to Telegram MarkdownV2 (same pipeline as agent responses, eliminates need for manual escaping)
• Reworked message formatting architecture from aiogram utilities to manual MarkdownV2 strings for better rendering control
• Updated to Letta SDK v1.0 with proper async streaming support for agent message responses
• Agent responses now render with proper Telegram-compatible markdown formatting using telegramify-markdown library
• Improved message splitting with intelligent boundary detection at newlines and spaces
• Updated help documentation with /request_identity workflow
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
