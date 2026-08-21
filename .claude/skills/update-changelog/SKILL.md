---
name: update-changelog
description: Updates notes/changelog.md based on git history. Use when user says "update changelog", "changelog entry", "release version", "release X.Y.Z", or runs /update-changelog.
---

# Update Changelog

Read `notes/changelog.md` first to load the changelog rule (`.claude/rules/changelog.md`), then follow it.

## Workflow

1. Find baseline: `git log -1 --format="%H" -- notes/changelog.md`
2. Review commits: `git log <hash>..HEAD --oneline --no-merges`
3. Review files: `git diff <hash>..HEAD --name-only`
4. Draft entries following the changelog rule
5. Get user approval
6. Add to `[Latest additions]` section
