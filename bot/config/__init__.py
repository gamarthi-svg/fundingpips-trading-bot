"""Configuration package for the prop-firm trading bot.

Provides FundingPips-specific settings, phase-aware risk profiles,
and the evaluation-to-funded phase state machine.
"""

from config.settings import (
    BotConfig,
    FUNDINGPIPS_CONFIG,
    RISK_PROFILES,
    load_config,
)
from config.phases import (
    AccountInfo,
    BotPhase,
    PhaseManager,
)

__all__ = [
    "AccountInfo",
    "BotConfig",
    "BotPhase",
    "FUNDINGPIPS_CONFIG",
    "PhaseManager",
    "RISK_PROFILES",
    "load_config",
]
