"""
Time utility functions for the prop firm trading bot.

Provides helpers for working with UTC and CET timezones,
trading session detection, and market hours.
"""

import logging
from datetime import datetime, time, timedelta, timezone, tzinfo
from typing import Optional

logger = logging.getLogger(__name__)


class _CET(tzinfo):
    """Central European Time (CET, UTC+1) timezone implementation.

    Implements a fixed-offset timezone for CET without daylight saving
    time transitions. For DST-aware CET/CEST, use zoneinfo or pytz.
    """

    _offset = timedelta(hours=1)
    _dst = timedelta(0)
    _name = "CET"

    def utcoffset(self, dt: Optional[datetime]) -> timedelta:
        """Return the UTC offset for CET (+1 hour).

        Args:
            dt: The datetime to compute offset for (unused, fixed offset).

        Returns:
            Timedelta of +1 hour.
        """
        return self._offset

    def dst(self, dt: Optional[datetime]) -> timedelta:
        """Return DST offset (none for this fixed-offset implementation).

        Args:
            dt: The datetime to compute DST for (unused).

        Returns:
            Zero timedelta.
        """
        return self._dst

    def tzname(self, dt: Optional[datetime]) -> str:
        """Return the timezone name.

        Args:
            dt: The datetime to get name for (unused).

        Returns:
            The string 'CET'.
        """
        return self._name

    def __repr__(self) -> str:
        return "CET()"


# Module-level singleton for CET timezone
_CET_TZ = _CET()


# Trading session hours in CET
_SESSION_HOURS = {
    "Asia": (time(0, 0), time(8, 0)),
    "London": (time(8, 0), time(17, 0)),
    "New_York": (time(14, 0), time(23, 0)),
}


def get_utc_now() -> datetime:
    """Get the current datetime in UTC timezone.

    Returns:
        Aware datetime object with UTC timezone.
    """
    return datetime.now(timezone.utc)


def get_cet_now() -> datetime:
    """Get the current datetime in CET timezone.

    Returns:
        Aware datetime object with CET timezone (UTC+1).
    """
    utc = get_utc_now()
    return utc.astimezone(_CET_TZ)


def is_session_time(session_name: str) -> bool:
    """Check if the current CET time falls within a trading session.

    Trading sessions (CET):
        - Asia: 00:00 - 08:00
        - London: 08:00 - 17:00
        - New_York: 14:00 - 23:00

    Args:
        session_name: Name of the session ("Asia", "London", or "New_York").

    Returns:
        True if the current time is within the specified session hours.

    Raises:
        ValueError: If session_name is not a recognized session.
    """
    if session_name not in _SESSION_HOURS:
        raise ValueError(
            f"Unknown session '{session_name}'. "
            f"Valid sessions: {list(_SESSION_HOURS.keys())}"
        )

    cet_now = get_cet_now()
    current_time = cet_now.time()
    start, end = _SESSION_HOURS[session_name]

    result = start <= current_time < end
    logger.debug(
        "Session check: %s, time=%s, range=%s-%s, active=%s",
        session_name,
        current_time.strftime("%H:%M"),
        start.strftime("%H:%M"),
        end.strftime("%H:%M"),
        result,
    )
    return result


def get_current_session() -> Optional[str]:
    """Determine which trading session is currently active.

    Sessions are checked in priority order: London, New_York, Asia.
    Overlapping sessions (e.g., London + New_York 14:00-17:00)
    return the primary session.

    Returns:
        Name of the active session, or None if no session is active.
    """
    cet_now = get_cet_now()
    current_time = cet_now.time()

    for session_name in ("London", "New_York", "Asia"):
        start, end = _SESSION_HOURS[session_name]
        if start <= current_time < end:
            logger.debug("Current session: %s", session_name)
            return session_name

    logger.debug("No active trading session at %s", current_time.strftime("%H:%M"))
    return None


def format_iso(dt: datetime) -> str:
    """Format a datetime as ISO 8601 string with timezone.

    Args:
        dt: The datetime to format.

    Returns:
        ISO 8601 formatted string.
    """
    return dt.isoformat()


def parse_iso(iso_string: str) -> datetime:
    """Parse an ISO 8601 datetime string.

    Args:
        iso_string: ISO 8601 formatted datetime string.

    Returns:
        Parsed datetime object.
    """
    return datetime.fromisoformat(iso_string)


def trading_day_start(dt: Optional[datetime] = None) -> datetime:
    """Get the start of the trading day in CET.

    The trading day starts at 00:00 CET.

    Args:
        dt: Reference datetime (defaults to current CET time).

    Returns:
        Datetime at 00:00 CET of the same calendar day.
    """
    if dt is None:
        dt = get_cet_now()
    return dt.replace(hour=0, minute=0, second=0, microsecond=0)


def trading_week_start(dt: Optional[datetime] = None) -> datetime:
    """Get the start of the trading week in CET.

    The forex trading week starts on Monday 00:00 CET.

    Args:
        dt: Reference datetime (defaults to current CET time).

    Returns:
        Datetime at 00:00 CET on Monday of the current week.
    """
    if dt is None:
        dt = get_cet_now()
    monday = dt - timedelta(days=dt.weekday())
    return monday.replace(hour=0, minute=0, second=0, microsecond=0)


__all__ = [
    "get_utc_now",
    "get_cet_now",
    "is_session_time",
    "get_current_session",
    "format_iso",
    "parse_iso",
    "trading_day_start",
    "trading_week_start",
]
