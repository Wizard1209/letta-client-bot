---
paths:
  - "letta_bot/queries/**/*.edgeql"
  - "dbschema/**/*.esdl"
---

# EdgeQL Quick Reference

EdgeQL is Gel's query language, blending object-oriented, graph, and relational concepts.

## Core Concepts

**Objects and Links (not Tables and Foreign Keys)**:

- Schema uses **object types** with **properties** and **links** (relations)
- Example:

  ```edgeql
  type Person {
    required name: str;
  }

  type Movie {
    required title: str;
    multi actors: Person;
  }
  ```

**Structured Results (not Flat Rows)**:

- Queries return nested objects, not flat row lists
- No need for explicit JOINs - use shapes to fetch related data
- Example:
  ```edgeql
  select Movie {
    title,
    actors: { name }
  }
  filter .title = "The Matrix"
  ```

**Composable and Strongly Typed**:

- Embed queries within queries (subqueries, nested mutations)
- Strongly typed - schema enforces consistency
- Shape expressions (curly braces) dictate result structure

## Syntax Patterns

**Data Retrieval**:

```edgeql
# Basic select with nested data
select Issue {
  number,
  status: { name },
  assignee: { firstname, lastname }
}
filter .status.name = "Open"
```

**Data Modification**:

```edgeql
# Insert
insert Person {
  name := "Alice"
}

# Nested insert with links
insert Movie {
  title := "The Matrix Resurrections",
  actors := (
    select Person
    filter .name in {"Keanu Reeves", "Carrie-Anne Moss"}
  )
}

# Update
update Person
filter .name = "Alice"
set {
  name := "Alice Smith"
}

# Delete
delete Person
filter .name = "Alice Smith"
```

**WITH Blocks (temporary views)**:

```edgeql
with
  active_users := select User filter .is_active
select active_users {
  firstname,
  friends: { firstname }
}
```

## Best Practices

1. **Embrace Object Modeling**: Model data with object types and links; avoid translating legacy relational schemas directly
2. **Favor Composability**: Use shapes and subqueries for readable, reusable query fragments
3. **Leverage Nested Fetching**: Fetch complex object graphs directly using shapes instead of manual joins
4. **Use Transactions**: Rely on transaction statements (`start transaction`, `commit`, `rollback`) for multi-step operations
5. **Consistent Typing**: Maintain clear, strict type definitions in schemas

## After Modifying Queries

Run `uv run gel-py` to regenerate Python modules from `.edgeql` files.
