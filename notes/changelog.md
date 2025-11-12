*CHANGELOG*

All notable changes to this project will be documented in this file\.

*\[Latest additions\]*

*Added:*
• Progressive "working" indicator that updates in real\-time during agent processing \(shows increasing hourglass symbols while waiting\)
• New unified response handler module consolidating stream event processing and message formatting
• User notification system for authorization events \(approval, denial, revocation\)
• /request\_identity command for requesting identity access independently
• Pending request validation to prevent duplicate identity requests
• /switch\_agent command for switching between user's agents
• /notify command for managing agent\-to\-user proactive notifications via Telegram with automatic tool registration

*Changed:*
• Agent responses now render with proper Telegram\-compatible markdown formatting using telegramify\-markdown library
• Improved message splitting with intelligent boundary detection at newlines and spaces
• Updated help documentation with /request\_identity workflow
• Centralized Letta client operations into dedicated client module
• Changed: Improved message rendering to properly preserve Markdown formatting when splitting long messages (fixes issue where code blocks and formatting would break across message
  boundaries)

*\[0\.1\.0\] \- 2025\-11\-03*

*Added:*
• Multi\-user Telegram bot with Letta identity system integration
• Per\-user agent isolation using identity\_ids
• Template\-based agent provisioning from Letta API
• Authorization flow: user registration, resource requests, admin approval/denial
• Admin commands: pending, allow, deny, list, revoke
• Info commands: privacy, help, about, contact \(markdown file support\)
• Real\-time message streaming with formatted responses
• Gel/EdgeDB storage with auto\-generated EdgeQL query modules
• Docker deployment with Traefik reverse proxy
• aiogram 3\.x with MarkdownV2 formatting utilities
• uv dependency management, ruff/mypy tooling

*Fixed:*
• Message length handling for Telegram 4096 character limit
• MarkdownV2 escaping via aiogram formatting
• Callback query error handling
