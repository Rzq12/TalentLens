# Contributing to TalentLens

This is a solo project. `@Rzq12` is the sole author and contributor. These
conventions exist so that future-you can reconstruct why a change was made, and
so the repository holds up to outside review.

## Branch strategy

```
main                    protected, release-ready, tagged
  └── develop           integration branch, always green
        ├── feat/resume-ocr-fallback
        ├── fix/docx-offset-drift
        └── chore/pin-dependencies

  └── hotfix/parser-crash        branches from main, merges to main AND develop
  └── release/0.2.0              branches from develop, merges to main AND develop
```

| Prefix | From | Merges to | Use for |
|---|---|---|---|
| `feat/` | `develop` | `develop` | New capability |
| `fix/` | `develop` | `develop` | Bug fix (non-urgent) |
| `chore/` | `develop` | `develop` | Deps, tooling, config |
| `docs/` | `develop` | `develop` | Documentation only |
| `refactor/` | `develop` | `develop` | Behaviour-preserving change |
| `test/` | `develop` | `develop` | Test-only work |
| `release/` | `develop` | `main` + `develop` | Version bump, changelog, final checks |
| `hotfix/` | `main` | `main` + `develop` | Production-urgent fix only |

Branch names are kebab-case and describe the change, not the ticket alone:
`feat/batch-resume-upload`, not `feat/issue-42`.

Keep branches short-lived. Rebase onto `develop` rather than merging `develop`
in, so history stays linear — but only while the branch is unpushed or you are
certain nobody else has based work on it. Never rebase `main` or `develop`.

## Commit messages

[Conventional Commits](https://www.conventionalcommits.org/). The release
workflow parses these to generate notes, so the type prefix is load-bearing.

```
<type>(<scope>): <subject>

[body: why, not what]

[footer: Closes #123, BREAKING CHANGE: ...]
```

**Types:** `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `chore`, `perf`, `ci`, `revert`

**Scopes:** `api`, `auth`, `ingestion`, `parser`, `jobs`, `db`, `infra`, `tests`

Subject line: imperative mood, no trailing period, 72 characters or fewer.

```
# Good
feat(ingestion): deduplicate resumes by content hash
fix(parser): normalize BadZipFile into DocumentParseError

    zipfile.BadZipFile does not inherit from OSError, so it escaped the
    except clause in _parse_docx and surfaced as a raw library exception
    instead of a 422.

    Closes #17

# Bad
update stuff
WIP
fixed bug
```

**Authorship.** Every commit is authored by `@Rzq12`. Do not add
`Co-authored-by` trailers. Do not credit AI tools, bots, or automated systems
as authors, co-authors, contributors, maintainers, or reviewers anywhere in
commit metadata, documentation, or package metadata.

## Definition of done

A change is not finished until all of these hold:

```bash
ruff check .          # no violations
mypy serving/app      # no issues
pytest tests/ -q      # all pass
pytest tests/ --cov=serving/app   # coverage >= 80%
```

Plus:

- Tests were written **before** the implementation, and observed to fail for
  the intended reason before any production code changed.
- New public functions and classes carry Google-style docstrings.
- Every new signature is fully type-hinted.
- New environment variables are documented in `.env.example`.
- Schema changes ship with an Alembic migration.
- No secrets, credentials, or candidate PII in tracked files.

## Versioning

[Semantic Versioning](https://semver.org/). `MAJOR.MINOR.PATCH`.

- **MAJOR** - breaking API change, or a change to the scoring formula that
  makes historical scores non-reproducible.
- **MINOR** - new capability, backwards compatible.
- **PATCH** - bug fix, backwards compatible.

Pre-1.0 the API is not stable; minor bumps may still break things, and that is
signalled in the changelog rather than by the version alone.

The tag must match `pyproject.toml`'s `project.version` - the release workflow
fails the build if they diverge.

## Release process

1. `git switch develop && git pull`
2. `git switch -c release/0.2.0`
3. Bump `version` in `pyproject.toml`; update `CHANGELOG.md`
4. Run the full gate locally; fix anything red
5. Open a PR into `main`, merge after CI is green
6. `git tag -a v0.2.0 -m "Release v0.2.0"` on `main`, then `git push origin v0.2.0`
7. The release workflow verifies the tag, builds, and publishes the GitHub release
8. Merge `main` back into `develop` so the version bump is not stranded

## Security

Do not open a public issue for an exploitable vulnerability in a deployed
instance - use a GitHub private security advisory. Never paste real candidate
data, resumes, tokens, or connection strings into issues or PRs.
