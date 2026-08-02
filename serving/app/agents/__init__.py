"""LLM adapters and the failover policy that chooses between them.

This package is the only place in the application permitted to hold a provider
API key or speak a provider's wire format. Everything above it works with
:class:`app.agents.base.LLMRequest` and :class:`app.agents.base.LLMResponse`,
so swapping a deprecated free-tier model is a config change rather than a
rewrite.

Per the layering rule, modules here may call ``utils/`` but never
``repositories/``: an adapter that could reach the database would make a
judge's answer depend on state the caller cannot see.
"""

from __future__ import annotations
