"""Phase state machine for evaluation-to-funded transitions."""

from enum import Enum, auto
from dataclasses import dataclass
from typing import Optional, Dict, Any
import logging

logger = logging.getLogger(__name__)


# =============================================================================
# Enumerations
# =============================================================================

class BotPhase(Enum):
    """Discrete lifecycle phases of the prop-firm trading bot.

    Attributes:
        CONFIG: Initial setup phase before trading begins.
        EVAL_P1: Evaluation Phase 1 (profit target: 8%).
        EVAL_P2: Evaluation Phase 2 (profit target: 5%).
        FUNDED_EARLY: Recently funded — reduced risk, strict consistency.
        FUNDED_SCALED: Scaled-up funded account with wider limits.
        PAUSED: Trading temporarily suspended (e.g. maintenance).
        EMERGENCY: Kill-switch triggered — all trading halted.
    """

    CONFIG = "config"
    EVAL_P1 = "eval_phase1"
    EVAL_P2 = "eval_phase2"
    FUNDED_EARLY = "funded_early"
    FUNDED_SCALED = "funded_scaled"
    PAUSED = "paused"
    EMERGENCY = "emergency"


# =============================================================================
# Data Containers
# =============================================================================

@dataclass
class AccountInfo:
    """Snapshot of account metrics as reported by the broker / platform.

    Attributes:
        balance: Cash balance excluding open PnL.
        equity: Balance + open PnL (net liquidation value).
        profit: Floating profit/loss of all open positions.
        margin: Margin currently used by open positions.
        free_margin: Equity - margin.
    """

    balance: float
    equity: float
    profit: float
    margin: float
    free_margin: float


# =============================================================================
# Phase Manager
# =============================================================================

class PhaseManager:
    """Manages bot phase transitions for FundingPips 2-step evaluation.

    The manager auto-detects phase transitions by comparing live account
    equity against profit targets.  It can also be forced into a specific
    phase for back-testing or manual override.

    Args:
        account_size: Starting account balance in base currency.
    """

    def __init__(self, account_size: float = 100_000):
        self.account_size: float = account_size
        self.current_phase: BotPhase = BotPhase.CONFIG
        self.phase_changed: bool = False

        # Phase-specific profit targets
        self._p1_target: float = account_size * 1.08   # 8 % profit
        self._p2_target: float = account_size * 1.05   # 5 % profit
        self._eval_start: float = account_size

    # ------------------------------------------------------------------
    # Core logic
    # ------------------------------------------------------------------

    def update(self, account: AccountInfo) -> None:
        """Auto-detect phase transitions from live account metrics.

        Rules:
            * CONFIG   -> EVAL_P1       immediately.
            * EVAL_P1  -> EVAL_P2       on 8 % equity gain.
            * EVAL_P2  -> FUNDED_EARLY  on 5 % equity gain.
            * FUNDED_EARLY -> FUNDED_SCALED after $50 K cumulative profit.

        Args:
            account: Current account snapshot.
        """
        prev = self.current_phase

        if self.current_phase == BotPhase.CONFIG:
            self.current_phase = BotPhase.EVAL_P1

        elif self.current_phase == BotPhase.EVAL_P1:
            if account.equity >= self._p1_target:
                self.current_phase = BotPhase.EVAL_P2
                self._eval_start = account.equity
                self._p2_target = account.equity * 1.05
                logger.info(
                    "Phase 1 target reached: equity=%.2f  p2_target=%.2f",
                    account.equity,
                    self._p2_target,
                )

        elif self.current_phase == BotPhase.EVAL_P2:
            if account.equity >= self._p2_target:
                self.current_phase = BotPhase.FUNDED_EARLY
                logger.info(
                    "Phase 2 target reached: equity=%.2f -> FUNDED_EARLY",
                    account.equity,
                )

        elif self.current_phase == BotPhase.FUNDED_EARLY:
            if abs(account.profit) > self.account_size * 0.5:
                self.current_phase = BotPhase.FUNDED_SCALED
                logger.info(
                    "Cumulative profit > 50%% of account -> FUNDED_SCALED"
                )

        self.phase_changed = self.current_phase != prev
        if self.phase_changed:
            logger.info(
                "Phase transition: %s -> %s", prev.value, self.current_phase.value
            )

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def is_evaluation(self) -> bool:
        """Return ``True`` while in either evaluation phase."""
        return self.current_phase in (BotPhase.EVAL_P1, BotPhase.EVAL_P2)

    @property
    def is_funded(self) -> bool:
        """Return ``True`` once the account is fully funded."""
        return self.current_phase in (
            BotPhase.FUNDED_EARLY,
            BotPhase.FUNDED_SCALED,
        )

    @property
    def profit_target(self) -> Optional[float]:
        """Return the next profit-target equity level, if applicable."""
        if self.current_phase == BotPhase.EVAL_P1:
            return self._p1_target
        elif self.current_phase == BotPhase.EVAL_P2:
            return self._p2_target
        return None

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    def force_phase(self, phase: BotPhase) -> None:
        """Manually override the current phase (testing / recovery).

        Args:
            phase: Desired target phase.
        """
        prev = self.current_phase
        self.current_phase = phase
        self.phase_changed = self.current_phase != prev
        logger.info("Phase forced: %s -> %s", prev.value, phase.value)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize manager state for persistence or logging."""
        return {
            "account_size": self.account_size,
            "current_phase": self.current_phase.value,
            "p1_target": self._p1_target,
            "p2_target": self._p2_target,
            "eval_start": self._eval_start,
        }
