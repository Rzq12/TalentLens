"""Construct registered agents from runtime configuration.

Agent classes stay free of environment access. This factory is the single
composition root for provider-backed agents, so registration can safely happen
at app startup even when no LLM credentials are configured.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.agents.agent import Agent
from app.agents.base import FailoverChain, LLMProvider
from app.agents.hf_provider import HFProvider
from app.agents.providers import GeminiProvider, GroqProvider
from app.config import Settings, get_settings


def build_failover_chain(settings: Settings | None = None) -> FailoverChain:
    """Build the permitted provider chain from configured non-empty keys."""
    cfg = settings or get_settings()
    providers: list[LLMProvider] = []
    if cfg.google_api_key:
        providers.append(GeminiProvider(api_key=cfg.google_api_key, model=cfg.gemini_model))
    if cfg.groq_api_key:
        providers.append(GroqProvider(api_key=cfg.groq_api_key, model=cfg.groq_model))
    if cfg.hf_api_key:
        providers.append(
            HFProvider(
                api_key=cfg.hf_api_key,
                model=cfg.hf_model,
                timeout=max(cfg.llm_timeout_seconds, 90.0),
            )
        )
    return FailoverChain(providers=providers)


def build_agent_factories(
    settings: Settings | None = None,
) -> dict[str, Callable[[], Agent[Any, Any]]]:
    """Return constructors for every registered agent."""
    from app.agents.ats_scoring import AtsScoringAgent
    from app.agents.bias_detection import BiasAgent
    from app.agents.cv_parser import CvParserAgent
    from app.agents.education_analyzer import EducationAnalyzerAgent
    from app.agents.experience_analyzer import ExperienceAnalyzerAgent
    from app.agents.fraud_detection import FraudAgent
    from app.agents.interview import InterviewAgent
    from app.agents.ocr_agent import OcrAgent
    from app.agents.recommendation import RecommendAgent
    from app.agents.semantic_matching import SemanticMatchingAgent
    from app.agents.skill_extraction import SkillExtractionAgent
    from app.agents.skill_gap import SkillGapAgent

    chain = build_failover_chain(settings)
    return {
        AtsScoringAgent.name: AtsScoringAgent,
        BiasAgent.name: lambda: BiasAgent(chain=chain),
        CvParserAgent.name: CvParserAgent,
        EducationAnalyzerAgent.name: lambda: EducationAnalyzerAgent(chain=chain),
        ExperienceAnalyzerAgent.name: lambda: ExperienceAnalyzerAgent(chain=chain),
        FraudAgent.name: lambda: FraudAgent(chain=chain),
        InterviewAgent.name: lambda: InterviewAgent(chain=chain),
        OcrAgent.name: OcrAgent,
        RecommendAgent.name: lambda: RecommendAgent(chain=chain),
        SemanticMatchingAgent.name: lambda: SemanticMatchingAgent(chain=chain),
        SkillExtractionAgent.name: lambda: SkillExtractionAgent(chain=chain),
        SkillGapAgent.name: lambda: SkillGapAgent(chain=chain),
    }
