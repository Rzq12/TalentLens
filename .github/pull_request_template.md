# <!-- feat(scope): short imperative description -->

## What

<!-- What does this change do? One or two sentences. -->

## Why

<!-- Motivation and context. Link the issue this closes. -->

Closes #

## How

<!-- Implementation details worth a reviewer's attention. Call out anything
     non-obvious, and anything you deliberately did NOT do. -->

## Verification

Paste actual command output. Do not tick a box for something you did not run.

```
ruff check .        ->
mypy serving/app    ->
pytest tests/ -q    ->
```

- [ ] Tests written **before** the implementation (RED confirmed, then GREEN)
- [ ] Coverage did not drop below 80%
- [ ] No new `ruff` violations
- [ ] Google-style docstrings on new public functions and classes
- [ ] Type hints complete on every new signature

## Data, security, and migrations

- [ ] No secrets, API keys, or credentials added to tracked files
- [ ] No candidate PII or real resumes committed
- [ ] New environment variables documented in `.env.example`
- [ ] Alembic migration included if the schema changed
- [ ] Tenant scoping preserved on every new query

## Scope

- [ ] This PR does one thing
- [ ] Under ~500 changed lines, or the size is explained above
- [ ] Self-review completed

## Breaking changes

<!-- Describe any breaking change and the migration path, or write "None". -->

None
