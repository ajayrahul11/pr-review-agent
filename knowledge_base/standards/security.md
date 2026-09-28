# Security Standards

## SEC-001: No hard-coded secrets
- severity: critical
- fixable: yes
- detect: `(?i)(password|passwd|secret|api_key|apikey|token)\s*=\s*['"][^'"]+['"]`

Secrets (passwords, API keys, tokens) must never be committed to source. Load them from
environment variables or AWS Secrets Manager, e.g. `os.environ["DB_PASSWORD"]`. Any
secret that reached a branch must be rotated.

## SEC-002: Parameterized SQL only
- severity: high
- fixable: yes
- detect: `execute\(\s*f["']|execute\([^)]*%\s*\(|execute\([^)]*\+\s*\w`

Never build SQL with f-strings, `%` formatting or string concatenation. Use driver
placeholders: `cur.execute("SELECT * FROM users WHERE name = ?", (name,))`. String-built
SQL is a blocking issue (SQL injection).

## SEC-003: No eval/exec on untrusted input
- severity: high
- fixable: no
- detect: `\b(eval|exec)\(`

`eval`, `exec` and `pickle.loads` on user-controlled data allow remote code execution.
Use `ast.literal_eval` for literals or an explicit parser.
