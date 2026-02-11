---
name: code-review
description: Reviews code changes with concrete feedback. Use when user says "review code", "review changes", "what changed", "review pull request", "review PR", "review the pr", "review this pr", "review [name]'s pr", "review new pr", "review latest pr", "let's review", "code review", "code review?", "review https://github.com/.../pull/123", or runs /code-review. ALSO trigger when user has just been exploring a PR/diff and asks for review, feedback, or opinions — even without the exact word "review". Also trigger when user mentions a PR by number or URL with intent to understand it — e.g. "walk me through PR <n>", "explain PR <n>", "show me PR <n>", "what's in PR <n>", "go over PR <n>", "break down PR <n>".
---

# Code Review

Interactive guided tour through code changes. You are walking a human through the code to help them understand it.

## Quick Start

```bash
# For PRs: get file list and size
gh pr view <number> --json additions,deletions,files
gh pr diff <number> --name-only

# For local changes
git diff HEAD --name-only
```

## Large PRs (>1500 lines changed)

Never load the full diff at once — it will crash context.

```bash
# 1. Get file list with sizes
gh pr view <number> --json files --jq '.files[] | "\(.additions)+\(.deletions) \(.path)"'

# 2. Diff one file at a time during tour stops
gh pr diff <number> | awk '/^diff --git a\/<file>/,/^diff --git/{if(/^diff --git/ && !/\/<file>/)exit; print}'
```

Walk files one at a time — only load each file's diff at its tour stop.

## Review Protocol

### 1. Overview (2-3 sentences max)

What the PR/changes accomplish at high level. Focus on the *purpose* — what problem does this solve and why.

### 2. Branch Check

For PRs, check if user is on the PR branch. If not, note it once: "You're on `main`, PR branch is `fix-fee-padding`." Don't ask — user will switch if they want to.

### 3. Tour Map

Show grouped file list ordered top-down for understanding:

1. **Docs/config** — README, CHANGELOG, configs, types, specs
2. **High-level** — entry points, APIs, service interfaces, route definitions
3. **Implementation** — core logic, helpers, utilities
4. **Tests** — verify the above matches intent

**Ordering principle:** each stop should build on what the user already learned.

**Signals:** types/specs/schemas before implementation, interfaces before their consumers, small supporting changes batch together, tests last.

Then start the tour in this order. User can say "skip to X" anytime.

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

### 5. Git Context (on-demand)

When a change seems non-obvious, check `git blame` or `git log` on the modified lines to explain why the old code existed and what this change replaces:

```bash
git log --oneline -5 -- path/to/file.ts
git blame path/to/file.ts -L 130,140
```

### 6. Flow Tracing (on-demand)

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

### 7. Wrap-up

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

## PR Diff Links

For PR reviews, generate clickable links that jump to the exact change in GitHub's diff view.

**Generate link:**
```bash
OWNER_REPO=$(gh repo view --json nameWithOwner -q .nameWithOwner) PR=<number> FILE="path/to/file.ts" LINE=<right-side-line> && echo "https://github.com/$OWNER_REPO/pull/$PR/files#diff-$(echo -n "$FILE" | sha256sum | cut -d' ' -f1)R$LINE"
```

**URL anatomy:**
```
https://github.com/<owner>/<repo>/pull/<PR>/files
  #diff-<SHA-256 of file path>
  R<line>                        ← right side (new). Use L<line> for left (old/removed)
```

**Line number:** Use the right-side line from diff hunk headers. `@@ -133,7 +133,7 @@` means new side starts at 133 — count offset from there.

**When to include:** Key changes, complex logic, security-sensitive spots. Not every line — just where jumping to the diff helps.

## Posting Comments on PR

**PR-level comment** (conversation tab):
```bash
gh pr comment <number> --body "comment text here"
```

**Inline comment on a specific diff line** (Files Changed tab):
```bash
gh api -X POST "/repos/{owner}/{repo}/pulls/{number}/comments" \
  -f body="comment text" \
  -f commit_id="$(gh pr view <number> --json headRefOid -q .headRefOid)" \
  -f path="path/to/file.ts" \
  -F position=<diff_position>
```

`position` is the 1-based line offset within the diff hunk (not the file line number). Count from the `@@` header: first line after `@@` is position 1.
