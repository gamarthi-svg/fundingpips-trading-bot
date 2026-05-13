"""
Notification manager for the prop firm trading bot.

Provides Telegram notifications and configurable alerts with
rate limiting to prevent notification spam.
"""

import logging
import os
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Optional

import httpx

logger = logging.getLogger(__name__)


class Severity(str, Enum):
    """Alert severity levels."""
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass
class AlertConfig:
    """Configuration for an alert type.

    Attributes:
        severity: The severity level of this alert type.
        cooldown_seconds: Minimum seconds between alerts of this type.
        enabled: Whether this alert type is active.
    """
    severity: Severity = Severity.INFO
    cooldown_seconds: int = 60
    enabled: bool = True


class NotificationManager:
    """Manages notifications via Telegram with rate limiting.

    Sends alerts through the Telegram Bot API with per-severity
    rate limiting to prevent spam. Configuration is read from
    environment variables TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID.

    Args:
        bot_token: Telegram bot token (overrides env var).
        chat_id: Telegram chat ID (overrides env var).
        default_cooldown: Default cooldown in seconds between alerts.
    """

    # Telegram API base URL
    _TELEGRAM_API_URL: str = "https://api.telegram.org/bot{token}/sendMessage"

    def __init__(
        self,
        bot_token: Optional[str] = None,
        chat_id: Optional[str] = None,
        default_cooldown: int = 60,
    ) -> None:
        """Initialize the notification manager.

        Args:
            bot_token: Telegram bot token. Falls back to TELEGRAM_BOT_TOKEN env var.
            chat_id: Telegram chat ID. Falls back to TELEGRAM_CHAT_ID env var.
            default_cooldown: Default rate limit cooldown in seconds.
        """
        self._bot_token: Optional[str] = bot_token or os.environ.get("TELEGRAM_BOT_TOKEN")
        self._chat_id: Optional[str] = chat_id or os.environ.get("TELEGRAM_CHAT_ID")
        self._default_cooldown: int = default_cooldown

        # Rate limiting: last send timestamp per severity
        self._last_alert_time: Dict[Severity, float] = {
            Severity.INFO: 0.0,
            Severity.WARNING: 0.0,
            Severity.CRITICAL: 0.0,
        }

        # Per-severity cooldown overrides
        self._cooldowns: Dict[Severity, int] = {
            Severity.INFO: default_cooldown,
            Severity.WARNING: default_cooldown,
            Severity.CRITICAL: 0,  # Critical alerts are not rate-limited
        }

        # Alert type configurations
        self._alert_configs: Dict[str, AlertConfig] = {}

        if self._bot_token and self._chat_id:
            logger.info(
                "NotificationManager initialized with chat_id=%s",
                self._chat_id,
            )
        else:
            logger.warning(
                "Telegram not configured: bot_token=%s chat_id=%s",
                "set" if self._bot_token else "missing",
                "set" if self._chat_id else "missing",
            )

    def configure_alert(self, event_type: str, config: AlertConfig) -> None:
        """Configure rate limiting and severity for an alert type.

        Args:
            event_type: The event type identifier.
            config: AlertConfig with severity and cooldown settings.
        """
        self._alert_configs[event_type] = config
        logger.debug(
            "Configured alert '%s': severity=%s cooldown=%ds",
            event_type,
            config.severity.value,
            config.cooldown_seconds,
        )

    def send_telegram(self, message: str) -> bool:
        """Send a raw message to the configured Telegram chat.

        Args:
            message: The text message to send (supports Markdown).

        Returns:
            True if the message was sent successfully, False otherwise.
        """
        if not self._bot_token or not self._chat_id:
            logger.warning("Telegram not configured, message not sent: %s", message)
            return False

        url = self._TELEGRAM_API_URL.format(token=self._bot_token)
        payload = {
            "chat_id": self._chat_id,
            "text": message,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True,
        }

        try:
            with httpx.Client(timeout=30.0) as client:
                response = client.post(url, json=payload)
                response.raise_for_status()
                logger.debug("Telegram message sent successfully")
                return True
        except httpx.HTTPStatusError as exc:
            logger.error(
                "Telegram HTTP error %d: %s",
                exc.response.status_code,
                exc.response.text,
            )
            return False
        except httpx.RequestError as exc:
            logger.error("Telegram request failed: %s", exc)
            return False
        except Exception:
            logger.exception("Unexpected error sending Telegram message")
            return False

    def send_alert(
        self,
        event_type: str,
        details: str,
        severity: Optional[Severity] = None,
    ) -> bool:
        """Send an alert with rate limiting and severity formatting.

        Checks the cooldown period for the alert's severity before
        sending. Critical alerts bypass rate limiting.

        Args:
            event_type: The type of event (e.g., 'daily_loss_limit').
            details: Human-readable description of the event.
            severity: Override severity level. Uses config default if None.

        Returns:
            True if the alert was sent (or queued), False if rate-limited.
        """
        # Resolve severity
        if severity is None:
            config = self._alert_configs.get(event_type)
            if config:
                severity = config.severity
            else:
                severity = Severity.INFO

        # Check if this alert type is enabled
        config = self._alert_configs.get(event_type)
        if config and not config.enabled:
            logger.debug("Alert '%s' is disabled, skipping", event_type)
            return False

        # Check rate limit
        if not self._check_rate_limit(severity):
            logger.debug(
                "Alert '%s' rate-limited (severity=%s)",
                event_type,
                severity.value,
            )
            return False

        # Format the message
        severity_emoji = {
            Severity.INFO: "ℹ️",
            Severity.WARNING: "⚠️",
            Severity.CRITICAL: "🚨",
        }.get(severity, "📢")

        timestamp = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())
        message = (
            f"{severity_emoji} *{severity.value.upper()}* - {event_type}\n"
            f"🕐 {timestamp}\n"
            f"{details}"
        )

        success = self.send_telegram(message)
        if success:
            self._last_alert_time[severity] = time.time()
            logger.info(
                "Alert sent: type=%s severity=%s",
                event_type,
                severity.value,
            )
        return success

    def _check_rate_limit(self, severity: Severity) -> bool:
        """Check if enough time has passed since the last alert of this severity.

        Args:
            severity: The severity level to check.

        Returns:
            True if the alert can be sent (cooldown expired).
        """
        # Critical alerts bypass rate limiting
        if severity == Severity.CRITICAL:
            return True

        cooldown = self._cooldowns.get(severity, self._default_cooldown)
        last_time = self._last_alert_time.get(severity, 0.0)
        elapsed = time.time() - last_time

        return elapsed >= cooldown

    def set_cooldown(self, severity: Severity, seconds: int) -> None:
        """Set the cooldown period for a severity level.

        Args:
            severity: The severity level to configure.
            seconds: Cooldown period in seconds.
        """
        self._cooldowns[severity] = seconds
        logger.info(
            "Cooldown for %s set to %d seconds",
            severity.value,
            seconds,
        )

    def is_configured(self) -> bool:
        """Check if Telegram is properly configured.

        Returns:
            True if both bot_token and chat_id are set.
        """
        return bool(self._bot_token and self._chat_id)


__all__ = ["NotificationManager", "Severity", "AlertConfig"]
