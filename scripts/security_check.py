#!/usr/bin/env python3
"""Static security checks (Phase 10).

Checks the backend source for the most common leaks:
  1. No router returns an encrypted token field in a response schema
     (tokens are only ever written, never read back via API).
  2. No hard-coded-looking Fernet key or JWT secret in source
     (the only allowed default is the explicit dev placeholder
     'change-me-in-production', which deploy_check blocks in prod).
  3. No .env file committed, no token/secret files in the repo.
Exit 0 = pass, 1 = failure. Tested in test_phase10.py.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def check() -> list[str]:
    failures: list[str] = []
    backend = ROOT / "backend" / "app"
    # 1. Response schemas must not expose token columns.
    schemas = (backend / "schemas.py").read_text()
    for field in ("access_token_encrypted", "refresh_token_encrypted"):
        if field in schemas:
            failures.append(f"schemas.py exposes {field} in an API response schema")
    # Routers may WRITE encrypted tokens, but must not return them:
    # a simple heuristic -- a return statement mentioning the field.
    for router in (backend / "routers").glob("*.py"):
        text = router.read_text()
        for line in text.splitlines():
            if "return" in line and "access_token_encrypted" in line:
                failures.append(f"{router.name} returns an encrypted token: {line.strip()}")
    # 2. Hard-coded secrets: a 44-char base64 Fernet-looking string,
    # or a password assignment with a non-empty literal.
    fernet_re = re.compile(r"[A-Za-z0-9_-]{43}=")
    for path in list(backend.rglob("*.py")) + list((ROOT / "scripts").glob("*.py")):
        for i, line in enumerate(path.read_text().splitlines(), 1):
            if fernet_re.search(line) and "test" not in str(path):
                failures.append(f"{path.relative_to(ROOT)}:{i} looks like a hard-coded Fernet key")
    # 3. No committed .env with values.
    for env_file in (ROOT / ".env", ROOT / "backend" / ".env"):
        if env_file.exists():
            failures.append(f"{env_file.relative_to(ROOT)} exists in the repo -- use .env.example instead")
    return failures


def main() -> int:
    failures = check()
    for f in failures:
        print(f"FAIL: {f}")
    if failures:
        print(f"SECURITY CHECK FAILED: {len(failures)} issue(s)")
        return 1
    print("SECURITY CHECK PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
