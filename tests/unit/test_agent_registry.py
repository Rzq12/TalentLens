"""Startup wiring tests for registered screening agents."""

from __future__ import annotations


def test_registered_agents_can_be_resolved_without_provider_keys() -> None:
    """Missing LLM keys must not make app startup or agent resolution fail."""
    from app.main import create_app
    from app.routers.screening import get_registry

    create_app()
    registry = get_registry()

    for registered in registry.list_agents():
        name = registered.split("@", maxsplit=1)[0]
        assert registry.resolve(name).name == name


def test_semantic_matching_receives_an_empty_chain_when_unconfigured() -> None:
    """Provider absence fails only at an LLM invocation, never during startup."""
    from app.main import create_app
    from app.routers.screening import get_registry

    create_app()
    assert get_registry().resolve("semantic_matching").chain.providers == []
