"""FundingPips configuration and risk profiles."""

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# =============================================================================
# FundingPips 2-Step Standard ($100K) Prop Firm Configuration
# =============================================================================

FUNDINGPIPS_CONFIG: Dict[str, Any] = {
    "account_size": 100_000,
    "evaluation": {
        "phase1_target": 0.08,      # 8% profit target
        "phase2_target": 0.05,      # 5% profit target
        "daily_loss_limit": 0.05,   # 5% max daily loss
        "max_loss_limit": 0.10,     # 10% max total loss
        "min_trading_days": 3,      # Minimum active trading days
        "time_limit": None,         # No time limit (FP rule)
    },
    "funded": {
        "daily_loss_limit": 0.05,
        "max_loss_limit": 0.10,
        "max_loss_per_trade_small": 0.03,  # <$50K accounts
        "max_loss_per_trade_large": 0.02,  # >=$50K accounts
        "consistency_score_limit": 0.35,
        "news_blackout_minutes": 5,
        "profit_split": 0.80,
    },
    "leverage": {
        "forex": 100,
        "metals": 30,
        "indices": 20,
        "energies": 10,
        "crypto": 2,
    },
    "commission": {
        "forex": 5.0,
        "metals": 5.0,
        "indices": 0.0,
    },
}

# =============================================================================
# Phase-Aware Risk Profiles
# =============================================================================

# =============================================================================
# MetaAPI Cloud Configuration Defaults
# =============================================================================

METAAPI_DEFAULTS: Dict[str, Any] = {
    "provider_type": "metaapi",  # "mt5" or "metaapi"
    "token": "",  # MetaAPI token from https://app.metaapi.cloud/token
    "account_id": "",  # MetaAPI account ID
    # MT5 credentials still needed for MetaAPI (it connects to your broker via MT5)
    "mt_login": 0,
    "mt_password": "",
    "mt_server": "",
}


RISK_PROFILES: Dict[str, Dict[str, Any]] = {
    "eval_phase1": {
        "risk_per_trade": 0.005,
        "daily_loss_buffer": 0.80,
        "max_positions": 3,
        "profit_target": 0.08,
        "session_filter": "all",
        "consistency_cap": None,
    },
    "eval_phase2": {
        "risk_per_trade": 0.005,
        "daily_loss_buffer": 0.80,
        "max_positions": 3,
        "profit_target": 0.05,
        "session_filter": "all",
        "consistency_cap": None,
    },
    "funded_early": {
        "risk_per_trade": 0.003,
        "daily_loss_buffer": 0.75,
        "max_positions": 2,
        "profit_target": None,
        "session_filter": "conservative",
        "consistency_cap": 0.25,
    },
    "funded_scaled": {
        "risk_per_trade": 0.004,
        "daily_loss_buffer": 0.80,
        "max_positions": 3,
        "profit_target": None,
        "session_filter": "moderate",
        "consistency_cap": 0.30,
    },
}


@dataclass
class BotConfig:
    """Typed container for the merged bot configuration."""

    fundingpips: Dict[str, Any] = field(default_factory=lambda: FUNDINGPIPS_CONFIG)
    risk_profiles: Dict[str, Dict[str, Any]] = field(
        default_factory=lambda: RISK_PROFILES
    )
    user: Dict[str, Any] = field(default_factory=dict)

    @property
    def account_size(self) -> float:
        """Return the funded account size in base currency."""
        return float(self.fundingpips.get("account_size", 100_000))

    @property
    def leverage(self) -> Dict[str, int]:
        """Return leverage map by asset class."""
        return dict(self.fundingpips.get("leverage", {}))

    @property
    def commission(self) -> Dict[str, float]:
        """Return commission map by asset class (per round-turn lot)."""
        return dict(self.fundingpips.get("commission", {}))

    def get_risk_profile(self, phase: str) -> Dict[str, Any]:
        """Return the risk profile for a given phase name.

        Args:
            phase: Phase identifier (e.g. ``"eval_phase1"``).

        Returns:
            Risk-profile dictionary. Falls back to ``eval_phase1`` if *phase*
            is unknown.
        """
        profile = self.risk_profiles.get(phase)
        if profile is None:
            logger.warning(
                "No risk profile for phase %r; falling back to eval_phase1", phase
            )
            profile = self.risk_profiles["eval_phase1"]
        return dict(profile)


def load_config(path: str = "config.json") -> BotConfig:
    """Load configuration from a JSON file with fallback to defaults.

    The JSON file, when present, is merged under the ``user`` key so that
    user-defined values can override built-in defaults programmatically.

    Args:
        path: Filesystem path to the optional JSON config file.

    Returns:
        A fully populated :class:`BotConfig` instance.
    """
    config_path = Path(path)
    bot_config = BotConfig()

    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as fh:
                user_data: Dict[str, Any] = json.load(fh)
            bot_config.user = user_data
            logger.info("Loaded user config from %s", path)
        except (json.JSONDecodeError, OSError, TypeError) as exc:
            logger.warning("Failed to load %s: %s. Using defaults.", path, exc)
    else:
        logger.info("%s not found. Using built-in defaults.", path)

    return bot_config
