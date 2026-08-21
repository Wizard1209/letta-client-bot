---
paths:
  - "notes/changelog.md"
---

# Changelog

The project maintains a changelog at `notes/changelog.md` in **standard Markdown format**. The file is automatically converted to Telegram MarkdownV2 when displayed to users.

## Updating the Changelog

Analyze git history since last changelog update:

```bash
git log -1 --format="%H" -- notes/changelog.md  # baseline
git log <hash>..HEAD --oneline --no-merges       # commits
git diff <hash>..HEAD --name-only                # files
```

Draft entries, get user approval, then add to `[Latest additions]` section.

## What to Include

**User-facing:**
- New commands, features, UI changes
- Bug fixes users would notice
- Tool/integration improvements

**Major technical:**
- Architecture changes, new integrations/services
- Performance improvements, security updates

**Feature descriptions** must explain what it does for users:
- Good: "Progressive 'working' indicator that updates in real-time during agent processing (shows increasing hourglass symbols while waiting)"
- Bad: "Smart ping indicator system" (unclear what it does)

## What to Exclude

- Internal/meta changes: CLAUDE.md, README.md, CONTRIBUTION.md updates
- Code organization: file renames, module consolidations (unless major architectural change)
- Dev tooling config: ruff, mypy changes
- Test-only changes, skills
- Minor refactoring, code cleanup

## Entry Format

```markdown
**Added:**
• Feature name: what it does for users

**Changed:**
• Improvement description
```

- Use `**Added:**` for new features and capabilities
- Use `**Changed:**` for improvements to existing features
- Generally avoid `**Removed:**` section — focus on what's new and improved
- Use standard Markdown syntax (not MarkdownV2 escaping)

## Style Guide

**Length:** 1-2 lines max per entry. If longer, split or simplify.

**Start with:** noun (feature name), verb (Support, Improve), or command (`/name`)

**Patterns:**
- Feature: `Feature name: what it does for users`
- Command: `/command to do X`
- Rename: `Renamed /old → /new`
- Tech context: `(optional detail)` at end

**Avoid:** "Added support for..." → just "Support for..."

**Bullets:** Always use `•` (not `-`)

## Versioning / Release

- Keep `**[Latest additions]**` at the top as a staging area for unreleased changes
- When releasing version X.Y.Z:
  1. Move `[Latest additions]` content to new `**[X.Y.Z] - YYYY-MM-DD**` section
  2. Update version in: `pyproject.toml`, `letta_bot/__init__.py`
  3. Leave `[Latest additions]` empty with `**Added:**` and `**Changed:**` placeholders
