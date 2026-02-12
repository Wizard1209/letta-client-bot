---
paths:
  - "devscripts/**/*.py"
---

# Writing Devscripts

Import from `devscripts.bootstrap` and `letta_bot.config`:

```python
"""Description of the script.

Usage:
    uv run python -m devscripts.my_script [args]
"""

from devscripts.bootstrap import letta, gel, print_config, resolve_agent_id
from letta_bot.config import CONFIG


def main() -> None:
    print_config()  # Always print key inputs first
    agents = letta.agents.list()


if __name__ == '__main__':
    main()
```

## Bootstrap API

- `letta` - sync Letta client (created at import time)
- `gel` - sync Gel client (created at import time)
- `print_config(**extra)` - print masked config values; pass extra kwargs for script-specific inputs
- `resolve_agent_id(cli_arg=None)` - resolve agent ID from CLI > env > .agent_id file
## Key Rules

1. Sync clients only (no async/await)
2. Import clients from `devscripts.bootstrap`, config from `letta_bot.config`
3. Use `CONFIG.field` for env vars
4. Use `resolve_agent_id()` for agent ID resolution
5. Always call `print_config()` at script start (pass extra kwargs for script-specific inputs)
6. Include usage docstring at top
7. Use argparse for CLI args

**Note:** devscripts are excluded from mypy and type annotation checks (see pyproject.toml)
