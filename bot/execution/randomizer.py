"""
ExecutionRandomizer - Prop-firm trade randomization utilities.

Adds small random variations to lot sizes, delays, SL/TP offsets and
partial ratios in order to reduce predictability and avoid flagging
by prop-firm surveillance systems.
"""

from __future__ import annotations

import logging
import random
import time
from typing import List

logger = logging.getLogger(__name__)


class ExecutionRandomizer:
    """Randomizer for trade execution parameters.

    Prop firms monitor for robotic trading patterns.  This class applies
    small, configurable random perturbations to order parameters so that
    consecutive trades from the same strategy do not look identical.
    """

    def __init__(
        self,
        lot_variance_pct: float = 0.05,
        min_delay_sec: float = 2.0,
        max_delay_sec: float = 15.0,
        sl_variance_pct: float = 0.10,
        tp_variance_pct: float = 0.05,
        seed: int | None = None,
    ) -> None:
        """Initialize the randomizer with variance bounds.

        Args:
            lot_variance_pct: Maximum lot-size deviation as a fraction (e.g. 0.05 = +-5%).
            min_delay_sec: Minimum pre-trade delay in seconds.
            max_delay_sec: Maximum pre-trade delay in seconds.
            sl_variance_pct: Maximum SL-offset deviation as a fraction (e.g. 0.10 = +-10%).
            tp_variance_pct: Maximum partial-ratio deviation as a fraction (e.g. 0.05 = +-5%).
            seed: Optional random seed for reproducibility in tests.
        """
        self._lot_var = lot_variance_pct
        self._min_delay = min_delay_sec
        self._max_delay = max_delay_sec
        self._sl_var = sl_variance_pct
        self._tp_var = tp_variance_pct

        if seed is not None:
            random.seed(seed)
            logger.debug("ExecutionRandomizer seeded with %d", seed)

    # ------------------------------------------------------------------ #
    # Lot size
    # ------------------------------------------------------------------ #

    def randomize_lot_size(self, base_lot: float) -> float:
        """Return a lot size within +-lot_variance_pct of *base_lot*.

        The result is rounded to the nearest 0.01 lot to stay compatible
        with most MT5 broker lot-step requirements.

        Args:
            base_lot: The nominal lot size computed by risk management.

        Returns:
            Slightly perturbed lot size.
        """
        if base_lot <= 0:
            logger.warning("base_lot <= 0 (%f), returning unchanged", base_lot)
            return base_lot

        deviation = random.uniform(-self._lot_var, self._lot_var)
        randomized = base_lot * (1.0 + deviation)
        rounded = round(randomized, 2)
        logger.debug(
            "Lot randomized %.4f -> %.4f (dev=%+.2f%%)",
            base_lot,
            rounded,
            deviation * 100,
        )
        return max(rounded, 0.01)

    # ------------------------------------------------------------------ #
    # Delay
    # ------------------------------------------------------------------ #

    def randomize_delay(self) -> float:
        """Return a random delay in seconds and optionally sleep for it.

        Returns:
            The chosen delay value (seconds).
        """
        delay = random.uniform(self._min_delay, self._max_delay)
        logger.debug("Execution delay: %.2f seconds", delay)
        return delay

    def sleep_random_delay(self) -> None:
        """Sleep for a randomized duration between *min_delay* and *max_delay*."""
        delay = self.randomize_delay()
        time.sleep(delay)

    # ------------------------------------------------------------------ #
    # Stop-loss offset
    # ------------------------------------------------------------------ #

    def randomize_sl_offset(self, base_offset: float) -> float:
        """Return a stop-loss offset perturbed by +-sl_variance_pct.

        Args:
            base_offset: The nominal SL distance in price units (points/pips).

        Returns:
            Slightly perturbed SL offset.
        """
        if base_offset <= 0:
            logger.warning("base_offset <= 0 (%f), returning unchanged", base_offset)
            return base_offset

        deviation = random.uniform(-self._sl_var, self._sl_var)
        randomized = base_offset * (1.0 + deviation)
        logger.debug(
            "SL offset randomized %.2f -> %.2f (dev=%+.2f%%)",
            base_offset,
            randomized,
            deviation * 100,
        )
        return randomized

    # ------------------------------------------------------------------ #
    # Take-profit partial ratios
    # ------------------------------------------------------------------ #

    def randomize_tp_partials(self, ratios: List[float]) -> List[float]:
        """Perturb a list of TP partial-close ratios by +-tp_variance_pct.

        The returned list is normalised so the ratios still sum to 1.0
        (within floating-point tolerance).

        Args:
            ratios: Nominal partial-close ratios, e.g. [0.5, 0.3, 0.2].

        Returns:
            Perturbed ratios that still sum to 1.0.
        """
        if not ratios:
            logger.warning("Empty ratios list, returning as-is")
            return ratios

        perturbed: List[float] = []
        for r in ratios:
            deviation = random.uniform(-self._tp_var, self._tp_var)
            new_val = r * (1.0 + deviation)
            perturbed.append(max(new_val, 0.01))

        total = sum(perturbed)
        if total > 0:
            normalized = [round(p / total, 4) for p in perturbed]
        else:
            normalized = perturbed

        logger.debug(
            "TP partials %s -> %s", ratios, normalized
        )
        return normalized
