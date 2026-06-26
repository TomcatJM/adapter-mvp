import os
import unittest
from unittest.mock import patch

from fastapi import HTTPException


class AdapterAuthTest(unittest.TestCase):
    def test_env_token_still_works_as_fallback(self) -> None:
        from app.auth import require_api_token

        with patch.dict(os.environ, {"ADAPTER_API_TOKEN": "env-token"}, clear=True), patch(
            "app.auth.db.find_api_client_by_token", return_value=None
        ) as find_client:
            require_api_token("Bearer env-token")

        find_client.assert_called_once_with("env-token")

    def test_database_api_client_token_is_accepted(self) -> None:
        from app.auth import require_api_token

        with patch.dict(os.environ, {}, clear=True), patch(
            "app.auth.db.find_api_client_by_token",
            return_value={"clientId": "codex", "clientName": "Codex", "scopes": ["workflow:write"]},
        ):
            require_api_token("Bearer db-token")

    def test_invalid_token_is_rejected_when_auth_is_configured(self) -> None:
        from app.auth import require_api_token

        with patch.dict(os.environ, {"ADAPTER_API_TOKEN": "env-token"}, clear=True), patch(
            "app.auth.db.find_api_client_by_token", return_value=None
        ):
            with self.assertRaises(HTTPException) as raised:
                require_api_token("Bearer bad-token")

        self.assertEqual(raised.exception.status_code, 403)
        self.assertEqual(raised.exception.detail, "Invalid bearer token")

    def test_env_token_passes_when_database_lookup_fails(self) -> None:
        from app.auth import require_api_token

        with patch.dict(os.environ, {"ADAPTER_API_TOKEN": "env-token"}, clear=True), patch(
            "app.auth.db.find_api_client_by_token", side_effect=RuntimeError("db unavailable")
        ):
            require_api_token("Bearer env-token")

    def test_database_lookup_failure_returns_503_without_matching_env_token(self) -> None:
        from app.auth import require_api_token

        with patch.dict(os.environ, {"ADAPTER_API_TOKEN": "env-token"}, clear=True), patch(
            "app.auth.db.find_api_client_by_token", side_effect=RuntimeError("db unavailable")
        ):
            with self.assertRaises(HTTPException) as raised:
                require_api_token("Bearer db-token")

        self.assertEqual(raised.exception.status_code, 503)
        self.assertEqual(raised.exception.detail, "API token store unavailable")


if __name__ == "__main__":
    unittest.main()
