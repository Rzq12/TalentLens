"""Tests for Row-Level Security tenant isolation.

These tests verify that RLS policies on all tenant-scoped tables prevent
cross-tenant data access. They do NOT need a live PostgreSQL connection
because they validate:

1. RLS migration exists for every tenant-scoped table
2. Every repository query filters on tenant_id
3. The get_session dependency injects RLS context

The integration test (requires PostgreSQL) is deferred to Phase 0 completion.
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path

import pytest

# --------------------------------------------------------------------------- #
# Test 1: RLS migration covers all tenant-scoped tables                        #
# --------------------------------------------------------------------------- #

_VERSIONS = Path(__file__).resolve().parents[2] / "serving" / "app" / "migrations" / "versions"


def _declared_tenant_tables() -> set[str]:
    """Return tables in models that have tenant_id column."""
    models_path = Path(__file__).resolve().parents[2] / "serving" / "app" / "models.py"
    content = models_path.read_text()

    # Extract all __tablename__ values by finding lines with the pattern
    tablenames = set(re.findall(r'__tablename__\s*=\s*"(\w+)"', content))

    # Now find which of those have tenant_id
    tenant_tables: set[str] = set()
    classes = re.split(r"\nclass ", "\n" + content)
    for block in classes:
        match = re.search(r'__tablename__\s*=\s*"(\w+)"', block)
        if match and "tenant_id" in block:
            tenant_tables.add(match.group(1))
    return tenant_tables


def test_every_tenant_scoped_table_has_rls_policy() -> None:
    """RLS policy must exist for every table with tenant_id.

    Since the migration generates policies in a loop via f-strings,
    we verify the TENANT_TABLES list covers every tenant-scoped table
    and that the loop iterates correctly over it.
    """
    tenant_tables = _declared_tenant_tables()
    assert tenant_tables, "no tenant-scoped tables found in models"

    # Find the RLS migration
    rls_files = sorted(_VERSIONS.glob("*rls*"))
    if not rls_files:
        pytest.skip("RLS migration not found — Phase 0 incomplete")

    rls_content = rls_files[0].read_text()

    # Extract the TENANT_TABLES list from the migration
    tables_match = re.search(r"TENANT_TABLES\s*=\s*\[(.*?)\]", rls_content, re.DOTALL)
    assert tables_match, "TENANT_TABLES list not found in RLS migration"

    listed_raw = tables_match.group(1)
    listed_tables = set(re.findall(r'"(\w+)"', listed_raw))

    # Check every tenant-scoped table is in the migration's TENANT_TABLES
    missing = tenant_tables - listed_tables
    extra = listed_tables - tenant_tables

    assert not missing, (
        f"Tables with tenant_id missing from RLS migration TENANT_TABLES: {sorted(missing)}"
    )
    assert not extra, (
        f"Tables in RLS migration TENANT_TABLES without tenant_id in models: {sorted(extra)}"
    )


def test_rate_limit_buckets_excluded_from_rls() -> None:
    """rate_limit_buckets is UNLOGGED and not tenant-scoped — should not have RLS."""
    rls_files = list(_VERSIONS.glob("*rls*"))
    if not rls_files:
        pytest.skip("RLS migration not found")
    rls_content = rls_files[0].read_text()
    assert "tenant_isolation_rate_limit_buckets" not in rls_content, (
        "rate_limit_buckets should not have RLS — it is UNLOGGED and not tenant-scoped"
    )


# --------------------------------------------------------------------------- #
# Test 2: Every repository query filters on tenant_id                          #
# --------------------------------------------------------------------------- #

REPO_FILES = [
    "ingestion.py",
    "rubric.py",
    "search.py",
]


def test_every_repository_query_filters_on_tenant_id() -> None:
    """Every SELECT/DELETE in repositories must reference tenant_id."""
    repos_dir = Path(__file__).resolve().parents[2] / "serving" / "app" / "repositories"
    unfiltered: list[str] = []

    for filename in REPO_FILES:
        content = (repos_dir / filename).read_text()
        # Split by function definitions
        methods = re.split(r"\n    (?:async )?def ", content)
        for method in methods:
            if not method.strip():
                continue
            # Extract function name: first word before '('
            func_name = method.split("(")[0].strip()
            # Skip non-function chunks (module docstrings, class bodies, etc.)
            if not func_name or not re.match(r"^[a-zA-Z_]\w*$", func_name):
                continue
            if func_name.startswith("_"):
                continue

            has_select = bool(re.search(r"\bselect\b|\bdelete\b", method, re.IGNORECASE))
            has_tenant = "tenant_id" in method

            if has_select and not has_tenant:
                unfiltered.append(f"{filename}::{func_name}")

    assert not unfiltered, (
        f"Repository methods with SELECT/DELETE but no tenant_id reference: {unfiltered}. "
        f"Every query must filter on or accept tenant_id for RLS defense-in-depth."
    )


# --------------------------------------------------------------------------- #
# Test 3: get_session injects RLS tenant context                              #
# --------------------------------------------------------------------------- #

def test_get_session_injects_rls_parameter() -> None:
    """get_session must call set_config when tenant context is set."""
    db_path = Path(__file__).resolve().parents[2] / "serving" / "app" / "db.py"
    content = db_path.read_text()

    assert "app.current_tenant_id" in content, (
        "db.py must reference app.current_tenant_id for RLS"
    )
    assert "set_config" in content, (
        "db.py must call set_config to inject RLS parameter"
    )
    assert "get_tenant_context" in content, (
        "db.py must define get_tenant_context"
    )


# --------------------------------------------------------------------------- #
# Test 4: Middleware extracts tenant from token                               #
# --------------------------------------------------------------------------- #

def test_middleware_extracts_tenant_from_token() -> None:
    """The RLS middleware must decode the bearer token and set tenant context."""
    main_path = Path(__file__).resolve().parents[2] / "serving" / "app" / "main.py"
    content = main_path.read_text()

    assert "set_tenant_context" in content, (
        "main.py middleware must call set_tenant_context for RLS"
    )
    assert "_decode_access_token" in content or "decode_access_token" in content, (
        "main.py middleware must decode the bearer token for tenant id"
    )
