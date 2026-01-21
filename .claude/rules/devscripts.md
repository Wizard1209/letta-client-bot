---
paths:
  - "devscripts/**/*.py"
---

# Writing Devscripts

Import from `devscripts.bootstrap`:

```python
"""Description of the script.

Usage:
    uv run python -m devscripts.my_script [args]
"""

from devscripts.bootstrap import env, letta, gel


def main() -> None:
    project_id = env('LETTA_PROJECT_ID')
    agents = letta.agents.list()
    users = gel.query('select User { telegram_id }')


if __name__ == '__main__':
    main()
```

## Bootstrap API

- `env(key, default=None)` - get env var
- `letta` - sync Letta client
- `gel` - sync Gel client

## Key Rules

1. Sync clients only (no async/await)
2. Import from `devscripts.bootstrap`, NOT `letta_bot.config`
3. Use `env()` for env vars, NOT `CONFIG`
4. Include usage docstring at top
5. Use argparse for CLI args

**Note:** devscripts are excluded from mypy and type annotation checks (see pyproject.toml)
