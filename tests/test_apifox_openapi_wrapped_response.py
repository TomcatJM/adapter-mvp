import base64
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.apifox import fetch_sanitized_openapi


class _FakeResponse:
    def __init__(self, body: str) -> None:
        self.body = body.encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:
        return False

    def read(self) -> bytes:
        return self.body


class WrappedOpenapiResponseTest(unittest.TestCase):
    def test_fetch_sanitized_openapi_decodes_json_string_base64_wrapper(self) -> None:
        upstream_spec = {
            "openapi": "3.1.0",
            "info": {"title": "gmc", "version": "1.0"},
            "paths": {
                "/jdb-school-gmc/school/page": {"get": {"summary": "分页"}},
            },
        }
        wrapped_body = json.dumps(
            base64.b64encode(json.dumps(upstream_spec).encode("utf-8")).decode("ascii")
        )

        with patch("app.apifox.urllib.request.urlopen", return_value=_FakeResponse(wrapped_body)):
            result = fetch_sanitized_openapi("jdb-school-gmc")

        self.assertEqual(result["openapi"], "3.1.0")
        self.assertEqual(result["servers"], [{"url": "/jdb-school-gmc"}])
        self.assertIn("/school/page", result["paths"])
        self.assertNotIn("/jdb-school-gmc/school/page", result["paths"])


if __name__ == "__main__":
    unittest.main()
