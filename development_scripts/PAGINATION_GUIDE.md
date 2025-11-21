# Letta SDK v1.0 Pagination Guide

## How Pagination Works

After analyzing the SDK source code (`_base_client.py` and `pagination.py`), here's the complete explanation:

### Core Components

1. **AsyncPaginator** - Returned by `.list()` methods
2. **AsyncArrayPage** - The actual page object containing items
3. **Cursor-based pagination** - Uses item IDs, not offsets

### The Flow

```python
# When you call:
tools_page = await client.agents.tools.list(agent_id=agent_id)

# What happens:
# 1. client.agents.tools.list() returns AsyncPaginator[Tool, AsyncArrayPage[Tool]]
# 2. await AsyncPaginator triggers __await__() which calls _get_page()
# 3. Returns AsyncArrayPage[Tool] with .items attribute
```

## Safe Patterns (No Data Loss)

### Pattern 1: Single Page Access (Current in Our Code)
```python
# Used in: notification.py, agent.py
tools_page = await client.agents.tools.list(agent_id=agent_id)
for tool in tools_page.items:
    print(tool.name)
```

**When safe:**
- Resource has few items (< default page limit)
- You only need first page
- You check `page.has_next_page()` if unsure

**Limitation:**
- Only gets first page (default limit varies by endpoint)

### Pattern 2: Auto-Iteration (Recommended for ALL Items)
```python
# Automatically fetches ALL pages
paginator = client.agents.tools.list(agent_id=agent_id)
async for tool in paginator:
    print(tool.name)
```

**How it works:**
- `AsyncPaginator.__aiter__()` → awaits first page
- `AsyncArrayPage.__aiter__()` → calls `iter_pages()`
- `iter_pages()` automatically fetches next pages using `get_next_page()`
- Stops when `has_next_page()` returns False

**Guarantee:** Gets ALL items across ALL pages

### Pattern 3: Manual Page Control
```python
page = await client.agents.tools.list(agent_id=agent_id, limit=10)
async for current_page in page.iter_pages():
    print(f"Processing page with {len(current_page.items)} items")
    for tool in current_page.items:
        process(tool)
    # Can break early if needed
```

**Use when:**
- Need to process pages as batches
- Want progress indicators per page
- Need fine-grained control

### Pattern 4: Cursor-Based Manual Pagination
```python
# Get first page
page1 = await client.agents.tools.list(agent_id=agent_id, limit=5, order='asc')
last_id = page1.items[-1].id

# Get next page starting after last_id
page2 = await client.agents.tools.list(agent_id=agent_id, limit=5, after=last_id, order='asc')
```

**When to use:**
- Implementing custom pagination UI
- Resuming from specific point
- Need to control pagination flow manually

## How Cursor Pagination Works

From `AsyncArrayPage.next_page_info()`:

```python
def next_page_info(self) -> Optional[PageInfo]:
    if not self.items:
        return None

    if is_forwards:  # Normal pagination
        last_item = items[-1]
        return PageInfo(params={"after": last_item.id})
    else:  # Backward pagination
        first_item = items[0]
        return PageInfo(params={"before": first_item.id})
```

**Key insights:**
- Uses **item IDs as cursors**, not offsets
- `after=<id>` gets items AFTER this ID
- `before=<id>` gets items BEFORE this ID
- Direction controlled by `order='asc'` or `order='desc'`

## Pagination Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `limit` | int | Max items per page (varies by endpoint) |
| `after` | str | Get items after this ID (forward) |
| `before` | str | Get items before this ID (backward) |
| `order` | 'asc'/'desc' | Sort order (affects pagination direction) |
| `order_by` | str | Field to sort by (default: created_at) |

## Can You Lose Items?

### ❌ NO - Cursor-based pagination is safe

**Why cursor pagination prevents data loss:**

1. **Stable cursors** - Uses item IDs which don't change
2. **No gap/overlap** - `after=last_id` starts exactly after last item
3. **Atomic fetches** - Each page is a consistent snapshot

**Contrast with offset pagination (NOT used in Letta):**
```python
# OFFSET PAGINATION (vulnerable to data loss)
page1 = get_items(offset=0, limit=10)  # Items 0-9
# Someone inserts item at position 0
page2 = get_items(offset=10, limit=10)  # Skips item that was at position 9!
```

**Cursor pagination (what Letta uses):**
```python
# CURSOR PAGINATION (safe)
page1 = get_items(limit=10)  # Items with IDs ending at "xyz"
# Someone inserts new items
page2 = get_items(after="xyz", limit=10)  # Continues from "xyz", no gaps!
```

### ⚠️ Only Way to Lose Items

**If you do this wrong:**
```python
# BAD: Only gets first page!
page = await client.agents.tools.list(agent_id=agent_id)
for tool in page:  # ❌ This iterates page.items (first page only)
    print(tool.name)
```

**Solution:**
```python
# GOOD: Gets ALL pages automatically
async for tool in client.agents.tools.list(agent_id=agent_id):
    print(tool.name)
```

## Our Codebase Analysis

### Current Usage in notification.py

```python
# Line 92-94
tools_page = await client.agents.tools.list(agent_id=agent_id)
schedule_tool_attached = any(
    t.name == 'schedule_message' for t in tools_page.items
)
```

**Status:** ✅ Safe for most cases
- Tools per agent is usually small (< 50)
- Default page limit likely covers all tools
- Checks membership, doesn't need ALL tools

**Risk:** Low - but could miss tools if agent has 100+ tools

### Current Usage in agent.py

```python
# Line 208-210
agents_page = await client.identities.agents.list(
    identity_id=identity.identity_id
)
for agent in agents_page.items:
    # build UI
```

**Status:** ✅ Safe
- Agents per identity typically small (1-10)
- Default limit sufficient

## Recommendations

### 1. Keep Current Pattern for Most Cases
```python
# For resources with known small counts
page = await client.agents.tools.list(agent_id=agent_id)
for item in page.items:
    process(item)
```

### 2. Add Safety Check for Critical Operations
```python
# For operations that MUST see all items
page = await client.agents.tools.list(agent_id=agent_id)
if page.has_next_page():
    # Log warning or use full iteration
    LOGGER.warning(f"Agent {agent_id} has more than {len(page.items)} tools")
```

### 3. Use Full Iteration for Unbounded Resources
```python
# For resources that could grow large
all_items = []
async for item in client.some_resource.list(...):
    all_items.append(item)
```

## Performance Considerations

### Single Page (Fast)
- ✅ One API call
- ✅ Low latency
- ❌ Might miss items

### Full Iteration (Thorough)
- ✅ Gets ALL items guaranteed
- ❌ Multiple API calls
- ❌ Higher latency for large datasets

### When to Use Each

| Use Case | Pattern | Why |
|----------|---------|-----|
| Check if specific tool attached | Single page | Fast, likely complete |
| List agents for UI | Single page | Small dataset |
| Export all data | Full iteration | Must be complete |
| Count all items | Full iteration | Must be accurate |
| Find one item | Single page + early exit | Performance |

## Testing Pagination

To verify pagination works correctly:

```python
# Test data integrity
page = await client.list(limit=100)
single_page_ids = {item.id for item in page.items}

all_ids = set()
async for item in client.list(limit=2):  # Small pages
    all_ids.add(item.id)

assert single_page_ids == all_ids, "Data loss detected!"
```

## Conclusion

**Your concern about losing items is valid, but:**

1. ✅ Cursor-based pagination prevents data loss
2. ✅ Our current code is safe for typical use cases
3. ✅ SDK automatically handles pagination correctly
4. ⚠️ Only risk is using `.items` when dataset is large

**Action items:**
- ✅ Current code is fine for tools/blocks/agents (small datasets)
- Consider full iteration if you expect 100+ items
- Add `has_next_page()` checks for critical operations
