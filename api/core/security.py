"""Security utilities for credential handling."""

from typing import Tuple
from cryptography.fernet import Fernet


class CredentialHandler:
    """
    Handles credential encryption for in-memory storage.

    Security measures:
    1. Credentials encrypted with Fernet (AES-128-CBC + HMAC)
    2. Unique key per server instance (regenerated on restart)
    3. Credentials exist only in RAM, never written to disk
    4. Session TTL enforces automatic cleanup
    5. Explicit zeroing of memory on session destruction
    """

    def __init__(self):
        # Generate new key on each server start
        self._key = Fernet.generate_key()
        self._fernet = Fernet(self._key)

    def encrypt(self, user_id: str, password: str) -> bytes:
        """Encrypt credentials for storage."""
        # Combine with null separator (won't appear in credentials)
        combined = f"{user_id}\x00{password}".encode("utf-8")
        return self._fernet.encrypt(combined)

    def decrypt(self, encrypted: bytes) -> Tuple[str, str]:
        """Decrypt credentials for use."""
        decrypted = self._fernet.decrypt(encrypted).decode("utf-8")
        user_id, password = decrypted.split("\x00", 1)
        return user_id, password

    @staticmethod
    def secure_delete(data: bytearray) -> None:
        """Overwrite memory with zeros before deletion."""
        for i in range(len(data)):
            data[i] = 0
