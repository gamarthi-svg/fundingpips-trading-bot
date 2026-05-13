"""
Signal registry and strategy loader.

The ``SignalRegistry`` instantiates strategies based on the current
``BotPhase`` and aggregates signals from all active strategies.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional, Tuple, Type

import pandas as pd

from strategies.base import Signal, Strategy
from strategies.forex import ForexStrategy
from strategies.nq_futures import NqFuturesStrategy
from strategies.xauusd import XauUsdStrategy

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Re-exports for convenience
# ---------------------------------------------------------------------------
__all__ = [
    "BotPhase",
    "SignalRegistry",
    "SignalResult",
]


class BotPhase(Enum):
    """Lifecycle phase of the trading bot."""

    EVALUATION = "evaluation"
    """Challenge / evaluation phase – all strategies active."""

    FUNDED_EARLY = "funded_early"
    """Recently funded – conservative, only XAUUSD active."""

    FUNDED_SCALED = "funded_scaled"
    """Scaled funded account – all strategies active."""


@dataclass
class SignalResult:
    """A signal paired with the strategy that generated it."""

    strategy_name: str
    signal: Signal

    def __repr__(self) -> str:
        return (
            f"SignalResult(strategy={self.strategy_name!r}, "
            f"symbol={self.signal.symbol!r}, "
            f"direction={self.signal.direction.value}, "
            f"confidence={self.signal.confidence})"
        )


# ---------------------------------------------------------------------------
# Strategy configuration per phase
# ---------------------------------------------------------------------------
_PHASE_CONFIG: Dict[BotPhase, List[Type[Strategy]]] = {
    BotPhase.EVALUATION: [
        XauUsdStrategy,
        NqFuturesStrategy,
        ForexStrategy,
    ],
    BotPhase.FUNDED_EARLY: [
        XauUsdStrategy,
    ],
    BotPhase.FUNDED_SCALED: [
        XauUsdStrategy,
        NqFuturesStrategy,
        ForexStrategy,
    ],
}

# Forex symbols to instantiate when ForexStrategy is active
_FX_SYMBOLS = ["EURUSD", "GBPUSD", "USDJPY"]


class SignalRegistry:
    """
    Registry that loads and manages strategies based on the bot phase.

    Parameters
    ----------
    phase:
        The current ``BotPhase``.
    """

    def __init__(self, phase: BotPhase = BotPhase.EVALUATION) -> None:
        self.phase = phase
        self._strategies: List[Strategy] = []
        self._load_strategies()

    # ------------------------------------------------------------------
    # Strategy loading
    # ------------------------------------------------------------------
    def _load_strategies(self) -> None:
        """Instantiate all strategies permitted for the current phase."""
        strategy_classes = _PHASE_CONFIG.get(self.phase, [])
        for cls in strategy_classes:
            if cls is ForexStrategy:
                # Instantiate one ForexStrategy per supported symbol
                for sym in _FX_SYMBOLS:
                    try:
                        inst = cls(symbol=sym)
                        self._strategies.append(inst)
                        logger.info(
                            "Loaded %s for symbol %s (phase=%s)",
                            cls.__name__, sym, self.phase.value,
                        )
                    except Exception:
                        logger.exception(
                            "Failed to instantiate %s(%s)", cls.__name__, sym
                        )
            else:
                try:
                    inst = cls()
                    self._strategies.append(inst)
                    logger.info(
                        "Loaded %s (phase=%s)", cls.__name__, self.phase.value
                    )
                except Exception:
                    logger.exception("Failed to instantiate %s", cls.__name__)

        logger.info(
            "Registry initialised with %d strategy instance(s) for phase=%s",
            len(self._strategies), self.phase.value,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    @property
    def strategies(self) -> List[Strategy]:
        """Return the list of loaded strategy instances."""
        return self._strategies

    def get_signals(
        self,
        data_dict: Dict[str, pd.DataFrame],
    ) -> List[Tuple[str, Signal]]:
        """
        Iterate over all loaded strategies, generate signals, and return
        them sorted by descending confidence.

        Parameters
        ----------
        data_dict:
            Mapping from **symbol** -> ``pd.DataFrame`` of OHLCV bars.
            Each strategy looks up its symbol in this dictionary.

        Returns
        -------
        List of ``(strategy_name, signal)`` tuples sorted by
        ``signal.confidence`` descending.
        """
        results: List[Tuple[str, Signal]] = []

        for strategy in self._strategies:
            symbol = strategy.symbol
            data = data_dict.get(symbol)
            if data is None or data.empty:
                logger.debug(
                    "No data for %s (strategy=%s)", symbol, strategy.name
                )
                continue

            try:
                signal: Optional[Signal] = strategy.generate_signal(data)
            except Exception:
                logger.exception(
                    "Signal generation failed for %s", strategy.name
                )
                continue

            if signal is not None:
                signal.strategy_name = strategy.name
                results.append((strategy.name, signal))
                logger.info(
                    "Signal generated: %s %s %s @ %.5f conf=%.2f",
                    strategy.name, symbol, signal.direction.value,
                    signal.entry_price, signal.confidence,
                )

        # Sort by confidence descending
        results.sort(key=lambda item: item[1].confidence, reverse=True)

        if results:
            logger.info(
                "Registry returned %d signal(s) for phase=%s",
                len(results), self.phase.value,
            )
        else:
            logger.debug("No signals generated for phase=%s", self.phase.value)

        return results

    def __repr__(self) -> str:
        names = [s.name for s in self._strategies]
        return f"SignalRegistry(phase={self.phase.value!r}, strategies={names})"
