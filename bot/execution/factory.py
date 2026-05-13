"""
TradingProviderFactory — provider creation and discovery.

This module centralises the creation of trading-provider instances.  The
factory inspects the configuration dict (and optional environment overrides) to
instantiate the correct backend: MT5 local or MetaAPI cloud.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

from execution.provider import TradingProvider

logger = logging.getLogger(__name__)


class TradingProviderFactory:
    """Factory for creating TradingProvider instances based on configuration.

    Usage::

        provider = TradingProviderFactory.create_provider(config)
    """

    @staticmethod
    def create_provider(cfg: Dict[str, Any]) -> TradingProvider:
        """Instantiate a TradingProvider based on *cfg*.

        The ``provider`` key in *cfg* selects the backend:

        - ``"mt5"``      → Local MT5 terminal (default).
        - ``"metaapi"``  → MetaAPI.cloud REST/WebSocket gateway.

        Environment variables override config values:

        - ``MT5_ACCOUNT`` / ``MT5_PASSWORD`` / ``MT5_SERVER``
        - ``METAAPI_TOKEN`` / ``METAAPI_ACCOUNT_ID``

        Args:
            cfg: Parsed configuration dictionary.

        Returns:
            An initialised (but not yet connected) ``TradingProvider``.

        Raises:
            ValueError: If the requested provider type is unknown.
            ImportError: If required dependencies for the provider are missing.
        """
        provider_type = os.environ.get("PROVIDER_TYPE", cfg.get("provider", "mt5")).lower()
        logger.info("Creating trading provider: type=%s", provider_type)

        if provider_type == "mt5":
            from execution.mt5_provider import MT5Provider

            account = int(os.environ.get("MT5_ACCOUNT", cfg.get("account", 0)))
            password = os.environ.get("MT5_PASSWORD", cfg.get("password", ""))
            server = os.environ.get("MT5_SERVER", cfg.get("server", ""))
            return MT5Provider(login=account, password=password, server=server)

        if provider_type == "metaapi":
            from execution.metaapi_provider import MetaAPIProvider

            token = os.environ.get("METAAPI_TOKEN", cfg.get("metaapi_token", ""))
            account_id = os.environ.get(
                "METAAPI_ACCOUNT_ID", cfg.get("metaapi_account_id", "")
            )
            return MetaAPIProvider(token=token, account_id=account_id)

        raise ValueError(
            f"Unknown trading provider '{provider_type}'. "
            f"Supported: mt5, metaapi."
        )
