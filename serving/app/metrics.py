"""Prometheus metrics — per-agent and per-endpoint instrumentation.

Single module, one registry. Every counter, histogram, and gauge is
declared here so they are importable from anywhere without creating
a second registry.
"""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram, Info

NAMESPACE = "talentlens"

# --- API -------------------------------------------------------------------

http_requests_total = Counter(
    "http_requests_total",
    "Total HTTP requests processed",
    ["method", "path", "status_code"],
    namespace=NAMESPACE,
)

http_request_duration_seconds = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration in seconds",
    ["method", "path"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
    namespace=NAMESPACE,
)

# --- Agents ----------------------------------------------------------------

agent_invocations_total = Counter(
    "agent_invocations_total",
    "Total agent invocations",
    ["agent_name", "agent_version", "status"],
    namespace=NAMESPACE,
)

agent_duration_seconds = Histogram(
    "agent_duration_seconds",
    "Agent execution duration",
    ["agent_name", "agent_version"],
    buckets=(0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0),
    namespace=NAMESPACE,
)

agent_cache_hits_total = Counter(
    "agent_cache_hits_total",
    "Agent result cache hits",
    ["agent_name"],
    namespace=NAMESPACE,
)

agent_cache_misses_total = Counter(
    "agent_cache_misses_total",
    "Agent result cache misses",
    ["agent_name"],
    namespace=NAMESPACE,
)

# --- LLM -------------------------------------------------------------------

llm_tokens_used_total = Counter(
    "llm_tokens_used_total",
    "Total LLM tokens consumed",
    ["provider", "model", "direction"],
    namespace=NAMESPACE,
)

llm_rate_limit_reschedules_total = Counter(
    "llm_rate_limit_reschedules_total",
    "Rate-limit reschedules (expected non-zero in free-tier operation)",
    ["provider", "model"],
    namespace=NAMESPACE,
)

llm_provider_errors_total = Counter(
    "llm_provider_errors_total",
    "Provider errors by kind",
    ["provider", "model", "kind"],
    namespace=NAMESPACE,
)

# --- Screening --------------------------------------------------------------

screening_runs_active = Gauge(
    "screening_runs_active",
    "Currently active screening runs",
    namespace=NAMESPACE,
)

candidates_scored_total = Counter(
    "candidates_scored_total",
    "Total candidates scored",
    namespace=NAMESPACE,
)

# --- Application ------------------------------------------------------------

app_info = Info(
    "app",
    "Application metadata",
    namespace=NAMESPACE,
)
