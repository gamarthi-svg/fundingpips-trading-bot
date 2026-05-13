"""
data_loader.py - Historical OHLCV data loader for prop firm trading bot backtesting.

Supports multiple data sources:
    - MetaAPI Cloud (primary, for FundingPips/MetaTrader data)
    - Local CSV files (offline backtesting)
    - yfinance (fallback for Yahoo Finance)
    - Synthetic data generator (for unit testing and strategy development)

Instruments: XAUUSD (Gold), NQ (Nasdaq futures), EURUSD, GBPUSD, USDJPY
Timeframes: M1, M5, M15, M30, H1, H4, D1, W1
"""

from __future__ import annotations

import asyncio
import logging
import os
import random
import warnings
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional MetaAPI SDK — import gracefully
# ---------------------------------------------------------------------------
try:
    from metaapi_cloud_sdk import MetaApi
    from metaapi_cloud_sdk.clients.metaApi.provisioningProfile_client import (
        NewProvisioningProfileDto,
    )

    HAS_METAAPI = True
except ImportError:
    HAS_METAAPI = False
    warnings.warn(
        "metaapi_cloud_sdk not installed. MetaAPI source will be unavailable. "
        "Install with: pip install metaapi-cloud-sdk",
        ImportWarning,
        stacklevel=2,
    )

# ---------------------------------------------------------------------------
# Optional yfinance — import gracefully
# ---------------------------------------------------------------------------
try:
    import yfinance as yf

    HAS_YFINANCE = True
except ImportError:
    HAS_YFINANCE = False

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Valid timeframe strings (internal format → MetaAPI format)
TIMEFRAME_MAP: Dict[str, str] = {
    "M1": "1m",
    "M5": "5m",
    "M15": "15m",
    "M30": "30m",
    "H1": "1h",
    "H4": "4h",
    "D1": "1d",
    "W1": "1w",
}

# Reverse mapping: MetaAPI → internal
METAAPI_TF_MAP: Dict[str, str] = {v: k for k, v in TIMEFRAME_MAP.items()}

VALID_TIMEFRAMES: List[str] = list(TIMEFRAME_MAP.keys())

# Symbol normalization rules (variant → canonical)
SYMBOL_ALIASES: Dict[str, str] = {
    # Gold variants
    "GOLD": "XAUUSD",
    "XAU/USD": "XAUUSD",
    "XAU_USD": "XAUUSD",
    # Nasdaq variants
    "NAS100": "NQ",
    "USTEC": "NQ",
    "NASDAQ": "NQ",
    "NDX": "NQ",
    # EURUSD variants
    "EUR/USD": "EURUSD",
    "EUR_USD": "EURUSD",
    # GBPUSD variants
    "GBP/USD": "GBPUSD",
    "GBP_USD": "GBPUSD",
    # USDJPY variants
    "USD/JPY": "USDJPY",
    "USD_JPY": "USDJPY",
}

CANONICAL_SYMBOLS: List[str] = ["XAUUSD", "NQ", "EURUSD", "GBPUSD", "USDJPY"]

# Default data directory (relative to package root)
DEFAULT_DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def normalize_symbol(symbol: str) -> str:
    """Normalize a symbol string to canonical form.

    Args:
        symbol: Raw symbol string (e.g. 'gold', 'XAU/USD', 'NAS100')

    Returns:
        Canonical symbol (e.g. 'XAUUSD', 'NQ', 'EURUSD')

    Raises:
        ValueError: If symbol cannot be mapped to a known canonical form.
    """
    sym = symbol.strip().upper()
    if sym in CANONICAL_SYMBOLS:
        return sym
    if sym in SYMBOL_ALIASES:
        return SYMBOL_ALIASES[sym]
    raise ValueError(
        f"Unknown symbol: {symbol!r}. "
        f"Known symbols: {CANONICAL_SYMBOLS + list(SYMBOL_ALIASES.keys())}"
    )


def validate_timeframe(tf: str) -> str:
    """Validate and normalize a timeframe string.

    Args:
        tf: Timeframe string (e.g. 'M15', 'H1', '1h')

    Returns:
        Normalized internal timeframe (e.g. 'M15', 'H1')

    Raises:
        ValueError: If timeframe is not supported.
    """
    tf_upper = tf.strip().upper()
    if tf_upper in VALID_TIMEFRAMES:
        return tf_upper
    # Try reverse mapping from MetaAPI format
    if tf.lower() in METAAPI_TF_MAP:
        return METAAPI_TF_MAP[tf.lower()]
    raise ValueError(
        f"Unsupported timeframe: {tf!r}. "
        f"Supported: {VALID_TIMEFRAMES}"
    )


def timeframe_to_minutes(tf: str) -> int:
    """Convert a timeframe to its duration in minutes.

    Args:
        tf: Internal timeframe string (e.g. 'M15', 'H1', 'D1')

    Returns:
        Number of minutes per candle.
    """
    mapping = {
        "M1": 1,
        "M5": 5,
        "M15": 15,
        "M30": 30,
        "H1": 60,
        "H4": 240,
        "D1": 1440,
        "W1": 10080,
    }
    return mapping.get(tf, 1)


def minutes_to_timeframe(minutes: int) -> str:
    """Convert minutes to the closest valid timeframe.

    Args:
        minutes: Candle duration in minutes.

    Returns:
        Internal timeframe string.
    """
    pairs = [
        (10080, "W1"),
        (1440, "D1"),
        (240, "H4"),
        (60, "H1"),
        (30, "M30"),
        (15, "M15"),
        (5, "M5"),
        (1, "M1"),
    ]
    for threshold, tf in pairs:
        if minutes >= threshold:
            return tf
    return "M1"


# ---------------------------------------------------------------------------
# DataLoader class
# ---------------------------------------------------------------------------


class DataLoader:
    """Loads historical OHLCV data from multiple sources.

    Supports MetaAPI Cloud (primary for FundingPips), local CSV files,
    yfinance as a fallback, and synthetic data generation for testing.

    Example:
        loader = DataLoader(source="csv", data_dir="./data")
        df = asyncio.run(loader.fetch_candles("XAUUSD", "H1", start, end))
    """

    def __init__(
        self,
        source: str = "metaapi",
        token: Optional[str] = None,
        account_id: Optional[str] = None,
        data_dir: Optional[Union[str, Path]] = None,
    ):
        """Initialise the DataLoader.

        Args:
            source: Data source identifier. One of "metaapi", "csv", "yfinance".
            token: MetaAPI access token (required when source="metaapi").
            account_id: MetaAPI account ID (required when source="metaapi").
            data_dir: Directory for CSV caching/loading. Defaults to ``../data``
                relative to this file.
        """
        self.source = source.lower().strip()
        self.token = token
        self.account_id = account_id
        self.data_dir = Path(data_dir) if data_dir else DEFAULT_DATA_DIR
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # Validate source
        valid_sources = ["metaapi", "csv", "yfinance", "synthetic"]
        if self.source not in valid_sources:
            raise ValueError(
                f"Unknown source: {source!r}. Choose from {valid_sources}"
            )

        # Validate MetaAPI prerequisites
        if self.source == "metaapi":
            if not HAS_METAAPI:
                raise ImportError(
                    "metaapi_cloud_sdk is required for MetaAPI source. "
                    "Install: pip install metaapi-cloud-sdk"
                )
            if not self.token:
                raise ValueError("MetaAPI token is required when source='metaapi'")
            if not self.account_id:
                raise ValueError("MetaAPI account_id is required when source='metaapi'")

        logger.info(
            "DataLoader initialised | source=%s data_dir=%s",
            self.source,
            self.data_dir,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def fetch_candles(
        self,
        symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime,
        use_cache: bool = True,
    ) -> pd.DataFrame:
        """Fetch historical candles for a symbol and timeframe.

        Delegates to the configured source.  When *use_cache* is True and the
        source is not ``"csv"``, data is first looked up from cached CSV files
        before hitting the remote API, and the result is saved back to cache.

        Args:
            symbol: Trading symbol (e.g. ``"XAUUSD"``).
            timeframe: Timeframe string (e.g. ``"H1"``, ``"M15"``).
            start: Start of the requested range (timezone-aware preferred).
            end: End of the requested range (timezone-aware preferred).
            use_cache: Whether to read from / write to local CSV cache.

        Returns:
            DataFrame with columns:
            ``time, open, high, low, close, tick_volume, spread``
            sorted by ``time`` ascending.

        Raises:
            ValueError: On invalid parameters.
            RuntimeError: On failure to fetch data from any source.
        """
        # --- normalise inputs ---
        sym = normalize_symbol(symbol)
        tf = validate_timeframe(timeframe)

        if end <= start:
            raise ValueError(f"'end' must be after 'start': {start} -> {end}")

        # Ensure timezone-aware
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)

        logger.info(
            "fetch_candles | symbol=%s timeframe=%s range=%s -> %s",
            sym,
            tf,
            start.isoformat(),
            end.isoformat(),
        )

        # --- try CSV cache first ---
        if use_cache and self.source != "csv":
            cached_df = self._load_cached(sym, tf, start, end)
            if cached_df is not None and not cached_df.empty:
                logger.info(
                    "Returning %d rows from CSV cache for %s %s",
                    len(cached_df),
                    sym,
                    tf,
                )
                return cached_df

        # --- delegate to source ---
        if self.source == "metaapi":
            df = self.fetch_from_metaapi(sym, tf, start, end)
        elif self.source == "csv":
            df = self.fetch_from_csv(sym, tf)
            # Filter to requested range
            if not df.empty and "time" in df.columns:
                df = df[(df["time"] >= start) & (df["time"] <= end)].copy()
        elif self.source == "yfinance":
            df = self.fetch_from_yfinance(sym, tf, start, end)
        elif self.source == "synthetic":
            df = generate_synthetic_data(sym, tf, start, end)
        else:
            raise RuntimeError(f"Unhandled source: {self.source}")

        if df.empty:
            raise RuntimeError(
                f"No data returned for {sym} {tf} from {self.source}"
            )

        # Ensure standard columns
        df = self._standardise_columns(df)
        df = df.sort_values("time").reset_index(drop=True)

        # --- save to cache ---
        if use_cache and self.source != "csv":
            self.save_to_csv(df, sym, tf)

        logger.info(
            "fetch_candles complete | symbol=%s timeframe=%s rows=%d",
            sym,
            tf,
            len(df),
        )
        return df

    def fetch_from_metaapi(
        self,
        symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime,
    ) -> pd.DataFrame:
        """Fetch historical candles from MetaAPI Cloud (synchronous wrapper).

        MetaAPI's ``get_candles`` returns up to 1 000 candles per request, so
        pagination is handled automatically.

        Args:
            symbol: Canonical symbol (e.g. ``"XAUUSD"``).
            timeframe: Internal timeframe (e.g. ``"H1"``).
            start: Start datetime.
            end: End datetime.

        Returns:
            Raw DataFrame from MetaAPI with standard columns added if missing.
        """
        if not HAS_METAAPI:
            raise ImportError("metaapi_cloud_sdk not installed")

        meta_tf = self.get_timeframe_metaapi(timeframe)
        sym = normalize_symbol(symbol)

        logger.info(
            "MetaAPI fetch | symbol=%s tf=%s (meta: %s) range=%s -> %s",
            sym,
            timeframe,
            meta_tf,
            start.isoformat(),
            end.isoformat(),
        )

        # Run async MetaAPI code in a temporary event loop
        try:
            loop = asyncio.get_running_loop()
            # If we're already in an async context, use run_coroutine_threadsafe
            # or nest_asyncio.  For simplicity we call the sync helper.
            df = self._run_metaapi_sync(sym, meta_tf, start, end)
        except RuntimeError:
            df = asyncio.run(self._fetch_metaapi_async(sym, meta_tf, start, end))

        return df

    def _run_metaapi_sync(
        self,
        symbol: str,
        meta_tf: str,
        start: datetime,
        end: datetime,
    ) -> pd.DataFrame:
        """Synchronous bridge to MetaAPI async API."""
        # Create a fresh loop to avoid conflicts with existing loops
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            df = loop.run_until_complete(
                self._fetch_metaapi_async(symbol, meta_tf, start, end)
            )
            return df
        finally:
            loop.close()
            asyncio.set_event_loop(None)

    async def _fetch_metaapi_async(
        self,
        symbol: str,
        meta_tf: str,
        start: datetime,
        end: datetime,
    ) -> pd.DataFrame:
        """Async implementation of MetaAPI paginated fetch."""
        api = MetaApi(self.token)
        account = await api.metatrader_account_api.get_account(self.account_id)
        connection = account.get_streaming_connection()
        await connection.connect()
        await connection.wait_synchronized()

        try:
            # Estimate total candles needed
            minutes_per_candle = timeframe_to_minutes(
                METAAPI_TF_MAP.get(meta_tf, "H1")
            )
            total_minutes = int((end - start).total_seconds() / 60)
            estimated_candles = max(total_minutes // minutes_per_candle, 1000)

            all_candles: List[dict] = []
            current_start = start
            max_pages = max(estimated_candles // 1000 + 5, 50)
            page = 0

            while current_start < end and page < max_pages:
                page += 1
                # MetaAPI uses start_index based pagination
                # We'll use startTime parameter if available, otherwise index-based
                try:
                    candles = await connection.get_candles(
                        symbol=symbol,
                        timeframe=meta_tf,
                        start_time=current_start.isoformat(),
                        limit=1000,
                    )
                except TypeError:
                    # Fallback: some MetaAPI versions don't support start_time
                    # Use index-based pagination
                    start_index = len(all_candles)
                    candles = await connection.get_candles(
                        symbol=symbol,
                        timeframe=meta_tf,
                        start_index=start_index,
                        limit=1000,
                    )

                if not candles:
                    break

                # Filter candles within range
                for c in candles:
                    c_time = pd.to_datetime(c["time"])
                    if c_time.tzinfo is None:
                        c_time = c_time.replace(tzinfo=timezone.utc)
                    if start <= c_time <= end:
                        all_candles.append(c)
                    elif c_time > end:
                        break

                # Update current_start from last candle
                if candles:
                    last_time = pd.to_datetime(candles[-1]["time"])
                    if last_time.tzinfo is None:
                        last_time = last_time.replace(tzinfo=timezone.utc)
                    if last_time <= current_start:
                        # No progress — avoid infinite loop
                        break
                    current_start = last_time
                else:
                    break

            if not all_candles:
                logger.warning("No candles returned from MetaAPI")
                return pd.DataFrame()

            df = pd.DataFrame(all_candles)
            logger.info(
                "MetaAPI returned %d candles for %s %s", len(df), symbol, meta_tf
            )
            return df

        finally:
            await connection.close()

    def fetch_from_csv(
        self,
        symbol: str,
        timeframe: str,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
    ) -> pd.DataFrame:
        """Load historical data from a local CSV file.

        Expected filename format: ``{symbol}_{timeframe}.csv``
        Expected columns: ``time, open, high, low, close, volume``
        (``spread`` and ``tick_volume`` are optional).

        Args:
            symbol: Canonical symbol.
            timeframe: Internal timeframe.
            start: Optional filter start.
            end: Optional filter end.

        Returns:
            DataFrame with standardised columns.
        """
        sym = normalize_symbol(symbol)
        tf = validate_timeframe(timeframe)
        filepath = self.data_dir / f"{sym}_{tf}.csv"

        logger.info("CSV load | path=%s", filepath)

        if not filepath.exists():
            logger.error("CSV file not found: %s", filepath)
            # Try alternative filenames
            alt_paths = [
                self.data_dir / f"{sym.lower()}_{tf.lower()}.csv",
                self.data_dir / f"{sym}_{tf.lower()}.csv",
                self.data_dir / f"{sym}_{METAAPI_TF_MAP.get(tf, tf)}.csv",
            ]
            for alt in alt_paths:
                if alt.exists():
                    filepath = alt
                    logger.info("Found alternative CSV: %s", filepath)
                    break
            else:
                return pd.DataFrame()

        try:
            df = pd.read_csv(
                filepath,
                parse_dates=["time"],
                dtype={
                    "open": np.float64,
                    "high": np.float64,
                    "low": np.float64,
                    "close": np.float64,
                    "volume": np.float64,
                },
            )
        except Exception as exc:
            logger.error("Failed to read CSV %s: %s", filepath, exc)
            return pd.DataFrame()

        # Ensure time column is datetime
        if "time" in df.columns:
            df["time"] = pd.to_datetime(df["time"], utc=True)

        if start is not None and end is not None:
            df = df[(df["time"] >= start) & (df["time"] <= end)].copy()

        logger.info("CSV loaded | rows=%d path=%s", len(df), filepath)
        return df

    def fetch_from_yfinance(
        self,
        symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime,
    ) -> pd.DataFrame:
        """Fetch data from Yahoo Finance as a fallback source.

        Maps canonical symbols to Yahoo ticker symbols.

        Args:
            symbol: Canonical symbol.
            timeframe: Internal timeframe.
            start: Start date.
            end: End date.

        Returns:
            DataFrame with standard columns.
        """
        if not HAS_YFINANCE:
            raise ImportError("yfinance not installed. Run: pip install yfinance")

        sym = normalize_symbol(symbol)

        # Map canonical symbol to Yahoo Finance ticker
        yf_tickers = {
            "XAUUSD": "GC=F",      # Gold futures
            "NQ": "NQ=F",          # Nasdaq-100 futures
            "EURUSD": "EURUSD=X",  # EUR/USD
            "GBPUSD": "GBPUSD=X",  # GBP/USD
            "USDJPY": "USDJPY=X",  # USD/JPY
        }
        ticker = yf_tickers.get(sym, sym)

        # Map timeframe to yfinance interval
        interval_map = {
            "M1": "1m",
            "M5": "5m",
            "M15": "15m",
            "M30": "30m",
            "H1": "1h",
            "H4": "1h",   # yfinance doesn't have 4h; we'll resample
            "D1": "1d",
            "W1": "1wk",
        }
        interval = interval_map.get(timeframe, "1h")

        logger.info(
            "yfinance fetch | ticker=%s interval=%s range=%s -> %s",
            ticker,
            interval,
            start.date(),
            end.date(),
        )

        try:
            yf_ticker = yf.Ticker(ticker)
            df = yf_ticker.history(
                start=start.date(),
                end=end.date(),
                interval=interval,
            )
        except Exception as exc:
            logger.error("yfinance fetch failed: %s", exc)
            return pd.DataFrame()

        if df.empty:
            logger.warning("yfinance returned empty DataFrame for %s", ticker)
            return pd.DataFrame()

        # Reset index to get 'time' column
        df = df.reset_index()

        # Rename columns to standard format
        rename_map = {
            "Date": "time",
            "Datetime": "time",
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Volume": "tick_volume",
        }
        df = df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns})

        # Ensure time column
        if "time" not in df.columns:
            logger.error("yfinance DataFrame missing 'time' column. Columns: %s", df.columns.tolist())
            return pd.DataFrame()

        df["time"] = pd.to_datetime(df["time"], utc=True)

        # Resample to H4 if needed (from 1h)
        if timeframe == "H4" and interval == "1h":
            df = self._resample_to_timeframe(df, "H4")

        logger.info("yfinance returned %d rows for %s", len(df), ticker)
        return df

    def save_to_csv(
        self,
        df: pd.DataFrame,
        symbol: str,
        timeframe: str,
    ) -> Path:
        """Save fetched data to CSV for caching.

        Args:
            df: DataFrame with standard columns.
            symbol: Canonical symbol.
            timeframe: Internal timeframe.

        Returns:
            Path to the saved file.
        """
        sym = normalize_symbol(symbol)
        tf = validate_timeframe(timeframe)
        filepath = self.data_dir / f"{sym}_{tf}.csv"

        # Ensure required columns exist
        df_out = df.copy()
        for col in ["open", "high", "low", "close"]:
            if col not in df_out.columns:
                logger.warning("Column '%s' missing — cannot save to CSV", col)
                return filepath

        try:
            # Sort by time before saving
            df_out = df_out.sort_values("time").reset_index(drop=True)
            df_out.to_csv(filepath, index=False)
            logger.info("Saved %d rows to %s", len(df_out), filepath)
        except Exception as exc:
            logger.error("Failed to save CSV %s: %s", filepath, exc)

        return filepath

    def get_timeframe_metaapi(self, tf: str) -> str:
        """Convert internal timeframe string to MetaAPI format.

        Args:
            tf: Internal timeframe (e.g. ``"M15"``, ``"H1"``).

        Returns:
            MetaAPI timeframe string (e.g. ``"15m"``, ``"1h"``).
        """
        tf = validate_timeframe(tf)
        return TIMEFRAME_MAP[tf]

    def available_data_range(self, symbol: str, timeframe: str) -> Tuple[datetime, datetime]:
        """Return the available date range for cached CSV data.

        Args:
            symbol: Canonical symbol.
            timeframe: Internal timeframe.

        Returns:
            Tuple of (earliest, latest) datetime. Returns (epoch, epoch) if no data.
        """
        sym = normalize_symbol(symbol)
        tf = validate_timeframe(timeframe)
        filepath = self.data_dir / f"{sym}_{tf}.csv"

        if not filepath.exists():
            epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
            return epoch, epoch

        try:
            df = pd.read_csv(filepath, usecols=["time"], parse_dates=["time"])
            df["time"] = pd.to_datetime(df["time"], utc=True)
            return df["time"].min(), df["time"].max()
        except Exception as exc:
            logger.error("Failed to read range from %s: %s", filepath, exc)
            epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
            return epoch, epoch

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _standardise_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        """Ensure DataFrame has all standard columns with correct types.

        Standard columns: ``time, open, high, low, close, tick_volume, spread``
        """
        df = df.copy()

        # Required OHLC columns
        required = ["time", "open", "high", "low", "close"]
        for col in required:
            if col not in df.columns:
                logger.warning("Required column '%s' missing — filling with NaN", col)
                df[col] = np.nan

        # Ensure numeric
        for col in ["open", "high", "low", "close"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")

        # Volume columns (MetaAPI uses ``tickVolume`` or ``volume``)
        if "tick_volume" not in df.columns:
            if "tickVolume" in df.columns:
                df["tick_volume"] = df["tickVolume"]
            elif "volume" in df.columns:
                df["tick_volume"] = df["volume"]
            elif "Volume" in df.columns:
                df["tick_volume"] = df["Volume"]
            else:
                df["tick_volume"] = 0
        df["tick_volume"] = pd.to_numeric(df["tick_volume"], errors="coerce").fillna(0)

        # Spread
        if "spread" not in df.columns:
            if "Spread" in df.columns:
                df["spread"] = df["Spread"]
            elif "spread" in df.columns:
                pass
            else:
                df["spread"] = 0.0
        df["spread"] = pd.to_numeric(df["spread"], errors="coerce").fillna(0.0)

        # Ensure time is datetime
        df["time"] = pd.to_datetime(df["time"], utc=True)

        return df[required + ["tick_volume", "spread"]]

    def _load_cached(
        self,
        symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime,
    ) -> Optional[pd.DataFrame]:
        """Attempt to serve request entirely from cached CSV data.

        Returns ``None`` if cache does not fully cover the requested range.
        """
        cached_start, cached_end = self.available_data_range(symbol, timeframe)
        if cached_start == cached_end:  # no cache
            return None
        if cached_start > start or cached_end < end:
            logger.debug(
                "Cache range [%s, %s] does not cover request [%s, %s]",
                cached_start,
                cached_end,
                start,
                end,
            )
            return None

        df = self.fetch_from_csv(symbol, timeframe, start, end)
        if df.empty:
            return None
        return df

    def _resample_to_timeframe(self, df: pd.DataFrame, tf: str) -> pd.DataFrame:
        """Resample a DataFrame to a higher timeframe.

        Used internally when yfinance doesn't support the exact timeframe
        (e.g. 4h from 1h).
        """
        if tf == "H4":
            freq = "4h"
        elif tf == "H1":
            freq = "1h"
        elif tf == "D1":
            freq = "1D"
        else:
            return df

        df = df.set_index("time")
        resampled = df.resample(freq).agg({
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "tick_volume": "sum",
            "spread": "mean",
        }).dropna()
        resampled = resampled.reset_index()
        return resampled


# ---------------------------------------------------------------------------
# Synthetic data generator
# ---------------------------------------------------------------------------


def generate_synthetic_data(
    symbol: str,
    timeframe: str,
    start: datetime,
    end: datetime,
    seed: Optional[int] = None,
    trend: float = 0.0,
    volatility: Optional[float] = None,
    gap_probability: float = 0.15,
) -> pd.DataFrame:
    """Generate realistic synthetic OHLCV data for testing.

    Uses a geometric Brownian motion model with realistic volatility and
    occasional price gaps (simulating weekend/holiday gaps).

    Args:
        symbol: Canonical symbol (used to set realistic price levels).
        timeframe: Internal timeframe.
        start: Start datetime.
        end: End datetime.
        seed: Random seed for reproducibility.
        trend: Annualised drift (e.g. 0.05 = +5%%/year).
        volatility: Annualised volatility. If ``None``, uses realistic defaults.
        gap_probability: Probability of a gap between consecutive candles.

    Returns:
        DataFrame with columns ``time, open, high, low, close, tick_volume, spread``.
    """
    if seed is not None:
        np.random.seed(seed)
        random.seed(seed)

    sym = normalize_symbol(symbol)
    tf = validate_timeframe(timeframe)

    # Realistic base prices and default volatilities
    asset_params = {
        "XAUUSD": {"base_price": 2000.0, "vol": 0.15, "spread": 0.40},
        "NQ":     {"base_price": 15000.0, "vol": 0.20, "spread": 1.50},
        "EURUSD": {"base_price": 1.0800, "vol": 0.08, "spread": 0.00015},
        "GBPUSD": {"base_price": 1.2600, "vol": 0.09, "spread": 0.00020},
        "USDJPY": {"base_price": 150.00, "vol": 0.10, "spread": 0.015},
    }
    params = asset_params.get(sym, {"base_price": 100.0, "vol": 0.15, "spread": 0.10})

    base_price = params["base_price"]
    annual_vol = volatility if volatility is not None else params["vol"]
    spread = params["spread"]

    # Generate time index
    minutes = timeframe_to_minutes(tf)
    num_candles = int((end - start).total_seconds() / 60 / minutes)
    if num_candles < 1:
        num_candles = 1

    # Trading hours filter: skip weekends for forex/CFD simulation
    times = []
    current = start
    while len(times) < num_candles and current <= end:
        # Skip weekends (Saturday=5, Sunday=6)
        if current.weekday() < 5:
            times.append(current)
        current += timedelta(minutes=minutes)

    if not times:
        times = pd.date_range(start=start, periods=num_candles, freq=f"{minutes}min").to_pydatetime().tolist()

    n = len(times)

    # GBM parameters scaled to candle frequency
    dt = minutes / (365.25 * 24 * 60)  # fraction of a year per candle
    drift = trend * dt
    vol_scale = annual_vol * np.sqrt(dt)

    # Generate returns
    returns = np.random.normal(drift, vol_scale, n)

    # Inject gaps
    gap_mask = np.random.random(n) < gap_probability
    gap_sizes = np.random.choice([-1, 1], size=n) * np.random.exponential(2 * vol_scale, n)
    returns[gap_mask] += gap_sizes[gap_mask]

    # Price series (close)
    price_series = base_price * np.exp(np.cumsum(returns))

    # Build OHLC from close with intrabar noise
    ohlc = np.zeros((n, 4))
    ohlc[:, 3] = price_series  # close

    for i in range(n):
        close = price_series[i]
        # Intrabar volatility (typically 30-50% of candle range)
        intrabar_vol = close * vol_scale * 0.4

        high_noise = abs(np.random.normal(0, intrabar_vol))
        low_noise = abs(np.random.normal(0, intrabar_vol))

        high = close + high_noise
        low = close - low_noise
        # Ensure high >= low
        if low > high:
            low, high = high, low

        # Open is close of previous + small noise, or base for first
        if i == 0:
            open_price = close * (1 + np.random.normal(0, vol_scale * 0.3))
        else:
            open_price = price_series[i - 1] * (1 + np.random.normal(0, vol_scale * 0.2))

        # Ensure ordering: low <= min(open, close) <= max(open, close) <= high
        low = min(low, open_price, close)
        high = max(high, open_price, close)

        ohlc[i] = [open_price, high, low, close]

    # Generate tick volume (realistic patterns)
    base_volume = {
        "M1": 500, "M5": 1500, "M15": 3000, "M30": 5000,
        "H1": 8000, "H4": 20000, "D1": 50000, "W1": 150000,
    }
    vol_base = base_volume.get(tf, 8000)
    volumes = np.random.lognormal(
        mean=np.log(vol_base),
        sigma=0.5,
        size=n,
    )

    df = pd.DataFrame({
        "time": times[:n],
        "open": ohlc[:, 0],
        "high": ohlc[:, 1],
        "low": ohlc[:, 2],
        "close": ohlc[:, 3],
        "tick_volume": volumes.astype(int),
        "spread": np.full(n, spread),
    })

    df["time"] = pd.to_datetime(df["time"], utc=True)
    df = df.sort_values("time").reset_index(drop=True)

    logger.info(
        "Synthetic data generated | symbol=%s tf=%s candles=%d price_range=%.2f-%.2f",
        sym,
        tf,
        n,
        df["low"].min(),
        df["high"].max(),
    )
    return df


# ---------------------------------------------------------------------------
# Convenience: synchronous wrapper
# ---------------------------------------------------------------------------

def load_data(
    symbol: str,
    timeframe: str,
    start: Union[datetime, str],
    end: Union[datetime, str],
    source: str = "synthetic",
    **kwargs,
) -> pd.DataFrame:
    """Synchronous convenience function to load data.

    Args:
        symbol: Trading symbol.
        timeframe: Timeframe string.
        start: Start datetime or ISO string.
        end: End datetime or ISO string.
        source: Data source (``"synthetic"``, ``"csv"``, ``"yfinance"``).
        **kwargs: Additional arguments passed to ``DataLoader``.

    Returns:
        DataFrame with OHLCV data.
    """
    if isinstance(start, str):
        start = datetime.fromisoformat(start.replace("Z", "+00:00"))
    if isinstance(end, str):
        end = datetime.fromisoformat(end.replace("Z", "+00:00"))

    loader = DataLoader(source=source, **kwargs)
    return asyncio.run(loader.fetch_candles(symbol, timeframe, start, end))


# ---------------------------------------------------------------------------
# Module-level test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    # Demo: generate synthetic XAUUSD H1 data
    start_dt = datetime(2024, 1, 1, tzinfo=timezone.utc)
    end_dt = datetime(2024, 1, 15, tzinfo=timezone.utc)

    loader = DataLoader(source="synthetic")
    df = asyncio.run(loader.fetch_candles("XAUUSD", "H1", start_dt, end_dt))
    print(df.head(10))
    print(f"\nTotal rows: {len(df)}")
    print(f"Columns: {df.columns.tolist()}")
    print(f"Date range: {df['time'].min()} -> {df['time'].max()}")
