"""Tests for encryption service."""

import json
import tempfile
from pathlib import Path

import pytest

from openpaw.api.services.encryption import EncryptionService


class TestEncryptionService:
    """Test EncryptionService functionality."""

    def test_creates_key_file_when_not_exists(self):
        """Test that key file is created if it doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            key_path = Path(tmpdir) / "test_key"
            assert not key_path.exists()

            service = EncryptionService(key_path)

            assert key_path.exists()
            # Verify key file has restricted permissions (0o600)
            assert key_path.stat().st_mode & 0o777 == 0o600

    def test_loads_existing_key_file(self):
        """Test that existing key file is loaded."""
        with tempfile.TemporaryDirectory() as tmpdir:
            key_path = Path(tmpdir) / "test_key"

            # Create first service instance
            service1 = EncryptionService(key_path)
            original_key = key_path.read_bytes()

            # Create second service instance with same key path
            service2 = EncryptionService(key_path)
            loaded_key = key_path.read_bytes()

            # Key should be the same
            assert original_key == loaded_key

            # Both services should decrypt data encrypted by each other
            plaintext = "test message"
            encrypted_by_1 = service1.encrypt(plaintext)
            decrypted_by_2 = service2.decrypt(encrypted_by_1)
            assert decrypted_by_2 == plaintext

    def test_uses_default_key_path(self):
        """Test that default key path is used when not specified."""
        service = EncryptionService()
        expected_path = Path.home() / EncryptionService.DEFAULT_KEY_FILE
        assert service.key_path == expected_path

    def test_encrypt_decrypt_roundtrip(self):
        """Test encrypting and decrypting a string."""
        with tempfile.TemporaryDirectory() as tmpdir:
            key_path = Path(tmpdir) / "test_key"
            service = EncryptionService(key_path)

            plaintext = "sensitive data"
            ciphertext = service.encrypt(plaintext)

            # Ciphertext should be different from plaintext
            assert ciphertext != plaintext
            assert isinstance(ciphertext, str)

            # Decrypt should recover original plaintext
            decrypted = service.decrypt(ciphertext)
            assert decrypted == plaintext

    def test_encrypt_unicode_text(self):
        """Test encrypting and decrypting unicode text."""
        with tempfile.TemporaryDirectory() as tmpdir:
            key_path = Path(tmpdir) / "test_key"
            service = EncryptionService(key_path)

            plaintext = "Hello 世界 🌍"
            ciphertext = service.encrypt(plaintext)
            decrypted = service.decrypt(ciphertext)

            assert decrypted == plaintext

    def test_encrypt_empty_string(self):
        """Test encrypting and decrypting empty string."""
        with tempfile.TemporaryDirectory() as tmpdir:
            key_path = Path(tmpdir) / "test_key"
            service = EncryptionService(key_path)

            plaintext = ""
            ciphertext = service.encrypt(plaintext)
            decrypted = service.decrypt(ciphertext)

            assert decrypted == plaintext

    def test_encrypt_long_string(self):
        """Test encrypting and decrypting long string."""
        with tempfile.TemporaryDirectory() as tmpdir:
            key_path = Path(tmpdir) / "test_key"
            service = EncryptionService(key_path)

            plaintext = "a" * 10000
            ciphertext = service.encrypt(plaintext)
            decrypted = service.decrypt(ciphertext)

            assert decrypted == plaintext

    def test_encrypt_json_roundtrip(self):
        """Test encrypting and decrypting JSON data."""
        with tempfile.TemporaryDirectory() as tmpdir:
            key_path = Path(tmpdir) / "test_key"
            service = EncryptionService(key_path)

            data = {
                "api_key": "secret-key-123",
                "config": {
                    "enabled": True,
                    "count": 5,
                },
                "list": [1, 2, 3],
            }

            ciphertext = service.encrypt_json(data)

            # Ciphertext should be a string
            assert isinstance(ciphertext, str)

            # Decrypt should recover original data
            decrypted = service.decrypt_json(ciphertext)
            assert decrypted == data

    def test_encrypt_json_empty_dict(self):
        """Test encrypting and decrypting empty dictionary."""
        with tempfile.TemporaryDirectory() as tmpdir:
            key_path = Path(tmpdir) / "test_key"
            service = EncryptionService(key_path)

            data = {}
            ciphertext = service.encrypt_json(data)
            decrypted = service.decrypt_json(ciphertext)

            assert decrypted == data

    def test_encrypt_json_nested_structure(self):
        """Test encrypting and decrypting nested JSON structure."""
        with tempfile.TemporaryDirectory() as tmpdir:
            key_path = Path(tmpdir) / "test_key"
            service = EncryptionService(key_path)

            data = {
                "level1": {
                    "level2": {
                        "level3": {
                            "secret": "deeply nested secret",
                        }
                    }
                }
            }

            ciphertext = service.encrypt_json(data)
            decrypted = service.decrypt_json(ciphertext)

            assert decrypted == data

    def test_different_keys_produce_different_ciphertext(self):
        """Test that different keys produce different ciphertext."""
        with tempfile.TemporaryDirectory() as tmpdir:
            key_path1 = Path(tmpdir) / "key1"
            key_path2 = Path(tmpdir) / "key2"

            service1 = EncryptionService(key_path1)
            service2 = EncryptionService(key_path2)

            plaintext = "test message"
            ciphertext1 = service1.encrypt(plaintext)
            ciphertext2 = service2.encrypt(plaintext)

            # Different keys should produce different ciphertext
            assert ciphertext1 != ciphertext2

    def test_same_plaintext_produces_different_ciphertext(self):
        """Test that encrypting same plaintext multiple times produces different ciphertext."""
        with tempfile.TemporaryDirectory() as tmpdir:
            key_path = Path(tmpdir) / "test_key"
            service = EncryptionService(key_path)

            plaintext = "test message"
            ciphertext1 = service.encrypt(plaintext)
            ciphertext2 = service.encrypt(plaintext)

            # Fernet includes random IV, so same plaintext produces different ciphertext
            assert ciphertext1 != ciphertext2

            # Both should decrypt to same plaintext
            assert service.decrypt(ciphertext1) == plaintext
            assert service.decrypt(ciphertext2) == plaintext

    def test_wrong_key_cannot_decrypt(self):
        """Test that data encrypted with one key cannot be decrypted with another."""
        with tempfile.TemporaryDirectory() as tmpdir:
            key_path1 = Path(tmpdir) / "key1"
            key_path2 = Path(tmpdir) / "key2"

            service1 = EncryptionService(key_path1)
            service2 = EncryptionService(key_path2)

            plaintext = "test message"
            ciphertext = service1.encrypt(plaintext)

            # Attempting to decrypt with wrong key should raise exception
            with pytest.raises(Exception):
                service2.decrypt(ciphertext)

    def test_tampered_ciphertext_cannot_decrypt(self):
        """Test that tampered ciphertext cannot be decrypted."""
        with tempfile.TemporaryDirectory() as tmpdir:
            key_path = Path(tmpdir) / "test_key"
            service = EncryptionService(key_path)

            plaintext = "test message"
            ciphertext = service.encrypt(plaintext)

            # Tamper with the ciphertext
            tampered = ciphertext[:-5] + "XXXXX"

            # Should raise exception when trying to decrypt
            with pytest.raises(Exception):
                service.decrypt(tampered)

    def test_invalid_json_raises_error(self):
        """Test that encrypting invalid JSON raises error."""
        with tempfile.TemporaryDirectory() as tmpdir:
            key_path = Path(tmpdir) / "test_key"
            service = EncryptionService(key_path)

            # Objects that can't be JSON serialized
            class CustomObject:
                pass

            with pytest.raises(TypeError):
                service.encrypt_json({"obj": CustomObject()})

    def test_decrypt_json_with_invalid_data_raises_error(self):
        """Test that decrypting non-JSON data with decrypt_json raises error."""
        with tempfile.TemporaryDirectory() as tmpdir:
            key_path = Path(tmpdir) / "test_key"
            service = EncryptionService(key_path)

            # Encrypt non-JSON data
            ciphertext = service.encrypt("not json")

            # Should raise JSON decode error
            with pytest.raises(json.JSONDecodeError):
                service.decrypt_json(ciphertext)
