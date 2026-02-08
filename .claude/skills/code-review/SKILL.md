---
name: code-review
description: Reviews code changes with brief annotations. Use when user says "review code", "review changes", "what changed", "review pull request", "review PR", "review the pr", "review this pr", "review [name]'s pr", "review new pr", "review latest pr", "let's review", "review https://github.com/.../pull/123", or runs /code-review.
---

# Code Review

Interactive guided tour through code changes. You are walking a human through the code to help them understand it.

## Quick Start

```bash
# For PRs: get PR info and diff
gh pr list
gh pr view <number>
gh pr diff <number>

# For local changes
git diff HEAD --stat
```

## Review Protocol

### 1. Overview (2-3 sentences max)

What the PR/changes accomplish at high level. Focus on the *purpose* — what problem does this solve and why.

### 2. Offer Branch Switch

For PRs, offer to checkout the branch so user can explore in IDE alongside.

### 3. Tour Map

Show grouped file list so user sees full scope:

```markdown
| Group        | Files                    |
| ------------ | ------------------------ |
| Core feature | `main.py`, `helper.py`   |
| Utilities    | `utils.py`, `config.py`  |
| Docs         | `README.md`, `CHANGELOG` |
```

Then ask: "Where do you want to start, or should I go in order?"

### 4. File-by-File Tour

**CRITICAL: Send ONE stop per message. Wait for user response before continuing.**

Never combine multiple stops. Never send the full review at once. The user must have space to ask questions, discuss, or skip ahead at each stop.

At each stop:
- Explain *why* this file changed (its role in the bigger picture)
- Describe changes in plain language — what the code *does*, not just what lines differ
- Keep it scannable: short bullets, no paragraphs
- At complex points: offer to trace execution flow
- Batch small/related files into single stops (e.g., query files + generated code)
- DO NOT mix concerns/suggestions into the tour — collect them for wrap-up

End each stop clearly: "Questions, or next?"

### 5. Flow Tracing (on-demand)

When user wants to understand a specific feature deeper, trace the execution path:

```text
Entry point (e.g., handler receives message)
    ↓
Layer 2 (calls helper function)
    ↓
Layer 3 (calls API/database)
    ↓
Back up the stack with result
```

This shows how pieces connect across files.

### 6. Wrap-up

Only after completing the tour (or user asks to wrap up), present:

```markdown
**Summary:**
- [1-sentence description of the main change]
- [Supporting changes]

**Concerns:** (if any)
- [Specific issue with file reference]
- [Specific issue with file reference]

**Nits:** (if any, keep brief)
- [Minor observations]

Ready to merge, or want to discuss any concerns?
```

Concerns and suggestions go HERE, not during the tour stops. The tour is for understanding, the wrap-up is for judgment.

## Tour Stop Format

Keep stops SHORT. Aim for 5-8 lines of content, not 20.

```markdown
## [filename.py](path/to/file.py) (+X/-Y)

**Why:** [One sentence — this file's role in the change]

• [What the code does now, in plain language]
• [Key behavioral difference from before]
• [Notable design choice, if any]

→ Want to trace how [feature X] flows?

Questions, or next?
```

**Bad stop** (too technical, too dense):
> `get_or_create_letta_identity()` removed entirely. `create_agent_from_template()` now takes `telegram_id: int` instead of `identity_id: str` and builds tags internally using f-strings. New `list_agents_by_user()` wraps `client.agents.list(tags=[identity_tag])`. The `attach_identity_to_agent()` was replaced by `add_user_to_agent()` which retrieves agent, appends tag, updates. Race condition possible if two approvals happen simultaneously...

**Good stop** (human-readable, focused):
> **Why:** This is the main Letta API layer — all identity API calls lived here.
>
> • Deleted identity creation/retrieval — no more Letta Identity API
> • Agent operations now filter by tags instead of identity IDs
> • New helpers: list user's agents, validate access, add user to agent
>
> Questions, or next?

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
- Lock files, generated code
- Auto-generated files that mirror manual changes (batch with their source)

## Scope Options

| Scope          | Command                  |
| -------------- | ------------------------ |
| PR             | `gh pr diff <number>`    |
| Uncommitted    | `git diff HEAD`          |
| Staged only    | `git diff --cached`      |
| vs main        | `git diff main...HEAD`   |
| Last N commits | `git diff HEAD~N..HEAD`  |

## External PR URLs

When given a GitHub URL like `https://github.com/owner/repo/pull/123`:

1. Parse owner, repo, and PR number from URL
2. Use `-R owner/repo` flag for gh commands:

```bash
gh pr view 123 -R owner/repo --json title,body,author,state,additions,deletions,files,baseRefName,headRefName
gh pr diff 123 -R owner/repo
```

3. Follow the standard review protocol above
