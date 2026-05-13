"""
Trade journal logger using SQLite for persistent storage.

Provides the TradeLogger class for logging trades, calculating
performance metrics, and managing risk events.
"""

import logging
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import List, Optional

from journal.models import (
    DailySummary,
    PerformanceMetrics,
    RiskEvent,
    Trade,
)

logger = logging.getLogger(__name__)


class TradeLogger:
    """SQLite-backed trade journal logger.

    Manages persistent storage of trades, risk events, and daily
    summaries. Provides methods for logging trades, computing
    performance metrics, and querying historical data.

    Args:
        db_path: Filesystem path to the SQLite database file.
    """

    def __init__(self, db_path: str = "trades.db") -> None:
        """Initialize the logger and create required tables.

        Args:
            db_path: Path to the SQLite database file.
        """
        self.db_path = db_path
        self._ensure_tables()

    def _connect(self) -> sqlite3.Connection:
        """Create a database connection with row factory.

        Returns:
            sqlite3.Connection with Row factory enabled.
        """
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_tables(self) -> None:
        """Create all required tables if they do not exist."""
        conn = self._connect()
        try:
            cursor = conn.cursor()

            # Trades table
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticket INTEGER NOT NULL,
                    symbol TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    entry_price REAL NOT NULL,
                    exit_price REAL NOT NULL,
                    volume REAL NOT NULL,
                    sl REAL NOT NULL,
                    tp REAL NOT NULL,
                    open_time TEXT,
                    close_time TEXT,
                    profit REAL NOT NULL,
                    pips REAL NOT NULL,
                    strategy TEXT,
                    session TEXT,
                    phase TEXT,
                    account_balance REAL NOT NULL,
                    daily_pnl_before REAL NOT NULL,
                    zone TEXT
                )
                """
            )

            # Risk events table
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS risk_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    description TEXT NOT NULL,
                    daily_pnl REAL NOT NULL,
                    drawdown_pct REAL NOT NULL,
                    zone TEXT
                )
                """
            )

            # Daily summaries table
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS daily_summaries (
                    date TEXT PRIMARY KEY,
                    total_trades INTEGER NOT NULL DEFAULT 0,
                    wins INTEGER NOT NULL DEFAULT 0,
                    losses INTEGER NOT NULL DEFAULT 0,
                    gross_profit REAL NOT NULL DEFAULT 0.0,
                    gross_loss REAL NOT NULL DEFAULT 0.0,
                    net_pnl REAL NOT NULL DEFAULT 0.0,
                    max_dd REAL NOT NULL DEFAULT 0.0,
                    consistency_score REAL NOT NULL DEFAULT 0.0
                )
                """
            )

            # Indexes for common queries
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_trades_close_time "
                "ON trades(close_time)"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_trades_symbol "
                "ON trades(symbol)"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_trades_strategy "
                "ON trades(strategy)"
            )

            conn.commit()
            logger.info("TradeLogger tables ensured: trades, risk_events, daily_summaries")
        finally:
            conn.close()

    def log_trade(self, trade: Trade) -> int:
        """Insert a trade record into the database.

        Args:
            trade: The Trade dataclass to persist.

        Returns:
            The auto-generated row ID of the inserted trade.
        """
        conn = self._connect()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO trades (
                    ticket, symbol, direction, entry_price, exit_price,
                    volume, sl, tp, open_time, close_time, profit, pips,
                    strategy, session, phase, account_balance,
                    daily_pnl_before, zone
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    trade.ticket,
                    trade.symbol,
                    trade.direction,
                    trade.entry_price,
                    trade.exit_price,
                    trade.volume,
                    trade.sl,
                    trade.tp,
                    trade.open_time.isoformat() if trade.open_time else None,
                    trade.close_time.isoformat() if trade.close_time else None,
                    trade.profit,
                    trade.pips,
                    trade.strategy,
                    trade.session,
                    trade.phase,
                    trade.account_balance,
                    trade.daily_pnl_before,
                    trade.zone,
                ),
            )
            conn.commit()
            trade_id = cursor.lastrowid
            logger.info(
                "Logged trade ticket=%s symbol=%s profit=%.2f",
                trade.ticket,
                trade.symbol,
                trade.profit,
            )
            return trade_id if trade_id is not None else 0
        finally:
            conn.close()

    def get_trades(
        self,
        start_date: datetime,
        end_date: datetime,
        symbol: Optional[str] = None,
    ) -> List[Trade]:
        """Retrieve trades within a date range with optional symbol filter.

        Args:
            start_date: Inclusive start of the date range.
            end_date: Inclusive end of the date range.
            symbol: Optional trading instrument filter.

        Returns:
            List of Trade objects matching the criteria.
        """
        conn = self._connect()
        try:
            cursor = conn.cursor()
            params: List[Optional[str]] = [
                start_date.isoformat(),
                end_date.isoformat(),
            ]
            symbol_filter = ""
            if symbol:
                symbol_filter = "AND symbol = ?"
                params.append(symbol)

            cursor.execute(
                f"""
                SELECT * FROM trades
                WHERE close_time >= ? AND close_time <= ? {symbol_filter}
                ORDER BY close_time DESC
                """,
                params,
            )
            rows = cursor.fetchall()
            trades: List[Trade] = []
            for row in rows:
                row_dict = dict(row)
                trades.append(
                    Trade(
                        id=row_dict.get("id"),
                        ticket=row_dict.get("ticket", 0),
                        symbol=row_dict.get("symbol", ""),
                        direction=row_dict.get("direction", ""),
                        entry_price=row_dict.get("entry_price", 0.0),
                        exit_price=row_dict.get("exit_price", 0.0),
                        volume=row_dict.get("volume", 0.0),
                        sl=row_dict.get("sl", 0.0),
                        tp=row_dict.get("tp", 0.0),
                        open_time=self._parse_dt(row_dict.get("open_time")),
                        close_time=self._parse_dt(row_dict.get("close_time")),
                        profit=row_dict.get("profit", 0.0),
                        pips=row_dict.get("pips", 0.0),
                        strategy=row_dict.get("strategy", ""),
                        session=row_dict.get("session", ""),
                        phase=row_dict.get("phase", ""),
                        account_balance=row_dict.get("account_balance", 0.0),
                        daily_pnl_before=row_dict.get("daily_pnl_before", 0.0),
                        zone=row_dict.get("zone", ""),
                    )
                )
            logger.debug(
                "Retrieved %d trades from %s to %s",
                len(trades),
                start_date.date(),
                end_date.date(),
            )
            return trades
        finally:
            conn.close()

    def get_performance_metrics(self) -> PerformanceMetrics:
        """Calculate aggregated performance metrics from all trades.

        Returns:
            PerformanceMetrics dataclass with computed values.
        """
        conn = self._connect()
        try:
            cursor = conn.cursor()

            cursor.execute(
                """
                SELECT
                    COUNT(*) as total_trades,
                    SUM(CASE WHEN profit > 0 THEN 1 ELSE 0 END) as wins,
                    SUM(CASE WHEN profit < 0 THEN 1 ELSE 0 END) as losses,
                    SUM(CASE WHEN profit > 0 THEN profit ELSE 0 END) as gross_profit,
                    SUM(CASE WHEN profit < 0 THEN ABS(profit) ELSE 0 END) as gross_loss,
                    SUM(profit) as net_pnl,
                    AVG(profit) as avg_profit
                FROM trades
                """
            )
            row = cursor.fetchone()
            if row is None or row["total_trades"] == 0:
                return PerformanceMetrics()

            total_trades = row["total_trades"] or 0
            wins = row["wins"] or 0
            gross_profit = row["gross_profit"] or 0.0
            gross_loss = row["gross_loss"] or 0.0
            net_pnl = row["net_pnl"] or 0.0
            avg_profit = row["avg_profit"] or 0.0

            win_rate = (wins / total_trades * 100) if total_trades > 0 else 0.0
            profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else float("inf")

            # Compute standard deviation of profits in Python
            # (SQLite stddev function may not be available)
            cursor.execute("SELECT profit FROM trades")
            profit_rows = cursor.fetchall()
            profits = [r["profit"] for r in profit_rows if r["profit"] is not None]
            std_profit = self._compute_std(profits) if profits else 0.0

            # Sharpe ratio: annualized from daily returns
            # Simplified: use per-trade returns, assume ~1 trade/day for annualization
            if std_profit > 0:
                sharpe_ratio = (avg_profit / std_profit) * (252**0.5)
            else:
                sharpe_ratio = 0.0

            # Maximum drawdown from equity curve
            cursor.execute(
                """
                SELECT close_time, profit, account_balance
                FROM trades
                ORDER BY close_time ASC
                """
            )
            equity_rows = cursor.fetchall()
            max_dd = self._calculate_max_drawdown(equity_rows)

            # Total return (assuming starting balance ~ first trade balance)
            total_return = 0.0
            if equity_rows:
                start_balance = equity_rows[0]["account_balance"]
                if start_balance and start_balance > 0:
                    total_return = (net_pnl / start_balance) * 100

            metrics = PerformanceMetrics(
                total_return=total_return,
                win_rate=round(win_rate, 2),
                profit_factor=round(profit_factor, 2),
                sharpe_ratio=round(sharpe_ratio, 2),
                max_drawdown=round(max_dd, 2),
            )
            logger.info(
                "Performance metrics: win_rate=%.1f%% profit_factor=%.2f",
                metrics.win_rate,
                metrics.profit_factor,
            )
            return metrics
        finally:
            conn.close()

    def calculate_consistency_score(self) -> float:
        """Calculate the consistency score as best_day / total_profit.

        The consistency score measures how evenly profits are distributed
        across trading days. A score of 100 means no single day contributed
        more than its fair share. Lower scores indicate over-reliance on
        a few big winning days.

        Returns:
            Consistency score between 0 and 100.
        """
        conn = self._connect()
        try:
            cursor = conn.cursor()

            # Get daily PnL aggregated by date
            cursor.execute(
                """
                SELECT
                    DATE(close_time) as trade_date,
                    SUM(profit) as daily_pnl
                FROM trades
                WHERE close_time IS NOT NULL
                GROUP BY DATE(close_time)
                ORDER BY daily_pnl DESC
                """
            )
            rows = cursor.fetchall()
            if not rows:
                return 0.0

            daily_pnls = [row["daily_pnl"] for row in rows if row["daily_pnl"] is not None]
            if not daily_pnls:
                return 0.0

            # Consistency score = best_day / total_profit * 100
            # Lower best_day share = higher consistency
            total_profit = sum(p for p in daily_pnls if p > 0)
            if total_profit <= 0:
                return 0.0

            best_day = max(daily_pnls)
            score = (best_day / total_profit) * 100
            score = max(0.0, min(100.0, score))

            logger.info("Consistency score: %.2f (best_day=%.2f, total_profit=%.2f)",
                       score, best_day, total_profit)
            return round(score, 2)
        finally:
            conn.close()

    def log_risk_event(self, event: RiskEvent) -> int:
        """Insert a risk event into the database.

        Args:
            event: The RiskEvent dataclass to persist.

        Returns:
            The auto-generated row ID of the inserted event.
        """
        conn = self._connect()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO risk_events (
                    timestamp, event_type, description, daily_pnl,
                    drawdown_pct, zone
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    event.timestamp.isoformat() if event.timestamp else datetime.utcnow().isoformat(),
                    event.event_type,
                    event.description,
                    event.daily_pnl,
                    event.drawdown_pct,
                    event.zone,
                ),
            )
            conn.commit()
            event_id = cursor.lastrowid
            logger.warning(
                "Risk event logged: type=%s zone=%s dd=%.2f%%",
                event.event_type,
                event.zone,
                event.drawdown_pct,
            )
            return event_id if event_id is not None else 0
        finally:
            conn.close()

    def get_daily_summary(self, target_date: date) -> DailySummary:
        """Retrieve or compute the daily summary for a given date.

        First checks the daily_summaries table; if not found,
        computes from trade data and caches the result.

        Args:
            target_date: The calendar date to summarize.

        Returns:
            DailySummary for the specified date.
        """
        conn = self._connect()
        try:
            cursor = conn.cursor()

            # Check cached summary first
            date_str = target_date.isoformat()
            cursor.execute(
                "SELECT * FROM daily_summaries WHERE date = ?",
                (date_str,),
            )
            row = cursor.fetchone()
            if row:
                row_dict = dict(row)
                return DailySummary(
                    date=datetime.strptime(row_dict["date"], "%Y-%m-%d"),
                    total_trades=row_dict.get("total_trades", 0),
                    wins=row_dict.get("wins", 0),
                    losses=row_dict.get("losses", 0),
                    gross_profit=row_dict.get("gross_profit", 0.0),
                    gross_loss=row_dict.get("gross_loss", 0.0),
                    net_pnl=row_dict.get("net_pnl", 0.0),
                    max_dd=row_dict.get("max_dd", 0.0),
                    consistency_score=row_dict.get("consistency_score", 0.0),
                )

            # Compute from trades
            start_dt = datetime.combine(target_date, datetime.min.time())
            end_dt = start_dt + timedelta(days=1)

            cursor.execute(
                """
                SELECT
                    COUNT(*) as total_trades,
                    SUM(CASE WHEN profit > 0 THEN 1 ELSE 0 END) as wins,
                    SUM(CASE WHEN profit < 0 THEN 1 ELSE 0 END) as losses,
                    SUM(CASE WHEN profit > 0 THEN profit ELSE 0 END) as gross_profit,
                    SUM(CASE WHEN profit < 0 THEN ABS(profit) ELSE 0 END) as gross_loss,
                    SUM(profit) as net_pnl
                FROM trades
                WHERE close_time >= ? AND close_time < ?
                """,
                (start_dt.isoformat(), end_dt.isoformat()),
            )
            row = cursor.fetchone()
            if row is None or row["total_trades"] == 0:
                return DailySummary(date=start_dt)

            row_dict = dict(row)
            summary = DailySummary(
                date=start_dt,
                total_trades=row_dict.get("total_trades", 0),
                wins=row_dict.get("wins", 0),
                losses=row_dict.get("losses", 0),
                gross_profit=row_dict.get("gross_profit", 0.0),
                gross_loss=row_dict.get("gross_loss", 0.0),
                net_pnl=row_dict.get("net_pnl", 0.0),
            )

            # Cache the summary
            cursor.execute(
                """
                INSERT OR REPLACE INTO daily_summaries (
                    date, total_trades, wins, losses,
                    gross_profit, gross_loss, net_pnl
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    date_str,
                    summary.total_trades,
                    summary.wins,
                    summary.losses,
                    summary.gross_profit,
                    summary.gross_loss,
                    summary.net_pnl,
                ),
            )
            conn.commit()
            logger.info(
                "Daily summary for %s: %d trades, net_pnl=%.2f",
                date_str,
                summary.total_trades,
                summary.net_pnl,
            )
            return summary
        finally:
            conn.close()

    @staticmethod
    def _parse_dt(value: Optional[str]) -> Optional[datetime]:
        """Parse an ISO-formatted datetime string.

        Args:
            value: ISO datetime string or None.

        Returns:
            Parsed datetime or None.
        """
        if not value:
            return None
        try:
            return datetime.fromisoformat(value)
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _calculate_max_drawdown(rows: List[sqlite3.Row]) -> float:
        """Calculate maximum drawdown from a sequence of trade results.

        Args:
            rows: Database rows with "profit" and "account_balance" columns.

        Returns:
            Maximum drawdown as a percentage.
        """
        if not rows:
            return 0.0

        peak = 0.0
        max_dd = 0.0
        cumulative = 0.0

        for row in rows:
            profit = row["profit"] or 0.0
            cumulative += profit
            if cumulative > peak:
                peak = cumulative
            dd = peak - cumulative if peak > 0 else 0.0
            if peak > 0:
                dd_pct = (dd / peak) * 100
                if dd_pct > max_dd:
                    max_dd = dd_pct

        return max_dd

    @staticmethod
    def _compute_std(values: List[float]) -> float:
        """Compute the sample standard deviation of a list of numbers.

        Args:
            values: List of numeric values.

        Returns:
            Sample standard deviation (using N-1 denominator).
        """
        import math

        n = len(values)
        if n < 2:
            return 0.0

        mean = sum(values) / n
        variance = sum((x - mean) ** 2 for x in values) / (n - 1)
        return math.sqrt(variance)


__all__ = ["TradeLogger"]
