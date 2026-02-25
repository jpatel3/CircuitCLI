"""Master password encryption — PBKDF2-SHA512 key derivation for SQLCipher."""

from __future__ import annotations

import hashlib
import secrets
from pathlib import Path

from circuitai.core.config import get_data_dir, load_config
from circuitai.core.exceptions import EncryptionError


class MasterKeyManager:
    """Derives and manages the SQLCipher encryption key from a master password."""

    SALT_FILE = "salt.bin"
    VERIFY_FILE = "verify.bin"
    SALT_SIZE = 32
    KEY_SIZE = 32  # 256-bit

    def __init__(self, data_dir: Path | None = None) -> None:
        config = load_config()
        self.data_dir = data_dir or get_data_dir(config)
        self.iterations = config.get("security", {}).get("pbkdf2_iterations", 256_000)
        self._cached_key: str | None = None

    @property
    def is_initialized(self) -> bool:
        """Whether a master password has been set up."""
        return (self.data_dir / self.SALT_FILE).exists()

    def initialize(self, password: str) -> str:
        """Set up a new master password. Returns the derived hex key."""
        if self.is_initialized:
            raise EncryptionError("Master password already initialized. Use change_password().")

        salt = secrets.token_bytes(self.SALT_SIZE)
        (self.data_dir / self.SALT_FILE).write_bytes(salt)

        key_hex = self._derive_key(password, salt)

        # Store a verification hash (different salt) so we can check passwords later
        verify_salt = secrets.token_bytes(self.SALT_SIZE)
        verify_hash = self._derive_key(password, verify_salt)
        (self.data_dir / self.VERIFY_FILE).write_bytes(verify_salt + verify_hash.encode("ascii"))

        self._cached_key = key_hex
        return key_hex

    def unlock(self, password: str) -> str:
        """Verify password and return the derived hex key."""
        if not self.is_initialized:
            raise EncryptionError("Master password not initialized. Run 'circuit setup' first.")

        # Verify password
        verify_data = (self.data_dir / self.VERIFY_FILE).read_bytes()
        verify_salt = verify_data[: self.SALT_SIZE]
        stored_hash = verify_data[self.SALT_SIZE :].decode("ascii")
        check_hash = self._derive_key(password, verify_salt)
        if not secrets.compare_digest(check_hash, stored_hash):
            raise EncryptionError("Incorrect master password.")

        # Derive actual DB key
        salt = (self.data_dir / self.SALT_FILE).read_bytes()
        key_hex = self._derive_key(password, salt)
        self._cached_key = key_hex
        return key_hex

    def get_cached_key(self) -> str | None:
        """Return the cached key if available."""
        return self._cached_key

    def clear_cache(self) -> None:
        """Clear the cached key from memory."""
        self._cached_key = None

    def _derive_key(self, password: str, salt: bytes) -> str:
        """Derive a hex key from password + salt using PBKDF2-SHA512."""
        dk = hashlib.pbkdf2_hmac(
            "sha512",
            password.encode("utf-8"),
            salt,
            self.iterations,
            dklen=self.KEY_SIZE,
        )
        return dk.hex()

    def reset(self) -> None:
        """Remove all encryption state. DESTRUCTIVE — used for testing or re-setup."""
        for fname in (self.SALT_FILE, self.VERIFY_FILE):
            path = self.data_dir / fname
            if path.exists():
                path.unlink()
        self._cached_key = None
