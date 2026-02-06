# openpaw/api/services/encryption.py

import json
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet


class EncryptionService:
    """Handles encryption of sensitive data at rest."""

    DEFAULT_KEY_FILE = ".openpaw_key"

    def __init__(self, key_path: Path | None = None):
        self.key_path = key_path or Path.home() / self.DEFAULT_KEY_FILE
        self._fernet = self._load_or_create_key()

    def _load_or_create_key(self) -> Fernet:
        """Load existing key or generate new one."""
        if self.key_path.exists():
            key = self.key_path.read_bytes()
        else:
            key = Fernet.generate_key()
            self.key_path.write_bytes(key)
            self.key_path.chmod(0o600)

        return Fernet(key)

    def encrypt(self, plaintext: str) -> str:
        """Encrypt a string value."""
        return self._fernet.encrypt(plaintext.encode()).decode()

    def decrypt(self, ciphertext: str) -> str:
        """Decrypt a string value."""
        return self._fernet.decrypt(ciphertext.encode()).decode()

    def encrypt_json(self, data: dict[str, Any]) -> str:
        """Encrypt a dictionary as JSON."""
        return self.encrypt(json.dumps(data))

    def decrypt_json(self, ciphertext: str) -> dict[str, Any]:
        """Decrypt JSON data to dictionary."""
        decrypted = self.decrypt(ciphertext)
        result: dict[str, Any] = json.loads(decrypted)
        return result
