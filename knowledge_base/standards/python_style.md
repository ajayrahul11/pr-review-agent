# Python Style Standards

## STY-001: Use logging, not print
- severity: low
- fixable: yes
- detect: `^\s*print\(`

Application code must not use `print()`. Use a module logger:
`log = logging.getLogger(__name__)` and `log.info("looking up %s", name)` (lazy %-args,
not f-strings).

## STY-002: TODOs must reference a ticket
- severity: info
- fixable: no
- detect: `#\s*TODO(?!\()`

Every TODO must reference a tracking ticket, e.g. `# TODO(SHOP-123): add TTL`.
