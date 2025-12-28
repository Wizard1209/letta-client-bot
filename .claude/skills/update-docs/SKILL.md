---
name: update-docs
description: Updates CLAUDE.md based on recent project changes. Use when user says "update docs", "add to CLAUDE.md", "document this", or runs /update-docs command.
---

# Update CLAUDE.md

Maintains project documentation by analyzing git history and syncing CLAUDE.md with code changes.

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
- "1 week" → use `git log --since="1 week ago"`
- "1 month" → use `git log --since="1 month ago"`
- "Specific date" → ask for date, use `git log --since="YYYY-MM-DD"`
- "All time" → use full git history (may be large)

```bash
# Get changes by time range instead of commit
git log --since="1 week ago" --oneline --name-only
```

**Analyze changed files:**
- New modules/files → potential new sections
- Modified handlers/commands → updates to existing docs
- Config changes → update Configuration section
- Schema changes → update data model docs
- New dependencies → update setup/install docs

### Phase 2: Map Changes to Sections

Read current CLAUDE.md and map project areas to doc sections:

| Change Type | Likely Section |
|-------------|----------------|
| `**/commands/*.py`, handlers | Commands, Usage |
| `config.py`, `.env*` | Configuration |
| `schema.edgeql`, `queries/` | Database Schema, EdgeQL |
| `middlewares.py`, `filters.py` | Middleware System, Filters |
| New module file | New section or subsection |
| `Dockerfile`, `docker-compose*` | Deployment |
| `devscripts/` | Devscripts |

### Phase 3: Propose Updates

For each affected area, identify:
1. **Existing sections needing updates** - list specific changes
2. **New sections to add** - describe what they'd cover

Present to engineer:
```
Changes detected since last CLAUDE.md update (<commit>):

**Sections to UPDATE:**
• [Section Name] - reason (files: x.py, y.py)
• [Section Name] - reason

**Potential NEW sections:**
• [Proposed Title] - would document X (files: new_module.py)

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
# Check if master has different CLAUDE.md than our updated version
git diff master -- CLAUDE.md
```

**IMPORTANT:** Run this check AFTER applying updates, not before. This catches:
- Sections modified in master that we also modified
- New sections added in master we might overwrite
- Deletions in master we might reintroduce

**If master differs:**
1. Fetch master's CLAUDE.md: `git show master:CLAUDE.md`
2. Identify conflicting sections (both branches modified same area)
3. Merge content intelligently:
   - Keep additions from both branches
   - For same-section edits, combine information or prefer more complete version
   - Preserve master's structure when possible
4. Show engineer the diff before finalizing

**Conflict resolution strategy:**
- Section exists only in master → keep it (don't lose upstream changes)
- Section exists only in current → keep it (our new content)
- Section modified in both → merge carefully, ask engineer if unclear

## Quality Checks

Before finalizing:
- [ ] All identified changes documented
- [ ] No merge conflicts with master
- [ ] Matches existing formatting style
- [ ] Cross-references still valid
- [ ] No duplicate information

## Git Commands Reference

```bash
# Last CLAUDE.md change
git log -1 --format="%H %s" -- CLAUDE.md

# Changes since commit
git diff <commit>..HEAD --stat
git log <commit>..HEAD --oneline --name-only

# Changes by time range (when CLAUDE.md not in git)
git log --since="1 week ago" --oneline --name-only
git log --since="2025-01-15" --oneline --name-only

# Diff with master
git diff master -- CLAUDE.md

# Show file at specific commit
git show master:CLAUDE.md
```
