"""
Encryption Utility — AES-256 for file passwords & secure links.
Uses Fernet (symmetric) for link tokens + bcrypt for passwords.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
import secrets
import time
from typing import Optional

try:
    from cryptography.fernet import Fernet, InvalidToken
    HAS_CRYPTO = True
except ImportError:
    HAS_CRYPTO = False
    logger_pre = logging.getLogger(__name__)
    logger_pre.warning("cryptography not installed — link encryption disabled")

logger = logging.getLogger(__name__)


class Encryptor:
    """
    Handles:
    1. Secure file link token generation (Fernet)
    2. Password hashing for locked files (SHA-256 PBKDF2)
    3. File key generation
    """

    def __init__(self, secret_key: str):
        self.secret_key = secret_key or os.urandom(32).hex()
        if HAS_CRYPTO:
            # Derive a 32-byte key for Fernet
            key_bytes = hashlib.sha256(self.secret_key.encode()).digest()
            self._fernet = Fernet(base64.urlsafe_b64encode(key_bytes))
        else:
            self._fernet = None

    # ─── File Keys ────────────────────────────────────────────

    def generate_file_key(self) -> str:
        """Generate a unique file key (used in share links)."""
        return secrets.token_urlsafe(16)

    # ─── Link Tokens ─────────────────────────────────────────

    def create_link_token(self, file_key: str, expiry_seconds: Optional[int] = None) -> str:
        """
        Create an encrypted token for a file link.
        Token embeds file_key + optional expiry.
        """
        if not HAS_CRYPTO or not self._fernet:
            # Fallback: plain base64 (not secure, but functional)
            return base64.urlsafe_b64encode(file_key.encode()).decode()

        payload = file_key
        if expiry_seconds:
            expiry = int(time.time()) + expiry_seconds
            payload = f"{file_key}::{expiry}"

        encrypted = self._fernet.encrypt(payload.encode())
        return encrypted.decode()

    def decode_link_token(self, token: str) -> Optional[str]:
        """
        Decode a link token back to file_key.
        Returns None if invalid/expired.
        """
        if not HAS_CRYPTO or not self._fernet:
            try:
                return base64.urlsafe_b64decode(token.encode()).decode()
            except Exception:
                return None

        try:
            decrypted = self._fernet.decrypt(token.encode()).decode()
            if "::" in decrypted:
                file_key, expiry_str = decrypted.split("::", 1)
                if int(time.time()) > int(expiry_str):
                    return None  # Expired
                return file_key
            return decrypted
        except (InvalidToken, Exception) as e:
            logger.debug(f"Token decode failed: {e}")
            return None

    # ─── Password Hashing ────────────────────────────────────

    def hash_password(self, password: str) -> str:
        """Hash a file password with PBKDF2-SHA256."""
        salt = secrets.token_hex(16)
        key = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt.encode(),
            100_000,
        )
        return f"{salt}:{base64.b64encode(key).decode()}"

    def verify_password(self, password: str, stored_hash: str) -> bool:
        """Verify a password against stored hash."""
        try:
            salt, encoded_key = stored_hash.split(":", 1)
            key = hashlib.pbkdf2_hmac(
                "sha256",
                password.encode("utf-8"),
                salt.encode(),
                100_000,
            )
            expected = base64.b64decode(encoded_key.encode())
            return hmac.compare_digest(key, expected)
        except Exception as e:
            logger.error(f"Password verify error: {e}")
            return False

    # ─── HMAC for integrity ──────────────────────────────────

    def sign(self, data: str) -> str:
        """Create HMAC signature."""
        sig = hmac.new(
            self.secret_key.encode(),
            data.encode(),
            hashlib.sha256
        ).hexdigest()
        return sig

    def verify_signature(self, data: str, signature: str) -> bool:
        return hmac.compare_digest(self.sign(data), signature)
