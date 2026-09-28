# Past Bug Patterns (from incident postmortems)

## BUG-001: Swallowed exceptions hid a data-loss outage
- severity: medium
- fixable: yes
- detect: `except(\s+Exception)?\s*:\s*pass`

INC-2291: `except Exception: pass` in the order sync job silently dropped writes for
3 days. Never swallow exceptions. Log with `log.exception(...)` and re-raise, or catch
a specific exception type and handle it explicitly.

## BUG-002: Mutable default arguments leaked state between requests
- severity: medium
- fixable: yes
- detect: `def \w+\([^)]*=\s*(\[\]|\{\})`

INC-1874: `def add_item(item, cart=[])` shared one list across all requests. Use
`None` as the default and create the list inside the function.

## BUG-003: Missing timeout on outbound HTTP call caused thread exhaustion
- severity: high
- fixable: yes
- detect: `requests\.(get|post|put|delete)\((?![^)]*timeout)`

INC-2044: a `requests.get(url)` with no timeout hung worker threads when a partner API
stalled. Always pass `timeout=`.
