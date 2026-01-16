---
name: code-review
description: Reviews code changes with brief annotations. Use when user says "review code", "review changes", "what changed", "review pull request", "review PR", "let's review", or runs /code-review.
---

# Code Review

Interactive guided tour through code changes.

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

What the PR/changes accomplish at high level.

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

### 4. File-by-File Tour

Walk through each changed file:

- Brief description of what changed
- At complex points: offer to trace execution flow
- Batch small/related files into single stops (e.g., utils + related refactors)
- End each stop clearly: "Questions, or next file?"

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

Quick summary of key changes when tour completes:

```markdown
**PR Summary:**
- Main feature added
- Supporting changes
- Dependencies/config updates

Ready to merge, or any concerns?
```

## Tour Stop Format

```markdown
## [filename.py](path/to/file.py) (+X/-Y)

**What changed:**
• Change 1
• Change 2

**Key point:** [explanation of important logic]

→ Want to trace how [feature X] flows through the code?

Questions, or next file?
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
- Lock files, generated code

## Scope Options

| Scope          | Command                  |
| -------------- | ------------------------ |
| PR             | `gh pr diff <number>`    |
| Uncommitted    | `git diff HEAD`          |
| Staged only    | `git diff --cached`      |
| vs main        | `git diff main...HEAD`   |
| Last N commits | `git diff HEAD~N..HEAD`  |
