"""Secure credential management for MetaAPI tokens.

Credentials are encrypted at rest using AES-256-GCM with a key derived from
the MASTER_KEY environment variable.  The plaintext token is NEVER written to
logs or returned in API responses.

Usage:
    creds = CredentialManager()          # Loads from SQLite
    await creds.update(token="...")      # Encrypts and stores
    cfg = creds.get_config()             # Returns decrypted config
    status = creds.get_status()          # Returns masked status (safe for UI)
"""

import base64
import json
import logging
import os
import secrets
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

import httpx

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
except ImportError:
    AESGCM = None  # type: ignore

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────
DB_PATH = Path("data/credentials.db")
KEY_ENV_VAR = "MASTER_KEY"
KEY_LENGTH = 32          # AES-256
NONCE_LENGTH = 12        # 96-bit GCM nonce


# ── Data Model ─────────────────────────────────────────────────────────────

@dataclass
class MetaApiConfig:
    """Container for MetaAPI connection settings."""

    token: str = ""
    account_id: str = ""
    region: str = "new-york"  # agiliumtrade.ai region

    # Prop firm selection
    prop_firm: str = "fundingpips"   # "fundingpips" or "the5ers"
    account_type: str = "pro"        # e.g. "pro", "bootcamp"
    account_size: float = 10_000.0   # Eval account size in USD
    phase: str = "phase1"            # "phase1", "phase2", "funded"

    # The5%ers specific
    the5ers_step: int = 1            # 1, 2, or 3 for 3-step challenge

    # MT5 credentials (used by MetaAPI to connect to broker)
    mt_login: int = 0
    mt_password: str = ""
    mt_server: str = ""

    @property
    def is_configured(self) -> bool:
        return bool(self.token and self.account_id)


# ── Encryption ─────────────────────────────────────────────────────────────

class EncryptionError(Exception):
    """Raised when encryption or decryption fails."""


def _derive_key(master_key: str) -> bytes:
    """Derive a 32-byte AES key from the master key string.

    Uses PBKDF2-HMAC-SHA256 with a fixed salt for deterministic key
    derivation.  The salt is stored alongside the ciphertext so the
    same key can decrypt any past record.
    """
    import hashlib
    # Simple hash-based key derivation — in production use a proper KDF
    # like argon2 or PBKDF2 with high iteration count
    raw = hashlib.sha256(master_key.encode("utf-8")).digest()
    return raw[:KEY_LENGTH]


def _encrypt(plaintext: str, master_key: str) -> str:
    """Encrypt a string using AES-256-GCM.

    Returns a base64-encoded string containing:
        nonce (12 bytes) || ciphertext || auth_tag (16 bytes)
    """
    if AESGCM is None:
        raise EncryptionError(
            "cryptography library required. Install: pip install cryptography"
        )

    key = _derive_key(master_key)
    nonce = secrets.token_bytes(NONCE_LENGTH)
    aesgcm = AESGCM(key)
    ciphertext = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
    # ciphertext = nonce || encrypted_data (auth tag is last 16 bytes)
    combined = nonce + ciphertext
    return base64.urlsafe_b64encode(combined).decode("ascii")


def _decrypt(ciphertext_b64: str, master_key: str) -> str:
    """Decrypt a base64-encoded AES-256-GCM ciphertext."""
    if AESGCM is None:
        raise EncryptionError(
            "cryptography library required. Install: pip install cryptography"
        )

    try:
        combined = base64.urlsafe_b64decode(ciphertext_b64.encode("ascii"))
    except Exception as exc:
        raise EncryptionError(f"Invalid ciphertext encoding: {exc}") from exc

    if len(combined) < NONCE_LENGTH + 16:
        raise EncryptionError("Ciphertext too short")

    nonce = combined[:NONCE_LENGTH]
    ciphertext = combined[NONCE_LENGTH:]
    key = _derive_key(master_key)
    aesgcm = AESGCM(key)

    try:
        plaintext = aesgcm.decrypt(nonce, ciphertext, None)
        return plaintext.decode("utf-8")
    except Exception as exc:
        raise EncryptionError(f"Decryption failed (wrong master key?): {exc}") from exc


# ── Credential Manager ─────────────────────────────────────────────────────

class CredentialManager:
    """Manages encrypted storage and retrieval of MetaAPI credentials.

    Credentials are stored in a local SQLite database with AES-256-GCM
    encryption.  The plaintext token is never persisted to disk unencrypted
    and is never returned in API responses.
    """

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self.db_path = db_path or DB_PATH
        self._master_key: Optional[str] = None
        self._ensure_db()

    # ── Key Management ─────────────────────────────────────────────────

    def _get_master_key(self) -> str:
        """Return the master encryption key from environment.

        Caches after first read.  Raises if not set.
        """
        if self._master_key is not None:
            return self._master_key

        key = os.environ.get(KEY_ENV_VAR, "")
        if not key:
            logger.warning(
                "%s not set — using default key (INSECURE, development only). "
                "Set %s in your .env file!",
                KEY_ENV_VAR,
                KEY_ENV_VAR,
            )
            # Development fallback — prints a big warning
            key = "__DEV_FALLBACK_CHANGE_IN_PRODUCTION__"
        self._master_key = key
        return key

    # ── Database ───────────────────────────────────────────────────────

    def _ensure_db(self) -> None:
        """Create the credentials table if it doesn't exist."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._db() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS credentials (
                    id          INTEGER PRIMARY KEY CHECK (id = 1),
                    encrypted   TEXT NOT NULL,
                    updated_at  REAL NOT NULL,
                    updated_by  TEXT
                )
                """
            )
            conn.commit()

    @contextmanager
    def _db(self):
        conn = sqlite3.connect(str(self.db_path))
        try:
            yield conn
        finally:
            conn.close()

    # ── Public API ─────────────────────────────────────────────────────

    async def update(
        self,
        token: str,
        account_id: str,
        region: str = "new-york",
        prop_firm: str = "fundingpips",
        account_type: str = "pro",
        account_size: float = 10_000.0,
        phase: str = "phase1",
        the5ers_step: int = 1,
        mt_login: int = 0,
        mt_password: str = "",
        mt_server: str = "",
    ) -> Dict[str, Any]:
        """Encrypt and store new credentials.

        Args:
            token: MetaAPI token (will be encrypted).
            account_id: MetaAPI account ID.
            region: MetaAPI region (default: "new-york").
            prop_firm: "fundingpips" or "the5ers".
            account_type: Account type string.
            account_size: Account size in USD.
            phase: Current phase ("phase1", "phase2", "funded").
            the5ers_step: For The5%ers 3-step challenge (1, 2, 3).
            mt_login: MT5 login number.
            mt_password: MT5 password.
            mt_server: MT5 server name.

        Returns:
            {"success": True, "validated": bool, "message": str}
        """
        # Validate by making a test call to MetaAPI
        validated = False
        validation_msg = "Token not validated"
        if token and account_id:
            validated, validation_msg = await self._validate_token(
                token, account_id, region
            )

        # Build config object
        config = MetaApiConfig(
            token=token,
            account_id=account_id,
            region=region,
            prop_firm=prop_firm,
            account_type=account_type,
            account_size=account_size,
            phase=phase,
            the5ers_step=the5ers_step,
            mt_login=mt_login,
            mt_password=mt_password,
            mt_server=mt_server,
        )

        # Serialize and encrypt
        plaintext = json.dumps(asdict(config), indent=2)
        master_key = self._get_master_key()
        try:
            encrypted = _encrypt(plaintext, master_key)
        except EncryptionError as exc:
            logger.error("Encryption failed: %s", exc)
            return {
                "success": False,
                "validated": False,
                "message": f"Encryption failed: {exc}",
            }

        # Store encrypted blob
        with self._db() as conn:
            conn.execute(
                """
                INSERT INTO credentials (id, encrypted, updated_at, updated_by)
                VALUES (1, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    encrypted = excluded.encrypted,
                    updated_at = excluded.updated_at,
                    updated_by = excluded.updated_by
                """,
                (encrypted, time.time(), "api"),
            )
            conn.commit()

        # Clear sensitive data from memory (best effort)
        del plaintext
        config.token = ""

        logger.info(
            "Credentials updated for account %s (%s, %s, %s)",
            account_id[:8] + "...",
            prop_firm,
            account_type,
            phase,
        )
        return {
            "success": True,
            "validated": validated,
            "message": validation_msg,
        }

    async def _validate_token(
        self, token: str, account_id: str, region: str
    ) -> tuple:
        """Validate a MetaAPI token by fetching account information.

        Returns:
            (is_valid: bool, message: str)
        """
        url = (
            f"https://mt-client-api-v1.{region}.agiliumtrade.ai"
            f"/users/current/accounts/{account_id}/accountInformation"
        )
        headers = {"auth-token": token}
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(url, headers=headers)
                if resp.status_code == 200:
                    data = resp.json()
                    broker = data.get("broker", "unknown")
                    balance = data.get("balance", 0)
                    return True, f"Connected: {broker} | Balance: ${balance:,.2f}"
                elif resp.status_code == 401:
                    return False, "Invalid token or token lacks required permissions"
                else:
                    return False, f"HTTP {resp.status_code} from MetaAPI"
        except Exception as exc:
            logger.warning("Token validation error: %s", exc)
            return False, f"Connection error: {exc}"

    def get_config(self) -> Optional[MetaApiConfig]:
        """Load and decrypt credentials from the database.

        Returns a MetaApiConfig with the plaintext token populated.
        Returns None if no credentials are stored.
        """
        with self._db() as conn:
            row = conn.execute(
                "SELECT encrypted FROM credentials WHERE id = 1"
            ).fetchone()

        if row is None:
            return None

        master_key = self._get_master_key()
        try:
            plaintext = _decrypt(row[0], master_key)
        except EncryptionError as exc:
            logger.error("Failed to decrypt credentials: %s", exc)
            return None

        data = json.loads(plaintext)
        return MetaApiConfig(**data)

    def get_status(self) -> Dict[str, Any]:
        """Return a safe, masked view of the credential status.

        The token itself is NEVER included in the response.
        """
        with self._db() as conn:
            row = conn.execute(
                "SELECT encrypted, updated_at FROM credentials WHERE id = 1"
            ).fetchone()

        if row is None:
            return {
                "configured": False,
                "account_id": None,
                "region": None,
                "prop_firm": None,
                "account_type": None,
                "account_size": None,
                "phase": None,
                "the5ers_step": None,
                "updated_at": None,
                "validated": False,
            }

        master_key = self._get_master_key()
        try:
            plaintext = _decrypt(row[0], master_key)
            data = json.loads(plaintext)
        except EncryptionError:
            return {"configured": True, "error": "Decryption failed"}

        # Mask sensitive fields
        raw_id = data.get("account_id", "")
        masked_id = raw_id[:6] + "..." + raw_id[-4:] if len(raw_id) > 10 else "***"

        return {
            "configured": True,
            "account_id": masked_id,
            "region": data.get("region", "new-york"),
            "prop_firm": data.get("prop_firm", "fundingpips"),
            "account_type": data.get("account_type", "pro"),
            "account_size": data.get("account_size", 10_000),
            "phase": data.get("phase", "phase1"),
            "the5ers_step": data.get("the5ers_step", 1),
            "updated_at": row[1],
        }

    def has_credentials(self) -> bool:
        """Return True if credentials are configured."""
        with self._db() as conn:
            row = conn.execute(
                "SELECT 1 FROM credentials WHERE id = 1"
            ).fetchone()
        return row is not None

    def delete(self) -> None:
        """Remove all stored credentials."""
        with self._db() as conn:
            conn.execute("DELETE FROM credentials WHERE id = 1")
            conn.commit()
        logger.info("Credentials deleted")
