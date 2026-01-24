---
name: update-docs
description: Updates CLAUDE.md and other project docs based on recent changes. Use when user says "update docs", "add to CLAUDE.md", "document this", or runs /update-docs command.
---

# Update Project Documentation

Maintains project documentation by analyzing git history and syncing CLAUDE.md, help.md, botfather_commands.txt, and other docs with code changes.

## Quick Start

1. `git log -1 --format="%H" -- CLAUDE.md` → find baseline
2. `git diff <hash>..HEAD --name-only` → list changed files
3. Read CLAUDE.md → identify sections → map changes → propose → apply → check master

## Workflow

### Phase 1: Discover Changes

```bash
# Find last CLAUDE.md commit
git log -1 --format="%H" -- CLAUDE.md

# Get all changes since then
git diff <last-claude-commit>..HEAD --name-only
git log <last-claude-commit>..HEAD --oneline
```

**If CLAUDE.md not in git** (new file or untracked):

Ask user: "CLAUDE.md isn't tracked in git. How long since it was last updated?"

Options:
- "1 week" → `git log --since="1 week ago" --oneline --name-only`
- "1 month" → `git log --since="1 month ago" --oneline --name-only`
- "Specific date" → `git log --since="YYYY-MM-DD" --oneline --name-only`

### Phase 2: Analyze CLAUDE.md Structure

**Read the actual CLAUDE.md first.** Extract:
- All `##` and `###` section headings
- What each section documents (modules, commands, config, etc.)
- File/directory patterns mentioned in each section

Build a dynamic mapping: `changed file → relevant section(s)`

Example discovery:
```
Sections found:
- "## Configuration" mentions: config.py, .env, environment variables
- "## Middleware System" mentions: middlewares.py, filters.py
- "## Project Structure" lists: all module files
→ If middlewares.py changed, update "Middleware System" + "Project Structure"
```

### Phase 3: Propose Updates

For each affected area:
1. **Existing sections needing updates** - list specific changes
2. **New sections to add** - describe what they'd cover
3. **Other documentation files** - check if changes require updates beyond CLAUDE.md

#### Other Documentation Files

When analyzing changes, also check these files:

| Changed Files | Documentation to Update |
|---------------|------------------------|
| New `/command` handler in `auth.py`, `agent.py`, etc. | `notes/help.md`, `deploy/botfather_commands.txt` |
| New user-facing agent tool | `notes/help.md` (if users need to know about it) |
| Authorization or onboarding flow changes | `notes/about.md` |
| User-facing features | `notes/changelog.md` (`[Latest additions]` section) |

**Detection hints:**
- New `@router.message(Command('...'))` → likely needs help.md + botfather_commands.txt
- New tool in `custom_tools/` → check if user-facing or agent-internal
- Changes to middleware flow → may affect about.md

Present to engineer:
```
Changes detected since last CLAUDE.md update (<commit>):

**Files changed:**
• path/to/file.py - <brief description of change>
• path/to/new_module.py - NEW FILE

**Sections to UPDATE:**
• [Section Name] - reason
  └─ files: x.py, y.py

**Potential NEW sections:**
• [Proposed Title] - would document X
  └─ files: new_module.py

**Other docs to update:**
• notes/help.md - new /command added
• deploy/botfather_commands.txt - new /command added
• notes/changelog.md - user-facing feature

Which changes should I document?
```

Wait for engineer confirmation before proceeding.

### Phase 4: Apply Updates

After engineer approval:
1. Read affected sections from current CLAUDE.md
2. Apply changes matching existing style
3. Add new sections in appropriate locations

### Phase 5: Resolve Master Conflicts (AFTER applying updates)

```bash
git diff master -- CLAUDE.md
```

**IMPORTANT:** Run AFTER applying updates to catch:
- Sections modified in master that we also modified
- New sections added in master we might overwrite

**If master differs:**
1. `git show master:CLAUDE.md` → fetch master version
2. Identify conflicting sections
3. Merge: keep additions from both, prefer more complete version
4. Show engineer the diff before finalizing

**Conflict strategy:**
- Only in master → keep it
- Only in current → keep it
- Both modified → merge carefully, ask if unclear

## Quality Checks

Before finalizing:
- [ ] All identified changes documented in CLAUDE.md
- [ ] Other docs updated (help.md, botfather_commands.txt, about.md, changelog.md)
- [ ] No merge conflicts with master
- [ ] Matches existing formatting style
- [ ] Cross-references still valid

## References

- [CLAUDE.md Memory Management](https://code.claude.com/docs/en/memory) ([md](https://code.claude.com/docs/en/memory.md)) - official docs on CLAUDE.md structure and best practices
- [All Claude Code Docs](https://code.claude.com/docs/llms.txt) - LLM-friendly documentation index
