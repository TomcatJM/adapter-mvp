import os
import unittest
from unittest.mock import patch


class ApiClientTokenStorageTest(unittest.TestCase):
    def test_token_can_be_encrypted_and_decrypted_with_configured_key(self) -> None:
        from app import db

        with patch.dict(os.environ, {"ADAPTER_API_TOKEN_ENCRYPTION_KEY": "unit-test-key"}, clear=True):
            ciphertext = db.encrypt_api_token("plain-token")

            self.assertIsNotNone(ciphertext)
            self.assertNotEqual(ciphertext, "plain-token")
            self.assertEqual(db.decrypt_api_token(ciphertext), "plain-token")

    def test_token_encryption_is_skipped_without_key(self) -> None:
        from app import db

        with patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(db.encrypt_api_token("plain-token"))

    def test_token_last4_masks_short_and_long_tokens(self) -> None:
        from app import db

        self.assertEqual(db.api_token_last4("abcdef"), "cdef")
        self.assertEqual(db.api_token_last4("abc"), "abc")
        self.assertIsNone(db.api_token_last4(""))


if __name__ == "__main__":
    unittest.main()
