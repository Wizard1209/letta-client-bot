# Docs

Design notes that outlive a single change. Runtime text served to bot users
lives in `notes/`, not here.

| File | What it is | Read it when |
|------|------------|--------------|
| [`harness-spec.html`](harness-spec.html) | Registry: 40 harness properties + 31 bot features, one row each, with what we already own and what it costs to rebuild | Scoring a candidate framework — one pass down the rows |
| [`freeze.html`](freeze.html) | Registry: 82 rows of what is left unclosed - platform coupling, fleet state, runtime holes, deployment, documentation drift, code debt, and what will not be built | Something broke and you need to know whether it is known; or you are deciding what to touch |
| [`harness-spec-long.html`](harness-spec-long.html) | The argument behind the registry: five breaking changes with their cost in commits, context-window measurements across the agent fleet, the boundary drawings, nine screening questions | A row is disputed, or someone asks why replacing Letta is a state-server problem rather than an SDK problem |

The harness registry is the working document for choosing a replacement; the long
version is its evidence, since every row was derived from a measurement or an
incident the table has no room to carry. `freeze.html` answers a different
question - not what to build next, but what a maintainer inherits.
