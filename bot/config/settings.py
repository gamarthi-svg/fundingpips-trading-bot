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
# The5%ers 5K Bootcamp (3-Step) Configuration
# =============================================================================

THE5ERS_CONFIG: Dict[str, Any] = {
    "account_size": 5_000,
    "evaluation": {
        "phase1_target": 0.06,      # 6% profit target ($300)
        "phase2_target": 0.05,      # 5% profit target ($250)
        "phase3_target": 0.00,      # No target (Funded)
        "daily_loss_limit": 0.03,   # 3% max daily loss ($150)
        "max_loss_limit": 0.06,     # 6% max total loss ($300)
        "min_trading_days": 4,      # Per phase
        "time_limit": None,         # No time limit
    },
    "funded": {
        "daily_loss_limit": 0.03,
        "max_loss_limit": 0.05,     # 5% max DD in funded
        "max_loss_per_trade": 0.02,  # 2% max per trade
        "consistency_score_limit": 0.35,
        "profit_split": 0.50,
        "scaling_plan": True,
    },
    "leverage": {
        "forex": 100,
        "metals": 30,
        "indices": 20,
    },
    "commission": {
        "forex": 0.0,
        "metals": 0.0,
    },
    "three_step_challenge": True,  # Distinct from 2-step
}

# ── Prop Firm Registry ──
PROP_FIRMS: Dict[str, Dict[str, Any]] = {
    "fundingpips": FUNDINGPIPS_CONFIG,
    "the5ers": THE5ERS_CONFIG,
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
    the5ers: Dict[str, Any] = field(default_factory=lambda: THE5ERS_CONFIG)
    risk_profiles: Dict[str, Dict[str, Any]] = field(
        default_factory=lambda: RISK_PROFILES
    )
    user: Dict[str, Any] = field(default_factory=dict)

    # ── Prop Firm Selection ──

    def _get_firm_config(self, firm: Optional[str] = None) -> Dict[str, Any]:
        """Return the config dict for the named prop firm (or default)."""
        firm = firm or self.user.get("prop_firm", "fundingpips")
        config = PROP_FIRMS.get(firm)
        if config is None:
            logger.warning(
                "Unknown prop firm %r; falling back to fundingpips", firm
            )
            config = FUNDINGPIPS_CONFIG
        return config

    @property
    def account_size(self, firm: Optional[str] = None) -> float:
        """Return the funded account size in base currency."""
        return float(self._get_firm_config(firm).get("account_size", 100_000))

    @property
    def leverage(self, firm: Optional[str] = None) -> Dict[str, int]:
        """Return leverage map by asset class."""
        return dict(self._get_firm_config(firm).get("leverage", {}))

    @property
    def commission(self, firm: Optional[str] = None) -> Dict[str, float]:
        """Return commission map by asset class (per round-turn lot)."""
        return dict(self._get_firm_config(firm).get("commission", {}))

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

    # ── Prop-Firm Helpers ──

    def get_limits(self, firm: Optional[str] = None, phase: Optional[str] = None) -> Dict[str, float]:
        """Return prop-firm risk limits for the current phase.

        Returns a flat dict with keys like ``daily_dd_pct``,
        ``max_dd_pct``, ``profit_target_pct``.
        """
        config = self._get_firm_config(firm)
        eval_cfg = config.get("evaluation", {})
        funded_cfg = config.get("funded", {})

        # Phase-aware limits
        phase = phase or "phase1"
        if phase in ("phase1", "phase2"):
            target_key = f"{phase}_target"
            return {
                "daily_dd_pct": eval_cfg.get("daily_loss_limit", 0.05),
                "max_dd_pct": eval_cfg.get("max_loss_limit", 0.10),
                "profit_target_pct": eval_cfg.get(target_key, 0.08),
                "max_loss_per_trade_pct": eval_cfg.get("max_loss_per_trade", 0.02),
            }
        # Funded
        return {
            "daily_dd_pct": funded_cfg.get("daily_loss_limit", 0.03),
            "max_dd_pct": funded_cfg.get("max_loss_limit", 0.05),
            "profit_target_pct": 0.0,
            "max_loss_per_trade_pct": funded_cfg.get("max_loss_per_trade", 0.02),
        }


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
