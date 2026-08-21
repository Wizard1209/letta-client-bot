# Letta Telegram Bot

> [!WARNING]
> **Unmaintained.** Deployed instances keep running, but no features, fixes or
> dependency updates are planned.
>
> The reason is the platform contract, not the code. Letta's V1 SDK — the only
> Python client — is [being deprecated](https://docs.letta.com/v1-sdk) in favour
> of the Agent SDK, which is TypeScript-only and carries no server-side Python
> tools. The V1 server source was archived in August 2026. There is no forward
> path for a Python client, and no server-side changelog to watch: over nine
> months this bot was rewritten five times to follow changes it was never told
> about.
>
> The last of those is representative. Server-side tools receive an injected
> `client` object; injection was made conditional on a `LETTA_API_KEY`
> environment variable that Letta Cloud does not set, so `client` silently
> became unusable for every existing agent. Tools kept reporting
> `status: "success"` while returning `name 'client' is not defined`, and
> scheduled notifications went quiet for days without raising an error anywhere.
> The [docs](https://docs.letta.com/v1-sdk/tools/server-tools) still promise the
> old behaviour.
>
> Tools here therefore build their own client from `LETTA_API_KEY` in the
> agent's `secrets` rather than using the injected global. It is the same
> credential — the injected client is built from that variable too — but the
> tool no longer depends on the runtime emitting the global at all.
> `devscripts/sync_custom_tools.py` pushes the sources and backfills that key.
> The Telegram, Markdown and storage layers carry no Letta coupling and are
> reusable as-is.

Multi-user Telegram bot for Letta cloud. This bot lets you provide your agents and agent architectures to end-users. Heavily inspired by <https://github.com/letta-ai/letta-telegram/>

## Forking

Issues and PRs are not being reviewed. Fork it — the code is a working reference
for the pieces that outlive the Letta coupling:

- `md_tg/` — Markdown → Telegram MessageEntity converter, UTF-16 aware offsets
  and chunking at block boundaries
- `letta_bot/middlewares.py` — photo/album batching, identity upsert
- `letta_bot/auth.py` + `letta_bot/queries/` — admin approval flow on Gel
