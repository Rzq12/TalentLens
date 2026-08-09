"""Documentation-drift guards for the README API table and `.env.example`.

The Definition of Done requires that a new endpoint reaches the README and a new
setting reaches `.env.example`. Nothing enforced that, so both drifted: the
README advertised eight endpoints while the application served twenty, and five
configurable settings were absent from the template a new contributor copies.

Prose cannot be type-checked, but these two facts can. Both checks read the
committed documents as text and compare them against the application's own
introspection — the OpenAPI schema and `Settings.model_fields` — so they run
without a database and fail on the commit that introduces the drift rather than
during a later audit.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[2]
_README = _ROOT / "README.md"
_ENV_EXAMPLE = _ROOT / ".env.example"

# Settings that configure nothing a deployment operator should set. `app_name`,
# `version`, and `api_v1_prefix` identify the build itself: overriding them from
# the environment changes what the API calls itself without changing behaviour,
# so they are deliberately absent from the template.
_INTERNAL_SETTINGS = frozenset({"APP_NAME", "VERSION", "API_V1_PREFIX"})


def _openapi_paths() -> set[tuple[str, str]]:
    """Return every `(METHOD, path)` pair the application actually serves.

    Read from the OpenAPI schema rather than `app.routes`, because Starlette
    nests routes added via `include_router` inside wrapper objects that carry no
    `methods` attribute of their own.
    """
    # `Settings` has required fields with no defaults; the session fixture in
    # conftest populates them, and these guard direct single-file invocation.
    os.environ.setdefault(
        "DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5433/talentlens_test"
    )
    os.environ.setdefault("JWT_SECRET", "test-secret-not-a-real-key")
    os.environ.setdefault("STORAGE_BACKEND", "memory")
    os.environ.setdefault("ENVIRONMENT", "test")

    from app.main import create_app

    spec: dict[str, Any] = create_app().openapi()
    return {
        (method.upper(), path)
        for path, operations in spec["paths"].items()
        for method in operations
    }


def _readme_documented_routes() -> set[tuple[str, str]]:
    """Return every `(METHOD, path)` pair the README's API table lists.

    Matches Markdown table rows of the form `| `GET` | `/api/v1/x` | ... |`,
    tolerating the backticks and surrounding whitespace the table uses.
    """
    row = re.compile(
        r"^\|\s*`(GET|POST|PUT|PATCH|DELETE)`\s*\|\s*`([^`]+)`\s*\|",
        re.MULTILINE,
    )
    return {
        (match.group(1).upper(), match.group(2).strip())
        for match in row.finditer(_README.read_text(encoding="utf-8"))
    }


def _env_example_keys() -> set[str]:
    """Return every environment variable name assigned in `.env.example`."""
    assignment = re.compile(r"^\s*([A-Z][A-Z0-9_]*)\s*=", re.MULTILINE)
    return set(assignment.findall(_ENV_EXAMPLE.read_text(encoding="utf-8")))


def _settings_keys() -> set[str]:
    """Return the environment variable name of every `Settings` field."""
    from app.config import Settings

    return {name.upper() for name in Settings.model_fields}


def test_the_readme_api_table_is_parsed_at_all() -> None:
    """Anti-vacuous guard: an unparsed table makes the coverage check trivially pass."""
    documented = _readme_documented_routes()
    assert documented, (
        f"parsed zero endpoints out of {_README.name} — the API table format changed "
        "and the drift checks below are no longer verifying anything"
    )


def test_the_env_example_is_parsed_at_all() -> None:
    """Anti-vacuous guard: an unparsed template makes the coverage check trivially pass."""
    assert _env_example_keys(), f"parsed zero assignments out of {_ENV_EXAMPLE.name}"


def test_readme_documents_every_registered_route() -> None:
    """An endpoint absent from the README is an endpoint no reviewer knows to exercise.

    The README is the only API map a reader gets before running the service, so
    an undocumented route is functionally invisible — including the rubric and
    search surfaces, which is exactly the drift this caught.
    """
    served = _openapi_paths()
    documented = _readme_documented_routes()
    assert served, "the OpenAPI schema exposed no paths — the app failed to wire its routers"

    undocumented = sorted(f"{method} {path}" for method, path in served - documented)

    assert not undocumented, (
        f"routes served by the application but missing from the {_README.name} API table: "
        f"{undocumented} — add them to the table before merging"
    )


def test_the_readme_api_table_lists_no_route_that_does_not_exist() -> None:
    """A table entry for a removed route sends a reader to a guaranteed 404.

    The inverse of the check above: documentation that overstates the surface is
    as misleading as documentation that understates it.
    """
    served = _openapi_paths()
    documented = _readme_documented_routes()

    stale = sorted(f"{method} {path}" for method, path in documented - served)

    assert not stale, (
        f"the {_README.name} API table lists routes the application does not serve: {stale}"
    )


def test_env_example_documents_every_configurable_setting() -> None:
    """A setting absent from the template is a setting nobody knows they can set.

    `.env.example` is what a new contributor copies to `.env`. A field missing
    from it is discoverable only by reading `config.py`, which defeats the point
    of shipping a template.
    """
    configurable = _settings_keys() - _INTERNAL_SETTINGS
    documented = _env_example_keys()
    assert configurable, "Settings declared no fields — config.py failed to import"

    missing = sorted(configurable - documented)

    assert not missing, (
        f"settings configurable via the environment but absent from {_ENV_EXAMPLE.name}: "
        f"{missing} — document them before merging"
    )


def test_env_example_declares_no_variable_the_application_ignores() -> None:
    """A template key matching no setting is a silent no-op the operator trusts.

    Someone sets it, the value is read by nothing, and the misconfiguration
    surfaces as behaviour that contradicts the file they configured.
    """
    documented = _env_example_keys()
    known = _settings_keys()

    unknown = sorted(documented - known)

    assert not unknown, (
        f"{_ENV_EXAMPLE.name} declares variables no Settings field reads: {unknown}"
    )
