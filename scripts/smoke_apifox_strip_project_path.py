"""
Smoke-test stripping service project prefix from OpenAPI paths before Apifox import.
"""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.apifox import OpenapiValidationError, _validate_openapi_spec, strip_project_path_from_openapi  # noqa: E402


def main() -> None:
    spec = {
        "openapi": "3.1.0",
        "info": {"title": "jdb-order", "version": "1.0"},
        "paths": {
            "/jdb-order/stuStudentOrg/checkStuPhone": {"get": {"summary": "校验学员手机号"}},
            "/jdb-order/stuStudentOrg/page": {"post": {"summary": "分页"}},
            "/health": {"get": {"summary": "健康检查"}},
        },
    }
    result = strip_project_path_from_openapi(spec, "jdb-order")
    paths = result["paths"]
    assert "/stuStudentOrg/checkStuPhone" in paths, paths
    assert "/stuStudentOrg/page" in paths, paths
    assert "/jdb-order/stuStudentOrg/checkStuPhone" not in paths, paths
    assert "/health" in paths, paths
    assert result["servers"] == [{"url": "/jdb-order"}], result
    try:
        _validate_openapi_spec({"msg": "token失效", "code": 401, "data": {"tokeninc": 0}})
    except OpenapiValidationError:
        pass
    else:
        raise AssertionError("invalid upstream JSON should not pass OpenAPI validation")
    print("apifox strip project path smoke OK: /jdb-order/* -> /*")


if __name__ == "__main__":
    main()
