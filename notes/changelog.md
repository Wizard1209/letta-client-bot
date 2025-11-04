*CHANGELOG*

All notable changes to this project will be documented in this file\.

*\[Unreleased\]*

*Added:*
• User notification system for authorization events \(approval, denial, revocation\)
• Error handling for notification delivery with logging

*Changed:*
• Updated help documentation formatting

*\[0\.1\.0\] \- 2025\-01\-03*

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

──────────────────────────────

For full changelog, see CHANGELOG\.md in the repository root\.
