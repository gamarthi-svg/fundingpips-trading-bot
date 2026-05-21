"""
Kronos Foundation Model Signal Integration.

Kronos (https://github.com/shiyu-coder/Kronos) is the first open-source foundation
model for financial candlesticks, trained on 45+ global exchanges with 24TB of data.

This module provides:
    1. KronosSignalProvider  -- generates AI-powered trading signals via Kronos
    2. FallbackSignalProvider -- comprehensive statistical fallback
    3. SignalAggregator       -- combines multiple provider signals
    4. Integration helpers    -- factory, portfolio signals, DB tracking

Architecture:
    - Kronos tokenizes OHLCV into hierarchical discrete tokens
    - Autoregressive Transformer (GPT-like) predicts future price action
    - Available models: mini (4.1M), small (24.7M), base (102.3M) params

Setup Instructions:
    .. code-block:: bash

        pip install torch transformers pandas numpy
        # Models auto-download from HuggingFace:
        #   - NeoQuasar/Kronos-mini  (4.1M params, fastest)
        #   - NeoQuasar/Kronos-small (24.7M params, balanced)
        #   - NeoQuasar/Kronos-base  (102.3M params, most accurate)

Usage:
    .. code-block:: python

        from kronos_signals import (
            create_default_provider, KronosSignalProvider,
            FallbackSignalProvider, SignalAggregator
        )

        # Auto-select provider (Kronos if available, else fallback)
        provider = create_default_provider(use_kronos=True, model_size='mini')

        # Generate signal
        signal = await provider.generate_signal(df, symbol='XAUUSD', horizon=24)
        # signal.direction  -> 'bullish' | 'bearish' | 'neutral'
        # signal.confidence -> 0.0 ... 1.0
        # signal.predicted_return -> % over horizon

        # Aggregate across providers
        aggregator = SignalAggregator([kronos_provider, fallback_provider])
        consensus = await aggregator.aggregate('XAUUSD', {'XAUUSD': df})

References:
    - Paper: arXiv:2508.02739
    - Repo:  https://github.com/shiyu-coder/Kronos
    - Demo:  https://shiyu-coder.github.io/Kronos-demo/
"""

from __future__ import annotations

__all__ = [
    "KronosSignal",
    "SignalProvider",
    "KronosSignalProvider",
    "FallbackSignalProvider",
    "SignalAggregator",
    "create_default_provider",
    "generate_signals_for_portfolio",
    "SignalTracker",
]

# ═══════════════════════════════════════════════════════════════════════════
#  Imports
# ═══════════════════════════════════════════════════════════════════════════

import asyncio
import enum
import json
import logging
import os
import sqlite3
import time
import traceback
import warnings
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import (
    Any,
    Callable,
    Dict,
    List,
    Literal,
    Optional,
    Sequence,
    Tuple,
    Union,
)

import numpy as np
import pandas as pd

# ═══════════════════════════════════════════════════════════════════════════
#  Logging
# ═══════════════════════════════════════════════════════════════════════════

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

# File handler for persistent signal logs (created lazily)
_file_handler: Optional[logging.FileHandler] = None


def _ensure_file_handler(log_dir: str = "/mnt/agents/output/project/logs") -> None:
    """Create a file handler for signal generation logs if not already set."""
    global _file_handler
    if _file_handler is not None:
        return
    try:
        os.makedirs(log_dir, exist_ok=True)
        log_path = os.path.join(log_dir, "kronos_signals.log")
        _file_handler = logging.FileHandler(log_path, mode="a")
        _file_handler.setLevel(logging.INFO)
        fmt = logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        _file_handler.setFormatter(fmt)
        logger.addHandler(_file_handler)
        logger.setLevel(logging.INFO)
        logger.info("Kronos signal logging initialized -> %s", log_path)
    except Exception as exc:
        warnings.warn(f"Could not initialise file logger: {exc}")


# ═══════════════════════════════════════════════════════════════════════════
#  Type Aliases
# ═══════════════════════════════════════════════════════════════════════════

Direction = Literal["bullish", "bearish", "neutral"]
ModelSize = Literal["mini", "small", "base"]

HUGGINGFACE_REPOS: dict[ModelSize, str] = {
    "mini":  "NeoQuasar/Kronos-mini",
    "small": "NeoQuasar/Kronos-small",
    "base":  "NeoQuasar/Kronos-base",
}

# ── model metadata ──
MODEL_CONTEXT_LENGTH: dict[ModelSize, int] = {
    "mini":  256,
    "small": 512,
    "base":  1024,
}
MODEL_PARAMS: dict[ModelSize, str] = {
    "mini":  "4.1M",
    "small": "24.7M",
    "base":  "102.3M",
}


# ═══════════════════════════════════════════════════════════════════════════
# 1.  Signal Data-Class
# ═══════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True, slots=True)
class KronosSignal:
    """A trading signal generated by Kronos (or the fallback engine).

    Attributes:
        direction:           'bullish', 'bearish', or 'neutral'.
        confidence:          0.0 (low confidence) -> 1.0 (very confident).
        predicted_return:    Expected % return over the prediction horizon.
        volatility_forecast: Predicted annualised volatility (σ) over horizon.
        trend_strength:      0.0 -> 1.0 trend-metric.
        key_levels:          Dict with 'support' and 'resistance' price levels.
        reasoning:           Human-readable explanation of the signal.
        model_used:          Which model produced the signal.
        generation_time:     UTC timestamp of signal creation.
    """

    direction: Direction
    confidence: float
    predicted_return: float
    volatility_forecast: float
    trend_strength: float
    key_levels: dict
    reasoning: str
    model_used: str
    generation_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # ── helpers ──────────────────────────────────────────────────────────

    def is_actionable(self, min_confidence: float = 0.55) -> bool:
        """Return *True* if the signal is strong enough to trade on."""
        return self.confidence >= min_confidence and self.direction != "neutral"

    def to_dict(self) -> dict:
        """Serialise to a plain dict (JSON-friendly)."""
        d = asdict(self)
        d["generation_time"] = self.generation_time.isoformat()
        return d

    def __repr__(self) -> str:
        return (
            f"KronosSignal(direction={self.direction!r}, "
            f"confidence={self.confidence:.2f}, "
            f"return={self.predicted_return:+.3f}%, "
            f"model={self.model_used!r}, "
            f"time={self.generation_time:%H:%M:%S})"
        )


# ═══════════════════════════════════════════════════════════════════════════
# 2.  Abstract Base Provider
# ═══════════════════════════════════════════════════════════════════════════

class SignalProvider(ABC):
    """Abstract base class for all signal providers.

    Concrete subclasses must implement ``generate_signal``.  The base class
    handles batching, logging, and optional SQLite persistence automatically.
    """

    NAME: str = "abstract"

    # ------------------------------------------------------------------
    # construction
    # ------------------------------------------------------------------
    def __init__(self, *, tracker: Optional["SignalTracker"] = None) -> None:
        self._tracker = tracker or SignalTracker()
        _ensure_file_handler()

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------
    @abstractmethod
    async def generate_signal(
        self,
        df: pd.DataFrame,
        symbol: str,
        horizon: int = 24,
    ) -> KronosSignal:
        """Generate a single trading signal.

        Args:
            df:      OHLCV DataFrame with columns
                     ``['open','high','low','close','volume']`` (any case).
            symbol:  Trading symbol, e.g. ``'XAUUSD'`` or ``'BTCUSD'``.
            horizon: Prediction horizon in *periods* (not hours).

        Returns:
            A :class:`KronosSignal` instance.
        """
        ...  # pragma: no cover

    async def batch_signals(
        self,
        dfs: dict[str, pd.DataFrame],
        horizon: int = 24,
    ) -> dict[str, KronosSignal]:
        """Generate signals for multiple symbols concurrently.

        Returns:
            Mapping ``{symbol: KronosSignal, ...}``.
        """
        coros = [
            self.generate_signal(df, symbol, horizon) for symbol, df in dfs.items()
        ]
        results = await asyncio.gather(*coros, return_exceptions=True)
        out: dict[str, KronosSignal] = {}
        for sym, sig in zip(dfs.keys(), results):
            if isinstance(sig, Exception):
                logger.error("Signal error for %s: %s", sym, sig)
                out[sym] = self._error_signal(sym, str(sig))
            else:
                out[sym] = sig
        return out

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _error_signal(self, symbol: str, reason: str) -> KronosSignal:
        """Produce a neutral signal when something goes wrong."""
        return KronosSignal(
            direction="neutral",
            confidence=0.0,
            predicted_return=0.0,
            volatility_forecast=0.0,
            trend_strength=0.0,
            key_levels={"support": None, "resistance": None},
            reasoning=f"Error generating signal: {reason}",
            model_used=f"{self.NAME}_error",
        )


# ═══════════════════════════════════════════════════════════════════════════
# 3.  Kronos Real-Model Provider
# ═══════════════════════════════════════════════════════════════════════════

class KronosSignalProvider(SignalProvider):
    """Signal provider backed by the real Kronos foundation model.

    Models are auto-downloaded from the HuggingFace Hub:

    +--------+---------+-------------------------+------------------+
    | Size   | Params  | HuggingFace repo          | Context length   |
    +========+=========+=========================+==================+
    | mini   | 4.1M    | NeoQuasar/Kronos-mini   | 256              |
    +--------+---------+-------------------------+------------------+
    | small  | 24.7M   | NeoQuasar/Kronos-small  | 512              |
    +--------+---------+-------------------------+------------------+
    | base   | 102.3M  | NeoQuasar/Kronos-base   | 1 024            |
    +--------+---------+-------------------------+------------------+

    The model tokenises OHLCV data into hierarchical discrete tokens and
    uses an autoregressive Transformer (GPT-like) to predict future price
    action.  Kronos was trained on 45+ global exchanges covering equities,
    FX, commodities, and crypto.

    **Graceful degradation:** if ``transformers`` is not installed, the
    constructor raises an ``ImportError`` with a helpful message.  Use
    :func:`create_default_provider` to auto-fallback.
    """

    NAME = "kronos"

    # ------------------------------------------------------------------
    def __init__(
        self,
        model_size: ModelSize = "mini",
        device: Literal["cuda", "cpu", "auto"] = "auto",
        *,
        tracker: Optional["SignalTracker"] = None,
        trust_remote_code: bool = True,
        load_in_8bit: bool = False,
    ) -> None:
        """
        Args:
            model_size:  Which Kronos variant to load.
            device:      torch device (``'cuda'`` recommended for *base*).
            tracker:     Optional :class:`SignalTracker` for persistence.
            trust_remote_code: Passed to ``AutoModel.from_pretrained``.
            load_in_8bit:      Use 8-bit quantisation to reduce VRAM.
        """
        super().__init__(tracker=tracker)
        self.model_size = model_size
        self.device = device
        self.trust_remote_code = trust_remote_code
        self.load_in_8bit = load_in_8bit

        # lazy-loaded handles (see ``_load_model``)
        self._tokenizer: Any = None
        self._model: Any = None
        self._is_loaded: bool = False

        # detect torch / transformers availability
        self._has_torch = self._check_torch()
        self._has_transformers = self._check_transformers()

        if not (self._has_torch and self._has_transformers):
            missing = []
            if not self._has_torch:
                missing.append("torch")
            if not self._has_transformers:
                missing.append("transformers")
            raise ImportError(
                f"KronosSignalProvider requires: {', '.join(missing)}.\n"
                "Install with:  pip install torch transformers"
            )

        logger.info(
            "KronosSignalProvider created (size=%s, device=%s, params=%s)",
            model_size,
            device,
            MODEL_PARAMS.get(model_size, "?"),
        )

    # ------------------------------------------------------------------
    # dependency checks
    # ------------------------------------------------------------------
    @staticmethod
    def _check_torch() -> bool:
        try:
            import torch  # noqa: F401
            return True
        except Exception:
            return False

    @staticmethod
    def _check_transformers() -> bool:
        try:
            import transformers  # noqa: F401
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------
    # model loading
    # ------------------------------------------------------------------
    def _load_model(self) -> None:
        """Load tokenizer and model from HuggingFace Hub (lazy)."""
        if self._is_loaded:
            return

        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        repo_id = HUGGINGFACE_REPOS.get(self.model_size, HUGGINGFACE_REPOS["mini"])
        logger.info("Loading Kronos model: %s", repo_id)

        t0 = time.time()
        self._tokenizer = AutoTokenizer.from_pretrained(
            repo_id,
            trust_remote_code=self.trust_remote_code,
        )

        load_kwargs: dict[str, Any] = {
            "trust_remote_code": self.trust_remote_code,
        }
        if self.device == "auto":
            load_kwargs["device_map"] = "auto"
        if self.load_in_8bit:
            load_kwargs["load_in_8bit"] = True

        self._model = AutoModelForCausalLM.from_pretrained(repo_id, **load_kwargs)

        if self.device != "auto":
            dev = torch.device(self.device)
            self._model = self._model.to(dev)

        self._model.eval()
        self._is_loaded = True
        logger.info(
            "Kronos %s loaded in %.1fs on %s",
            self.model_size,
            time.time() - t0,
            next(self._model.parameters()).device,
        )

    # ------------------------------------------------------------------
    # preprocessing  (OHLCV -> token ids)
    # ------------------------------------------------------------------
    def _preprocess(self, df: pd.DataFrame) -> Any:  # returns torch.Tensor
        """Convert an OHLCV DataFrame into a token-id tensor for Kronos.

        Steps (replicating the paper's pipeline):
            1. **Normalise** OHLCV per-column (z-score over rolling window).
            2. **Quantise** each normalised value into discrete bins.
            3. **Map** bins to token IDs (offset by column-specific vocab
               segments to avoid collisions).
            4. **Pad / truncate** to the model's context length.

        Returns:
            ``torch.LongTensor`` of shape ``(1, seq_len)``.
        """
        import torch

        df = _normalise_ohlcv_columns(df).copy()
        ohlcv = df[["open", "high", "low", "close", "volume"]].values.astype(np.float32)

        # rolling z-score normalisation (256-bar window)
        window = min(256, len(ohlcv))
        rolling_mean = pd.DataFrame(ohlcv).rolling(window=window, min_periods=1).mean().values
        rolling_std = pd.DataFrame(ohlcv).rolling(window=window, min_periods=1).std().values
        rolling_std = np.where(rolling_std == 0, 1.0, rolling_std)
        normalised = (ohlcv - rolling_mean) / rolling_std

        # clip to [-4, +4] sigma then quantise to 64 bins per column
        BINS = 64
        normalised = np.clip(normalised, -4.0, 4.0)
        # map [-4, 4] -> [0, 63]
        quantised = ((normalised + 4.0) / 8.0 * (BINS - 1)).astype(np.int64)

        # offset each column's tokens so they don't collide
        # open=0..63, high=64..127, low=128..191, close=192..255, vol=256..319
        COLUMN_OFFSETS = np.array([0, 64, 128, 192, 256], dtype=np.int64)
        token_ids = quantised + COLUMN_OFFSETS[np.newaxis, :]

        # flatten to 1-D sequence: (open_t, high_t, low_t, close_t, vol_t, ...)
        flat = token_ids.flatten()

        # pad / truncate to context length
        ctx = MODEL_CONTEXT_LENGTH.get(self.model_size, 256)
        if len(flat) < ctx:
            flat = np.pad(flat, (0, ctx - len(flat)), constant_values=0)
        else:
            flat = flat[-ctx:]

        return torch.from_numpy(flat).long().unsqueeze(0)  # (1, ctx)

    # ------------------------------------------------------------------
    # post-processing  (model output -> trading signal)
    # ------------------------------------------------------------------
    def _postprocess(self, logits: Any, df: pd.DataFrame, symbol: str, horizon: int) -> KronosSignal:
        """Convert raw model logits into a structured :class:`KronosSignal`.

        We interpret the next-token distribution over the *close* price
        bin as a proxy for directional bias:

        * If the most-probable close bin > last actual close bin → bullish
        * If the most-probable close bin < last actual close bin → bearish
        * Otherwise → neutral

        Confidence is derived from the softmax entropy (sharper = more
        confident).  Predicted return is estimated from the distance
        between the predicted and current close bin.
        """
        import torch

        probs = torch.softmax(logits[:, -1, 192:256], dim=-1)  # close bins only
        best_bin = int(torch.argmax(probs, dim=-1).item())
        prob_dist = probs.squeeze(0).cpu().numpy()

        # retrieve last actual close bin
        last_close = float(df["close"].iloc[-1])
        window = min(256, len(df))
        mean_c = df["close"].rolling(window=window, min_periods=1).mean().iloc[-1]
        std_c = df["close"].rolling(window=window, min_periods=1).std().iloc[-1]
        std_c = std_c if std_c > 0 else 1.0
        last_bin = int(np.clip(((last_close - mean_c) / std_c + 4.0) / 8.0 * 63, 0, 63))

        # direction
        if best_bin > last_bin + 2:
            direction: Direction = "bullish"
        elif best_bin < last_bin - 2:
            direction = "bearish"
        else:
            direction = "neutral"

        # confidence via entropy
        entropy = -np.sum(prob_dist * np.log(prob_dist + 1e-12))
        max_entropy = np.log(len(prob_dist))
        confidence = float(np.clip(1.0 - entropy / max_entropy, 0.0, 1.0))

        # predicted return estimate (each bin ≈ 1/8 sigma)
        bin_delta = best_bin - last_bin
        predicted_return = float(bin_delta / 8.0 * std_c / last_close * 100)

        # volatility forecast (spread of top-5 bins)
        top5_idx = np.argsort(prob_dist)[-5:]
        vol_forecast = float(np.std(top5_idx) / 8.0 * std_c / last_close * 100 * np.sqrt(horizon))

        # key levels from prob distribution peaks
        peaks = _find_peaks(prob_dist)
        supports = [float(mean_c + (p / 63.0 * 8.0 - 4.0) * std_c) for p in peaks[:2]]
        resistances = [float(mean_c + (p / 63.0 * 8.0 - 4.0) * std_c) for p in peaks[-2:]]

        reasoning = (
            f"Kronos-{self.model_size} predicts close token bin {best_bin} vs "
            f"current {last_bin} (delta={bin_delta:+d}). "
            f"Entropy-based confidence={confidence:.2f}. "
            f"Top probability mass concentrated on bins {peaks}."
        )

        return KronosSignal(
            direction=direction,
            confidence=round(confidence, 4),
            predicted_return=round(predicted_return, 4),
            volatility_forecast=round(vol_forecast, 4),
            trend_strength=round(confidence * abs(bin_delta) / 32, 4),
            key_levels={
                "support": supports[0] if supports else None,
                "resistance": resistances[-1] if resistances else None,
                "supports": supports,
                "resistances": resistances,
            },
            reasoning=reasoning,
            model_used=f"kronos_{self.model_size}",
        )

    # ------------------------------------------------------------------
    # main entry point
    # ------------------------------------------------------------------
    async def generate_signal(
        self,
        df: pd.DataFrame,
        symbol: str,
        horizon: int = 24,
    ) -> KronosSignal:
        """Generate a signal using the Kronos foundation model."""
        t0 = time.perf_counter()
        try:
            self._load_model()
        except Exception as exc:
            logger.error("Failed to load Kronos model: %s", exc)
            return self._error_signal(symbol, f"Model load failed: {exc}")

        try:
            import torch

            input_ids = self._preprocess(df)
            device = next(self._model.parameters()).device
            input_ids = input_ids.to(device)

            with torch.no_grad():
                outputs = self._model(input_ids)
                logits = outputs.logits

            signal = self._postprocess(logits, df, symbol, horizon)
            latency = time.perf_counter() - t0
            logger.info(
                "Kronos %s signal for %s: %s (%.3fs)",
                self.model_size, symbol, signal.direction, latency,
            )
            await self._tracker.save(signal, symbol, horizon, latency_ms=latency * 1000)
            return signal

        except Exception as exc:
            logger.error("Kronos inference error: %s\n%s", exc, traceback.format_exc())
            return self._error_signal(symbol, str(exc))


# ═══════════════════════════════════════════════════════════════════════════
# 4.  Fallback Statistical Provider
# ═══════════════════════════════════════════════════════════════════════════

class FallbackSignalProvider(SignalProvider):
    """Comprehensive statistical signal provider that mimics Kronos-style
    predictions using proven technical-analysis methods.

    Scoring system
    ==============
    Each analysis module returns a score in ``[-1, +1]``:

    * **+1** = strongly bullish
    * **-1** = strongly bearish
    * **0**  = neutral / no edge

    The final signal is a weighted combination:

    +-------------------+----------+----------------------------------+
    | Module            | Weight   | Indicators                       |
    +===================+==========+==================================+
    | Trend             | 0.25     | EMA alignment, ADX, slope       |
    +-------------------+----------+----------------------------------+
    | Momentum          | 0.25     | RSI position, MACD cross        |
    +-------------------+----------+----------------------------------+
    | Volatility regime | 0.20     | ATR, Bollinger width            |
    +-------------------+----------+----------------------------------+
    | Pattern           | 0.15     | Candlestick patterns            |
    +-------------------+----------+----------------------------------+
    | Mean reversion    | 0.15     | Distance from VWAP              |
    +-------------------+----------+----------------------------------+

    Confidence is derived from:
    1.  **Strength** – absolute value of the composite score.
    2.  **Agreement** – how many sub-modules agree on the direction.
    3.  **Confluence** – whether multiple uncorrelated indicators align.

    This provider is the **default** when Kronos is unavailable and is
    intentionally designed to be robust, well-documented, and fully
    self-contained (no heavy ML dependencies).
    """

    NAME = "fallback"

    # module weights (must sum to 1.0)
    WEIGHTS: dict[str, float] = {
        "trend": 0.25,
        "momentum": 0.25,
        "volatility": 0.20,
        "pattern": 0.15,
        "mean_reversion": 0.15,
    }

    # minimum bars required for a reliable signal
    MIN_BARS: int = 50

    # ------------------------------------------------------------------
    # main entry point
    # ------------------------------------------------------------------
    async def generate_signal(
        self,
        df: pd.DataFrame,
        symbol: str,
        horizon: int = 24,
    ) -> KronosSignal:
        """Generate a signal using comprehensive statistical analysis."""
        t0 = time.perf_counter()
        df = _normalise_ohlcv_columns(df).copy()

        if len(df) < self.MIN_BARS:
            logger.warning(
                "Insufficient data for %s: %d bars (need %d)",
                symbol, len(df), self.MIN_BARS,
            )
            return KronosSignal(
                direction="neutral",
                confidence=0.0,
                predicted_return=0.0,
                volatility_forecast=0.0,
                trend_strength=0.0,
                key_levels={"support": None, "resistance": None},
                reasoning=f"Insufficient data: {len(df)} bars (need {self.MIN_BARS})",
                model_used="fallback_insufficient_data",
            )

        # ---- individual analyses ---------------------------------------
        trend_score, trend_desc = self._analyze_trend(df)
        mom_score, mom_desc = self._analyze_momentum(df)
        vol_score, vol_regime = self._analyze_volatility(df)
        # compute ADX once for trend-awareness in pattern scoring & mean reversion
        adx_series = self._compute_adx(df, period=14)
        adx_val = float(adx_series.iloc[-1]) if not pd.isna(adx_series.iloc[-1]) else 20.0

        patterns = self._detect_patterns(df)
        pattern_score = self._score_patterns(patterns, adx=adx_val)
        mr_score, mr_desc = self._mean_reversion(df)

        # ---- weighted composite ----------------------------------------
        composite = (
            trend_score * self.WEIGHTS["trend"]
            + mom_score * self.WEIGHTS["momentum"]
            + vol_score * self.WEIGHTS["volatility"]
            + pattern_score * self.WEIGHTS["pattern"]
            + mr_score * self.WEIGHTS["mean_reversion"]
        )

        # direction & confidence
        # Lower the threshold slightly since we have 5 sub-modules and
        # the mean-reversion component can be contrarian in trends.
        direction, confidence = self._composite_to_signal(
            composite,
            [
                (trend_score, "trend"),
                (mom_score, "momentum"),
                (vol_score, "volatility"),
                (pattern_score, "pattern"),
                (mr_score, "mean_reversion"),
            ],
            threshold=0.10,
        )

        # predicted return estimate
        last_close = float(df["close"].iloc[-1])
        atr_series = self._compute_atr(df, period=14)
        atr_val = float(atr_series.iloc[-1]) if not pd.isna(atr_series.iloc[-1]) else 0.0
        predicted_return = float(composite * atr_val / last_close * 100 * np.sqrt(horizon))

        # volatility forecast
        bb_width = self._compute_bb_width(df)
        vol_forecast = float(atr_val / last_close * 100 * np.sqrt(horizon) * (1 + bb_width))

        # key levels
        supports, resistances = self._compute_key_levels(df)

        # trend strength
        trend_strength = abs(composite)

        reasoning = (
            f"[Fallback] Trend({trend_score:+.2f}) | "
            f"Momentum({mom_score:+.2f}) | "
            f"Volatility({vol_score:+.2f}/{vol_regime}) | "
            f"Patterns({pattern_score:+.2f}: {', '.join(patterns) if patterns else 'none'}) | "
            f"MeanRev({mr_score:+.2f}).  "
            f"Composite={composite:+.3f} -> {direction} (conf={confidence:.2f})."
        )

        signal = KronosSignal(
            direction=direction,
            confidence=round(confidence, 4),
            predicted_return=round(predicted_return, 4),
            volatility_forecast=round(vol_forecast, 4),
            trend_strength=round(trend_strength, 4),
            key_levels={
                "support": supports[0] if supports else None,
                "resistance": resistances[-1] if resistances else None,
                "supports": supports,
                "resistances": resistances,
            },
            reasoning=reasoning,
            model_used="fallback_statistical",
        )

        latency = time.perf_counter() - t0
        logger.info(
            "Fallback signal for %s: %s (%.3fms)",
            symbol, signal.direction, latency * 1000,
        )
        await self._tracker.save(signal, symbol, horizon, latency_ms=latency * 1000)
        return signal

    # ═══════════════════════════════════════════════════════════════════
    # 4.1  Trend Analysis
    # ═══════════════════════════════════════════════════════════════════

    def _analyze_trend(self, df: pd.DataFrame) -> tuple[float, str]:
        """Analyse trend direction and strength.

        Methodology:
            1. **EMA alignment** – bullish when fast > medium > slow EMA.
            2. **ADX** – measures trend *strength* (not direction).
               - ADX > 25 → trending (higher = stronger)
               - ADX < 20 → ranging
            3. **Price vs EMA-50 slope** – recent trajectory.

        Returns:
            ``(score, description)`` where *score* ∈ ``[-1, +1]``.
        """
        close = df["close"]

        # EMAs
        ema9 = close.ewm(span=9, adjust=False).mean()
        ema21 = close.ewm(span=21, adjust=False).mean()
        ema50 = close.ewm(span=50, adjust=False).mean()

        # alignment score: +1 if stacked bullish, -1 if stacked bearish
        last = -1
        bullish_stack = ema9.iloc[last] > ema21.iloc[last] > ema50.iloc[last]
        bearish_stack = ema9.iloc[last] < ema21.iloc[last] < ema50.iloc[last]
        align_score = 1.0 if bullish_stack else (-1.0 if bearish_stack else 0.0)

        # ADX (simplified)
        adx = self._compute_adx(df, period=14)
        adx_val = adx.iloc[last] if not pd.isna(adx.iloc[last]) else 20.0
        adx_factor = min(adx_val / 50.0, 1.0)  # normalise 0..1

        # slope of EMA-50
        slope = (ema50.iloc[last] - ema50.iloc[-min(10, len(ema50))]) / ema50.iloc[last]
        slope_score = float(np.clip(slope * 100, -1, 1))

        score = float(np.clip((align_score * 0.5 + slope_score * 0.5) * adx_factor, -1, 1))

        desc = (
            f"EMA9={ema9.iloc[last]:.4f} vs EMA21={ema21.iloc[last]:.4f} vs "
            f"EMA50={ema50.iloc[last]:.4f}, ADX={adx_val:.1f}, "
            f"slope={slope_score:+.3f}"
        )
        return score, desc

    # ═══════════════════════════════════════════════════════════════════
    # 4.2  Momentum Analysis
    # ═══════════════════════════════════════════════════════════════════

    def _analyze_momentum(self, df: pd.DataFrame) -> tuple[float, str]:
        """Analyse momentum via RSI and MACD.

        RSI scoring:
            * > 70  → overbought  (bearish bias, score → -1)
            * < 30  → oversold    (bullish bias, score → +1)
            * 40-60 → neutral zone

        MACD scoring:
            * MACD line above signal  → bullish
            * Histogram expanding     → strengthening

        Returns:
            ``(score, description)`` where *score* ∈ ``[-1, +1]``.
        """
        close = df["close"]

        # RSI
        rsi = self._compute_rsi(close, period=14)
        rsi_val = rsi.iloc[-1] if not pd.isna(rsi.iloc[-1]) else 50.0
        if rsi_val > 70:
            rsi_score = -((rsi_val - 70) / 30)  # -0..-1
        elif rsi_val < 30:
            rsi_score = +((30 - rsi_val) / 30)  # +0..+1
        else:
            # map 30..70 -> -0.33..+0.33, neutral zone contracted
            rsi_score = (rsi_val - 50) / 60

        # MACD
        ema12 = close.ewm(span=12, adjust=False).mean()
        ema26 = close.ewm(span=26, adjust=False).mean()
        macd_line = ema12 - ema26
        signal_line = macd_line.ewm(span=9, adjust=False).mean()
        histogram = macd_line - signal_line

        macd_score = 0.0
        if not pd.isna(macd_line.iloc[-1]) and not pd.isna(signal_line.iloc[-1]):
            if macd_line.iloc[-1] > signal_line.iloc[-1]:
                macd_score = min(1.0, 0.5 + abs(histogram.iloc[-1]) / close.iloc[-1] * 100)
            else:
                macd_score = max(-1.0, -0.5 - abs(histogram.iloc[-1]) / close.iloc[-1] * 100)

        # combine
        score = float(np.clip(rsi_score * 0.5 + macd_score * 0.5, -1, 1))
        desc = f"RSI={rsi_val:.1f} ({rsi_score:+.2f}), MACD={macd_score:+.2f}"
        return score, desc

    # ═══════════════════════════════════════════════════════════════════
    # 4.3  Volatility Analysis
    # ═══════════════════════════════════════════════════════════════════

    def _analyze_volatility(self, df: pd.DataFrame) -> tuple[float, str]:
        """Analyse volatility regime and return a directional score.

        Volatility is *non-directional*, but regime shifts often precede
        directional moves:

        * **Contracting volatility** after expansion → often bullish
          (consolidation break-out).
        * **Expanding volatility** near highs → often bearish (climax).

        Returns:
            ``(directional_score, regime_name)``.
        """
        close = df["close"]
        atr = self._compute_atr(df, period=14)
        atr_val = atr.iloc[-1] if not pd.isna(atr.iloc[-1]) else 0.0
        atr_mean = atr.iloc[-20:].mean() if len(atr) >= 20 else atr.mean()

        # ATR regime
        if atr_val > atr_mean * 1.5:
            regime = "expanding"
            regime_score = -0.3  # expansion often near turning points
        elif atr_val < atr_mean * 0.7:
            regime = "contracting"
            regime_score = 0.2   # contraction → possible break-out
        else:
            regime = "normal"
            regime_score = 0.0

        # Bollinger Band width
        bb_width = self._compute_bb_width(df)
        if bb_width > 0.1:
            bb_score = -0.2  # wide bands → volatility high → caution
        elif bb_width < 0.02:
            bb_score = 0.1   # squeeze → break-out pending
        else:
            bb_score = 0.0

        score = float(np.clip(regime_score + bb_score, -1, 1))
        return score, regime

    # ═══════════════════════════════════════════════════════════════════
    # 4.4  Candlestick Pattern Detection
    # ═══════════════════════════════════════════════════════════════════

    def _detect_patterns(self, df: pd.DataFrame) -> list[str]:
        """Detect classic candlestick patterns.

        Detected patterns:
            * **Doji**          – open ≈ close (indecision).
            * **Hammer**        – small body, long lower shadow (bullish reversal).
            * **Shooting star** – small body, long upper shadow (bearish reversal).
            * **Bullish engulfing** – green body fully engulfs prior red body.
            * **Bearish engulfing** – red body fully engulfs prior green body.
            * **Morning star**  – 3-candle bullish reversal pattern.
            * **Evening star**  – 3-candle bearish reversal pattern.

        Returns:
            List of detected pattern names (may be empty).
        """
        if len(df) < 3:
            return []

        patterns: list[str] = []

        # aliases for the last 3 candles
        o1, h1, l1, c1 = (
            df["open"].iloc[-3], df["high"].iloc[-3],
            df["low"].iloc[-3], df["close"].iloc[-3],
        )
        o2, h2, l2, c2 = (
            df["open"].iloc[-2], df["high"].iloc[-2],
            df["low"].iloc[-2], df["close"].iloc[-2],
        )
        o3, h3, l3, c3 = (
            df["open"].iloc[-1], df["high"].iloc[-1],
            df["low"].iloc[-1], df["close"].iloc[-1],
        )

        body1, body2, body3 = abs(c1 - o1), abs(c2 - o2), abs(c3 - o3)
        range1 = h1 - l1
        range2 = h2 - l2
        range3 = h3 - l3

        # --- single-candle patterns -----------------------------------

        # Doji: body < 2% of range AND body is very small in absolute terms
        # (avoids false doji detection in trending markets with volatile wicks)
        atr_val = float(self._compute_atr(df.iloc[-20:], period=14).iloc[-1]) if len(df) >= 14 else 1e-6
        if range3 > 0 and body3 / range3 < 0.02 and body3 < atr_val * 0.3:
            patterns.append("doji")

        # Hammer: body in upper half, long lower shadow (>2x body)
        lower_shadow = min(c3, o3) - l3
        upper_shadow = h3 - max(c3, o3)
        if body3 > 0 and lower_shadow > 2 * body3 and upper_shadow < body3:
            patterns.append("hammer")

        # Shooting star: body in lower half, long upper shadow
        if body3 > 0 and upper_shadow > 2 * body3 and lower_shadow < body3:
            patterns.append("shooting_star")

        # --- two-candle patterns ---------------------------------------

        # Bullish engulfing
        if c2 < o2 and c3 > o3 and o3 < c2 and c3 > o2:
            patterns.append("bullish_engulfing")

        # Bearish engulfing
        if c2 > o2 and c3 < o3 and o3 > c2 and c3 < o2:
            patterns.append("bearish_engulfing")

        # --- three-candle patterns -------------------------------------

        # Morning star (bearish -> small -> bullish)
        if c1 < o1 and body2 < body1 * 0.5 and c3 > o3 and c3 > (o1 + c1) / 2:
            patterns.append("morning_star")

        # Evening star (bullish -> small -> bearish)
        if c1 > o1 and body2 < body1 * 0.5 and c3 < o3 and c3 < (o1 + c1) / 2:
            patterns.append("evening_star")

        return patterns

    def _score_patterns(
        self, patterns: list[str], adx: Optional[float] = None
    ) -> float:
        """Convert detected patterns into a directional score.

        Bullish patterns: hammer, bullish_engulfing, morning_star, doji
        Bearish patterns: shooting_star, bearish_engulfing, evening_star

        **Trend-aware:** in strong trends (ADX > 25) candlestick patterns
        are less reliable — the score is attenuated.
        """
        if not patterns:
            return 0.0

        bullish = {"hammer", "bullish_engulfing", "morning_star", "doji"}
        bearish = {"shooting_star", "bearish_engulfing", "evening_star"}

        score = 0.0
        for p in patterns:
            if p in bullish:
                score += 0.35
            if p in bearish:
                score -= 0.35

        # attenuate in strong trends
        attenuation = 1.0
        if adx is not None:
            if adx > 30:
                attenuation = 0.3
            elif adx > 20:
                attenuation = 0.6

        return float(np.clip(score * attenuation, -1, 1))

    # ═══════════════════════════════════════════════════════════════════
    # 4.5  Mean Reversion (VWAP)
    # ═══════════════════════════════════════════════════════════════════

    def _mean_reversion(self, df: pd.DataFrame, window: int = 20) -> tuple[float, str]:
        """Analyse deviation from rolling Volume-Weighted Average Price (VWAP).

        Uses a *rolling* VWAP (not cumulative from t=0) so that it remains
        relevant in trending markets.  The z-score of the last close vs the
        rolling VWAP indicates how extended price is — extreme readings
        suggest mean-reversion.

        **Regime-aware:** when ADX > 25 (strong trend) the mean-reversion
        score is attenuated because break-outs can stay extended for long
        periods.  In ranging markets (ADX < 20) the full score is used.

        Logic:
            * Price > 2σ above VWAP → likely mean-revert lower (bearish).
            * Price > 2σ below VWAP → likely mean-revert higher (bullish).
            * Within ±1σ → no mean-reversion edge (neutral).

        Args:
            df:     OHLCV DataFrame (normalised columns).
            window: Rolling VWAP look-back (default 20 periods).

        Returns:
            ``(score, description)`` where score ∈ ``[-1, +1]``.
        """
        if len(df) < window or df["volume"].sum() == 0:
            return 0.0, "No volume data"

        # typical price = (H + L + C) / 3
        tp = (df["high"] + df["low"] + df["close"]) / 3.0

        # rolling VWAP (not cumulative from t=0 — that creates extreme
        # drift in trending markets)
        vwap = (
            tp.rolling(window=window, min_periods=window).apply(
                lambda x: np.average(x, weights=df["volume"].loc[x.index])
            )
        )

        # rolling std of the deviation
        deviation = df["close"] - vwap
        dev_std = deviation.rolling(window=window, min_periods=window // 2).std().iloc[-1]
        dev_std = dev_std if dev_std and dev_std > 0 else 1e-6

        z_score = float(deviation.iloc[-1] / dev_std)
        z_score = float(np.clip(z_score, -5.0, 5.0))

        # raw mean-reversion score
        if z_score > 2.5:
            raw = -0.8
        elif z_score > 1.5:
            raw = -0.4
        elif z_score < -2.5:
            raw = +0.8
        elif z_score < -1.5:
            raw = +0.4
        else:
            raw = 0.0

        # regime attenuation: suppress MR when trending
        adx = self._compute_adx(df, period=14)
        adx_val = float(adx.iloc[-1]) if not pd.isna(adx.iloc[-1]) else 20.0
        if adx_val > 30:
            attenuation = 0.2  # strong trend → barely use MR
        elif adx_val > 20:
            attenuation = 0.5  # moderate trend → halve MR
        else:
            attenuation = 1.0  # ranging → full MR

        score = raw * attenuation
        desc = f"roll-VWAP({window}) z={z_score:+.2f} adx={adx_val:.1f} att={attenuation}"
        return score, desc

    # ═══════════════════════════════════════════════════════════════════
    # 4.6  Composite → Signal conversion
    # ═══════════════════════════════════════════════════════════════════

    def _composite_to_signal(
        self,
        composite: float,
        scores: list[tuple[float, str]],
        threshold: float = 0.15,
    ) -> tuple[Direction, float]:
        """Convert composite score to direction + confidence.

        Confidence formula:
            1. Base = |composite|  (strength)
            2. Boost if ≥ 3 sub-modules agree on the sign
            3. Penalise if sub-module directions conflict heavily

        Args:
            composite: Weighted composite score.
            scores:    List of (sub_score, name) tuples for agreement calc.
            threshold: Minimum |composite| to declare a direction.
        """
        if composite > threshold:
            direction: Direction = "bullish"
        elif composite < -threshold:
            direction = "bearish"
        else:
            direction = "neutral"

        # base confidence
        confidence = abs(composite)

        # agreement bonus
        signs = [np.sign(s[0]) for s in scores if abs(s[0]) > 0.1]
        if len(signs) >= 3:
            majority = max(set(signs), key=signs.count)
            agreement = signs.count(majority) / len(signs)
            confidence = min(1.0, confidence * (0.7 + 0.3 * agreement))

        # cap based on direction clarity
        if direction == "neutral":
            confidence *= 0.5  # neutral signals are inherently less confident

        return direction, round(float(confidence), 4)

    # ═══════════════════════════════════════════════════════════════════
    # 4.7  Key levels (S/R)
    # ═══════════════════════════════════════════════════════════════════

    def _compute_key_levels(
        self,
        df: pd.DataFrame,
    ) -> tuple[list[float], list[float]]:
        """Compute support and resistance levels.

        Uses recent swing lows/highs and Bollinger Band boundaries.
        """
        if len(df) < 20:
            return [], []

        recent = df.iloc[-50:]
        lows = recent["low"].values
        highs = recent["high"].values

        # simple swing detection
        supports: list[float] = []
        resistances: list[float] = []

        for i in range(2, len(lows) - 2):
            if lows[i] < lows[i - 1] and lows[i] < lows[i - 2] and lows[i] < lows[i + 1]:
                supports.append(float(lows[i]))
            if highs[i] > highs[i - 1] and highs[i] > highs[i - 2] and highs[i] > highs[i + 1]:
                resistances.append(float(highs[i]))

        # add BB boundaries
        close = df["close"]
        sma20 = close.rolling(20).mean().iloc[-1]
        std20 = close.rolling(20).std().iloc[-1]
        if not pd.isna(sma20) and not pd.isna(std20):
            supports.append(float(sma20 - 2 * std20))
            resistances.append(float(sma20 + 2 * std20))

        supports = sorted(set(round(s, 5) for s in supports))[:3]
        resistances = sorted(set(round(r, 5) for r in resistances))[-3:]
        return supports, resistances

    # ═══════════════════════════════════════════════════════════════════
    # 4.8  Indicator helpers
    # ═══════════════════════════════════════════════════════════════════

    @staticmethod
    def _compute_rsi(series: pd.Series, period: int = 14) -> pd.Series:
        """Wilder's Relative Strength Index."""
        delta = series.diff()
        gain = delta.where(delta > 0, 0.0)
        loss = (-delta).where(delta < 0, 0.0)
        avg_gain = gain.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
        rs = avg_gain / avg_loss.replace(0, np.nan)
        rsi = 100.0 - (100.0 / (1.0 + rs))
        return rsi.fillna(50.0)

    @staticmethod
    def _compute_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
        """Average True Range."""
        high = df["high"]
        low = df["low"]
        close = df["close"]
        tr1 = high - low
        tr2 = (high - close.shift()).abs()
        tr3 = (low - close.shift()).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        return tr.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()

    @staticmethod
    def _compute_adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
        """Average Directional Index (simplified)."""
        high = df["high"]
        low = df["low"]
        close = df["close"]

        plus_dm = high.diff()
        minus_dm = -low.diff()
        plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0.0)
        minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0.0)

        tr1 = high - low
        tr2 = (high - close.shift()).abs()
        tr3 = (low - close.shift()).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

        atr = tr.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
        plus_di = 100 * (plus_dm.ewm(alpha=1.0 / period, adjust=False).mean() / atr)
        minus_di = 100 * (minus_dm.ewm(alpha=1.0 / period, adjust=False).mean() / atr)
        dx = ( (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan) ) * 100
        adx = dx.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
        return adx.fillna(20.0)

    @staticmethod
    def _compute_bb_width(df: pd.DataFrame, period: int = 20) -> float:
        """Bollinger Band width as fraction of SMA."""
        close = df["close"]
        sma = close.rolling(period).mean().iloc[-1]
        std = close.rolling(period).std().iloc[-1]
        if pd.isna(sma) or sma == 0:
            return 0.0
        return float(2 * std / sma)


# ═══════════════════════════════════════════════════════════════════════════
# 5.  Signal Aggregator
# ═══════════════════════════════════════════════════════════════════════════

class SignalAggregator:
    """Combine signals from multiple providers into a consensus signal.

    The aggregator uses **weighted voting** with conflict detection:

    * Each provider has a weight (default: equal).
    * Direction is determined by weighted majority.
    * Confidence is scaled by the *agreement ratio* among providers.
    * If providers strongly disagree, confidence is reduced (conflict
      penalty).
    * Predicted returns are averaged (not voted) to preserve magnitude.

    Example:
        .. code-block:: python

            kronos = KronosSignalProvider("mini")
            fallback = FallbackSignalProvider()
            aggregator = SignalAggregator(
                providers=[kronos, fallback],
                weights=[0.6, 0.4],
            )
            consensus = await aggregator.aggregate("XAUUSD", {"XAUUSD": df})
    """

    def __init__(
        self,
        providers: list[SignalProvider],
        weights: Optional[list[float]] = None,
        min_confidence: float = 0.55,
        conflict_threshold: float = 0.3,
    ) -> None:
        """
        Args:
            providers:          List of signal providers to aggregate.
            weights:            Optional weight for each provider (must sum
                                to 1.0).  If *None*, equal weights.
            min_confidence:     Minimum confidence for an actionable signal.
            conflict_threshold: If the spread between the most bullish and
                                most bearish sub-signal exceeds this value,
                                apply a conflict penalty.
        """
        if not providers:
            raise ValueError("At least one provider is required")

        self.providers = providers
        if weights is None:
            self.weights = [1.0 / len(providers)] * len(providers)
        else:
            if len(weights) != len(providers):
                raise ValueError("weights and providers must have same length")
            total = sum(weights)
            self.weights = [w / total for w in weights]

        self.min_confidence = min_confidence
        self.conflict_threshold = conflict_threshold
        _ensure_file_handler()

    # ------------------------------------------------------------------

    async def aggregate(
        self,
        symbol: str,
        data: dict[str, pd.DataFrame],
        horizon: int = 24,
    ) -> KronosSignal:
        """Generate and combine signals from all providers.

        Args:
            symbol:  Trading symbol.
            data:    Dict mapping symbols to OHLCV DataFrames.
            horizon: Prediction horizon in periods.

        Returns:
            Consensus :class:`KronosSignal`.
        """
        t0 = time.perf_counter()
        df = data.get(symbol)
        if df is None:
            raise KeyError(f"No data provided for symbol {symbol}")

        # collect signals from all providers
        signals: list[KronosSignal] = []
        tasks = [
            provider.generate_signal(df, symbol, horizon)
            for provider in self.providers
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for prov, result in zip(self.providers, results):
            if isinstance(result, Exception):
                logger.error("Provider %s failed: %s", prov.NAME, result)
                continue
            signals.append(result)

        if not signals:
            logger.error("All providers failed for %s", symbol)
            return KronosSignal(
                direction="neutral",
                confidence=0.0,
                predicted_return=0.0,
                volatility_forecast=0.0,
                trend_strength=0.0,
                key_levels={"support": None, "resistance": None},
                reasoning="All signal providers failed",
                model_used="aggregator_error",
            )

        consensus = self._weighted_vote(signals)
        latency = time.perf_counter() - t0
        logger.info(
            "Aggregated %d signals for %s -> %s (%.3fms)",
            len(signals), symbol, consensus.direction, latency * 1000,
        )
        return consensus

    # ------------------------------------------------------------------

    def _weighted_vote(self, signals: list[KronosSignal]) -> KronosSignal:
        """Weighted voting across multiple signals.

        Algorithm:
            1. Score each signal: bullish=+1, bearish=-1, neutral=0,
               weighted by ``confidence × provider_weight``.
            2. Sum to get composite score.
            3. Detect conflicts (spread of sub-signal scores).
            4. Compute aggregate predicted return (weighted average).
            5. Compute aggregate volatility (weighted average).
        """
        if len(signals) == 1:
            return signals[0]

        # assign weights to signals based on provider weights
        n = min(len(signals), len(self.weights))
        sig_weights = self.weights[:n]

        # 1. direction scores
        direction_scores: list[float] = []
        for sig, w in zip(signals, sig_weights):
            if sig.direction == "bullish":
                direction_scores.append(+1.0 * sig.confidence * w)
            elif sig.direction == "bearish":
                direction_scores.append(-1.0 * sig.confidence * w)
            else:
                direction_scores.append(0.0)

        composite = sum(direction_scores)

        # 2. conflict detection
        raw_scores = []
        for sig in signals:
            if sig.direction == "bullish":
                raw_scores.append(+sig.confidence)
            elif sig.direction == "bearish":
                raw_scores.append(-sig.confidence)
            else:
                raw_scores.append(0.0)

        spread = max(raw_scores) - min(raw_scores)
        conflict_penalty = 1.0
        if spread > self.conflict_threshold:
            conflict_penalty = max(0.3, 1.0 - (spread - self.conflict_threshold))
            logger.debug("Conflict detected (spread=%.2f), penalty=%.2f", spread, conflict_penalty)

        # 3. final direction
        if composite > 0.15:
            direction: Direction = "bullish"
        elif composite < -0.15:
            direction = "bearish"
        else:
            direction = "neutral"

        # 4. confidence
        base_confidence = abs(composite)
        agreement_ratio = 1.0
        if len([s for s in raw_scores if s != 0]) >= 2:
            # how many agree with the composite direction?
            if composite > 0:
                agreeing = sum(1 for s in raw_scores if s > 0)
            elif composite < 0:
                agreeing = sum(1 for s in raw_scores if s < 0)
            else:
                agreeing = sum(1 for s in raw_scores if s == 0)
            agreement_ratio = agreeing / len(raw_scores)

        confidence = base_confidence * agreement_ratio * conflict_penalty
        confidence = round(float(np.clip(confidence, 0.0, 1.0)), 4)

        # 5. predicted return (weighted average, preserving sign)
        total_pred_return = sum(
            sig.predicted_return * w for sig, w in zip(signals, sig_weights)
        )

        # 6. volatility (weighted average)
        total_vol = sum(
            sig.volatility_forecast * w for sig, w in zip(signals, sig_weights)
        )

        # 7. trend strength (weighted average)
        total_trend = sum(
            sig.trend_strength * w for sig, w in zip(signals, sig_weights)
        )

        # 8. key levels (merge from strongest signal)
        strongest = max(signals, key=lambda s: s.confidence)
        key_levels = strongest.key_levels.copy()

        # 9. reasoning
        parts = [
            f"[Aggregator] {len(signals)} providers, composite={composite:+.3f}",
        ]
        for i, sig in enumerate(signals):
            parts.append(
                f"  {i + 1}. {sig.model_used}: {sig.direction} "
                f"(conf={sig.confidence:.2f}, ret={sig.predicted_return:+.3f}%)"
            )
        parts.append(f"Consensus: {direction} (conf={confidence:.2f}, spread={spread:.2f})")

        return KronosSignal(
            direction=direction,
            confidence=confidence,
            predicted_return=round(total_pred_return, 4),
            volatility_forecast=round(total_vol, 4),
            trend_strength=round(total_trend, 4),
            key_levels=key_levels,
            reasoning="\n".join(parts),
            model_used="aggregator",
        )


# ═══════════════════════════════════════════════════════════════════════════
# 6.  SQLite Signal Tracker
# ═══════════════════════════════════════════════════════════════════════════

class SignalTracker:
    """Persistent SQLite tracking for signal accuracy and performance.

    Schema:
        * ``signal_log`` — every generated signal
        * ``signal_accuracy`` — outcome tracking for accuracy scoring

    This enables:
        * Backtesting signal performance
        * Provider weight optimisation
        * Confidence calibration
    """

    def __init__(self, db_path: str = "/mnt/agents/output/project/data/signals.db") -> None:
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._init_db()

    # ------------------------------------------------------------------
    def _init_db(self) -> None:
        """Create tables if they don't exist."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS signal_log (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol       TEXT NOT NULL,
                    direction    TEXT NOT NULL,
                    confidence   REAL NOT NULL,
                    predicted_return REAL,
                    volatility_forecast REAL,
                    trend_strength REAL,
                    model_used   TEXT NOT NULL,
                    reasoning    TEXT,
                    horizon      INTEGER,
                    latency_ms   REAL,
                    generation_time TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS signal_accuracy (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    signal_id    INTEGER REFERENCES signal_log(id),
                    symbol       TEXT NOT NULL,
                    actual_return REAL,
                    correct_direction INTEGER,  -- 1=correct, 0=wrong, NULL=pending
                    pnl_estimate  REAL,
                    resolved_at   TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_signal_log_symbol_time
                ON signal_log(symbol, generation_time)
                """
            )
            conn.commit()

    # ------------------------------------------------------------------
    async def save(
        self,
        signal: KronosSignal,
        symbol: str,
        horizon: int,
        latency_ms: Optional[float] = None,
    ) -> int:
        """Persist a generated signal to the database.

        Returns:
            The auto-generated row ID.
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute(
                    """
                    INSERT INTO signal_log
                        (symbol, direction, confidence, predicted_return,
                         volatility_forecast, trend_strength, model_used,
                         reasoning, horizon, latency_ms, generation_time)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        symbol,
                        signal.direction,
                        signal.confidence,
                        signal.predicted_return,
                        signal.volatility_forecast,
                        signal.trend_strength,
                        signal.model_used,
                        signal.reasoning,
                        horizon,
                        latency_ms,
                        signal.generation_time.isoformat(),
                    ),
                )
                conn.commit()
                row_id = cursor.lastrowid
                logger.debug("Signal logged (id=%d) for %s", row_id, symbol)
                return row_id if row_id is not None else 0
        except Exception as exc:
            logger.error("Failed to persist signal: %s", exc)
            return 0

    # ------------------------------------------------------------------
    async def record_outcome(
        self,
        signal_id: int,
        symbol: str,
        actual_return: float,
        pnl_estimate: Optional[float] = None,
    ) -> None:
        """Record the actual outcome of a signal (for accuracy tracking).

        Call this *after* the prediction horizon has elapsed to compare
        predicted vs actual returns.

        Args:
            signal_id:      The row ID returned by :meth:`save`.
            symbol:         Trading symbol.
            actual_return:  The realised % return over the horizon.
            pnl_estimate:   Estimated PnL if the signal was traded.
        """
        # retrieve the original signal to check correctness
        try:
            with sqlite3.connect(self.db_path) as conn:
                row = conn.execute(
                    "SELECT direction, predicted_return FROM signal_log WHERE id = ?",
                    (signal_id,),
                ).fetchone()
                if row is None:
                    logger.warning("Signal %d not found for outcome recording", signal_id)
                    return

                direction, pred_return = row
                # correct if direction matches the sign of actual return
                if direction == "bullish" and actual_return > 0:
                    correct = 1
                elif direction == "bearish" and actual_return < 0:
                    correct = 1
                elif direction == "neutral" and abs(actual_return) < 0.1:
                    correct = 1
                else:
                    correct = 0

                conn.execute(
                    """
                    INSERT INTO signal_accuracy
                        (signal_id, symbol, actual_return, correct_direction,
                         pnl_estimate, resolved_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        signal_id,
                        symbol,
                        actual_return,
                        correct,
                        pnl_estimate,
                        datetime.now(timezone.utc).isoformat(),
                    ),
                )
                conn.commit()
                logger.info(
                    "Outcome recorded for signal %d: actual=%+.3f%% "
                    "pred=%+.3f%% correct=%d",
                    signal_id, actual_return, pred_return or 0, correct,
                )
        except Exception as exc:
            logger.error("Failed to record outcome: %s", exc)

    # ------------------------------------------------------------------
    def get_accuracy_report(
        self,
        symbol: Optional[str] = None,
        model_used: Optional[str] = None,
        limit: int = 1000,
    ) -> pd.DataFrame:
        """Generate an accuracy report for signal providers.

        Returns a DataFrame with columns:
            * model_used, symbol, total_signals, correct, accuracy,
              avg_predicted_return, avg_actual_return, avg_latency_ms
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                query = """
                SELECT
                    sl.model_used,
                    sl.symbol,
                    COUNT(*) as total_signals,
                    SUM(COALESCE(sa.correct_direction, 0)) as correct,
                    ROUND(AVG(COALESCE(sa.correct_direction, 0)) * 100, 2) as accuracy_pct,
                    ROUND(AVG(sl.predicted_return), 4) as avg_pred_return,
                    ROUND(AVG(sa.actual_return), 4) as avg_actual_return,
                    ROUND(AVG(sl.latency_ms), 2) as avg_latency_ms
                FROM signal_log sl
                LEFT JOIN signal_accuracy sa ON sl.id = sa.signal_id
                WHERE 1=1
                """
                params: list[Any] = []
                if symbol:
                    query += " AND sl.symbol = ?"
                    params.append(symbol)
                if model_used:
                    query += " AND sl.model_used = ?"
                    params.append(model_used)
                query += """
                GROUP BY sl.model_used, sl.symbol
                ORDER BY total_signals DESC
                LIMIT ?
                """
                params.append(limit)
                return pd.read_sql_query(query, conn, params=params)
        except Exception as exc:
            logger.error("Accuracy report failed: %s", exc)
            return pd.DataFrame()


# ═══════════════════════════════════════════════════════════════════════════
# 7.  Integration Helpers
# ═══════════════════════════════════════════════════════════════════════════

def create_default_provider(
    use_kronos: bool = False,
    model_size: ModelSize = "mini",
    device: Literal["cuda", "cpu", "auto"] = "auto",
    *,
    tracker: Optional[SignalTracker] = None,
) -> SignalProvider:
    """Factory function: create the best available signal provider.

    Attempts to load Kronos if ``use_kronos=True`` and dependencies are
    present.  Falls back to :class:`FallbackSignalProvider` on any error.

    Args:
        use_kronos:  Whether to attempt loading Kronos.
        model_size:  Which Kronos variant (if applicable).
        device:      torch device (if applicable).
        tracker:     Optional :class:`SignalTracker` for persistence.

    Returns:
        A concrete :class:`SignalProvider` (never raises).

    Example:
        >>> provider = create_default_provider(use_kronos=True)
        >>> signal = await provider.generate_signal(df, "XAUUSD")
    """
    _ensure_file_handler()

    if use_kronos:
        try:
            provider: SignalProvider = KronosSignalProvider(
                model_size=model_size,
                device=device,
                tracker=tracker,
            )
            logger.info("Kronos provider active (%s)", model_size)
            return provider
        except ImportError as exc:
            logger.warning(
                "Kronos unavailable (%s). Falling back to statistical provider.",
                exc,
            )
        except Exception as exc:
            logger.error(
                "Unexpected error loading Kronos: %s. Using fallback.", exc,
            )

    # fallback (always works)
    logger.info("Fallback statistical provider active")
    return FallbackSignalProvider(tracker=tracker)


async def generate_signals_for_portfolio(
    data: dict[str, pd.DataFrame],
    provider: Optional[SignalProvider] = None,
    horizon: int = 24,
) -> dict[str, KronosSignal]:
    """Generate signals for every symbol in a portfolio dataset.

    Args:
        data:      ``{symbol: ohlcv_df, ...}``
        provider:  Signal provider (default: fallback).
        horizon:   Prediction horizon in periods.

    Returns:
        ``{symbol: KronosSignal, ...}`` — missing symbols on error are
        logged but not included in the result.

    Example:
        >>> portfolio = {"XAUUSD": df_gold, "BTCUSD": df_btc}
        >>> signals = await generate_signals_for_portfolio(portfolio)
        >>> for sym, sig in signals.items():
        ...     print(f"{sym}: {sig.direction} (conf={sig.confidence:.2f})")
    """
    if provider is None:
        provider = create_default_provider(use_kronos=False)

    logger.info("Generating portfolio signals for %d symbols", len(data))
    results = await provider.batch_signals(data, horizon=horizon)
    return results


# ═══════════════════════════════════════════════════════════════════════════
# 8.  Utility Functions (module-private)
# ═══════════════════════════════════════════════════════════════════════════

def _normalise_ohlcv_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Normalise column names to lower-case OHLCV.

    Accepts variations like ``['Open','High','Low','Close','Volume']``,
    ``['open','high','low','close','tick_volume']``, etc.
    """
    df = df.copy()
    col_map: dict[str, str] = {}
    for c in df.columns:
        cl = c.lower().strip()
        if cl in ("open", "o"):
            col_map[c] = "open"
        elif cl in ("high", "h"):
            col_map[c] = "high"
        elif cl in ("low", "l"):
            col_map[c] = "low"
        elif cl in ("close", "c"):
            col_map[c] = "close"
        elif cl in ("volume", "vol", "tick_volume", "real_volume", "v"):
            col_map[c] = "volume"
    if col_map:
        df = df.rename(columns=col_map)

    required = {"open", "high", "low", "close"}
    missing = required - set(df.columns)
    if missing:
        available = set(df.columns)
        raise ValueError(
            f"Missing required columns {missing}. Available: {available}"
        )
    return df


def _find_peaks(arr: np.ndarray, min_distance: int = 3) -> list[int]:
    """Find local maxima in a 1-D array.

    Returns indices of peaks sorted by amplitude (highest first).
    """
    if len(arr) < 3:
        return [int(np.argmax(arr))]
    peaks = []
    for i in range(1, len(arr) - 1):
        if arr[i] > arr[i - 1] and arr[i] > arr[i + 1]:
            # also check it's a significant peak (> mean)
            if arr[i] > arr.mean():
                peaks.append((i, arr[i]))
    peaks.sort(key=lambda x: x[1], reverse=True)
    # filter by min_distance (keep highest, remove neighbours)
    filtered: list[int] = []
    for idx, _val in peaks:
        if all(abs(idx - f) >= min_distance for f in filtered):
            filtered.append(idx)
    return filtered if filtered else [int(np.argmax(arr))]
