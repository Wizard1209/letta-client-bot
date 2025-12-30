---
name: code-review
description: Reviews code changes with brief annotations. Use when user says "review code", "review changes", "what changed", or runs /code-review.
---

# Code Review

Summarize code changes with short annotations.

## Quick Start

```bash
# Get scope
git diff HEAD --stat

# Review each file's diff, annotate important changes
```

## Output Format

```
## Code Review

**file.py** (+X/-Y)
• What changed and why it matters

**another.py** (+X/-Y)
• Key change description
```

## Guidelines

**Include:**
- Functional changes (new logic, modified behavior)
- Security-sensitive code
- Breaking changes
- New dependencies

**Skip:**
- Import reordering
- Formatting-only
- Comment typos

## Scope Options

| Scope | Command |
|-------|---------|
| Uncommitted | `git diff HEAD` |
| Staged only | `git diff --cached` |
| vs main | `git diff main...HEAD` |
| Last N commits | `git diff HEAD~N..HEAD` |

Default: `git diff HEAD` (all uncommitted changes)
