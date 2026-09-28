# Performance Standards

## PERF-001: Avoid nested loops for membership checks
- severity: low
- fixable: no

Comparing two collections with nested `for` loops is O(n*m). Convert one side to a
`set` or `dict` and use membership lookups.

## PERF-002: Paginate unbounded queries
- severity: medium
- fixable: no

Endpoints must not `SELECT *` without `LIMIT`; paginate any query that can return
unbounded rows.
