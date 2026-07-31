"""Security regression tests for ChunkRepository SQL construction.

CLAUDE.md mandates: 'Gunakan parameterized query — TIDAK BOLEH string formatting
untuk SQL'. ``search_dense`` and ``search_lexical`` once built their WHERE clauses
with f-string interpolation; they now emit fully static ``text()`` literals chosen
by branching, with every value passed as a bind parameter.

These tests pin that property structurally rather than by pattern-matching the
one syntax that was fixed. Every ``text(...)`` call in the module is parsed from
the AST and required to receive a plain string constant, so *any* dynamic SQL —
f-string, ``%``, ``.format()``, concatenation, or a string hoisted to a local and
passed by name — fails the assertion regardless of how it is spelled.
"""

from __future__ import annotations

import ast
import inspect

import app.repositories.search as search_module


def _text_call_arguments() -> list[tuple[int, ast.expr]]:
    """Collect the first argument of every ``text(...)`` call in the search module.

    Returns:
        List of ``(line_number, argument_node)`` pairs, one per ``text()`` call.
    """
    tree = ast.parse(inspect.getsource(search_module))

    calls: list[tuple[int, ast.expr]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
        if name == "text" and node.args:
            calls.append((node.lineno, node.args[0]))

    return calls


def test_module_contains_text_calls_to_inspect() -> None:
    """Guard against the other tests passing vacuously if the SQL is refactored away."""
    calls = _text_call_arguments()

    assert calls, (
        "no text() calls found in app.repositories.search — the SQL construction "
        "tests below would pass vacuously; update them to match the new structure"
    )


def test_every_text_call_receives_a_static_string_literal() -> None:
    """No ``text()`` call may build its SQL dynamically.

    A plain ``ast.Constant`` string is the only accepted argument. This rejects
    f-strings (``ast.JoinedStr``), concatenation and ``%`` formatting
    (``ast.BinOp``), ``.format()`` (``ast.Call``), and any SQL assembled into a
    variable and passed by name (``ast.Name``).
    """
    offenders: list[str] = []

    for lineno, arg in _text_call_arguments():
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            continue
        offenders.append(f"line {lineno}: text() received {type(arg).__name__}")

    assert not offenders, (
        "dynamic SQL construction detected in app.repositories.search — "
        "CLAUDE.md requires parameterized queries only: " + "; ".join(offenders)
    )


def test_no_sql_literal_contains_an_interpolation_placeholder() -> None:
    """Static literals must not carry ``{}`` placeholders awaiting a later format call."""
    offenders: list[str] = []

    for lineno, arg in _text_call_arguments():
        if not (isinstance(arg, ast.Constant) and isinstance(arg.value, str)):
            continue
        if "{" in arg.value or "}" in arg.value:
            offenders.append(f"line {lineno}")

    assert not offenders, (
        "SQL literal contains a brace placeholder, suggesting deferred string "
        "formatting: " + ", ".join(offenders)
    )


def test_every_sql_literal_filters_on_tenant_id() -> None:
    """Tenant isolation must live inside the static SQL, not in caller discipline.

    Every raw query in this module reads tenant-scoped rows, so each literal has
    to bind ``tenant_id`` itself — a predicate a caller cannot forget to apply.
    """
    offenders: list[str] = []

    for lineno, arg in _text_call_arguments():
        if not (isinstance(arg, ast.Constant) and isinstance(arg.value, str)):
            continue
        if ":tenant_id" not in arg.value:
            offenders.append(f"line {lineno}")

    assert not offenders, (
        "SQL literal does not filter on :tenant_id, risking cross-tenant reads: "
        + ", ".join(offenders)
    )


def test_search_methods_pass_document_id_as_a_bind_parameter() -> None:
    """``document_id`` must reach SQL as a bind param, never as interpolated text.

    This was the original defect: both methods spliced ``document_id`` into the
    WHERE clause. The fix branches between two static literals instead, so the
    value can only travel through the params dict.
    """
    methods = (
        search_module.ChunkRepository.search_dense,
        search_module.ChunkRepository.search_lexical,
    )
    for method in methods:
        source = inspect.getsource(method)

        assert ":document_id" in source, (
            f"{method.__name__} does not bind :document_id — verify the filter is "
            "still parameterized"
        )
        assert "f\"" not in source and "f'" not in source, (
            f"{method.__name__} contains an f-string; SQL in this module must be static"
        )
