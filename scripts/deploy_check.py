#!/usr/bin/env python3
"""Pre-deployment readiness check (Phase 9).

Usage:
  python scripts/deploy_check.py [--mode production|development] [--env-file .env]

Exit 0 = deployable (warnings allowed), exit 1 = blocking error.
The pure function check(env, mode) is unit-tested in test_phase9.py;
the CLI only loads .env / os.environ and prints the result.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def check(env: dict, mode: str = "production") -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    # Token encryption: without a real key, encrypted OAuth tokens
    # do not survive a restart (config.py generates an ephemeral key).
    key = env.get("TOKEN_ENCRYPTION_KEY")
    if not key:
        errors.append("TOKEN_ENCRYPTION_KEY is missing (tokens will not survive a restart)")
    else:
        try:
            from cryptography.fernet import Fernet

            Fernet(key.encode())
        except Exception:
            errors.append("TOKEN_ENCRYPTION_KEY is not a valid Fernet key")

    if env.get("SECRET_KEY") in (None, "", "change-me-in-production"):
        errors.append("SECRET_KEY is missing or still the default 'change-me-in-production'")

    if not env.get("ADMIN_EMAIL") or not env.get("ADMIN_PASSWORD"):
        warnings.append("ADMIN_EMAIL / ADMIN_PASSWORD missing: first admin cannot be created on a fresh DB")

    db = env.get("DATABASE_URL", "")
    if mode == "production":
        if not db.startswith("postgresql"):
            errors.append(
                f"Production DATABASE_URL must be postgresql, got: {db[:20] or '(empty)'}"
            )
        media = env.get("PUBLIC_MEDIA_BASE_URL", "")
        if not media.startswith("https://") or "localhost" in media:
            errors.append(
                "Production PUBLIC_MEDIA_BASE_URL must be a stable public HTTPS URL "
                f"(got: {media or '(empty)'}); Cloudflare Quick Tunnel URLs are temporary"
            )
        if not media.endswith("/media"):
            warnings.append("PUBLIC_MEDIA_BASE_URL should end with /media (Meta fetches from that path)")
    else:
        if not db:
            warnings.append("DATABASE_URL empty; backend defaults to local SQLite")

    for name in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "META_APP_ID", "META_APP_SECRET"):
        if not env.get(name):
            warnings.append(f"{name} missing: that OAuth connection cannot be completed until it is set")

    if env.get("ENABLE_SCHEDULER") == "true":
        warnings.append(
            "ENABLE_SCHEDULER=true with a separate worker process means two workers "
            "will tick (claim locking prevents duplicates, but run only one)"
        )
    return errors, warnings


def _load_env_file(path: str) -> dict:
    env: dict = {}
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        env[key.strip()] = value.strip().strip('"').strip("'")
    return env


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", default="production", choices=["production", "development"])
    parser.add_argument("--env-file", default=None)
    args = parser.parse_args()
    env = dict(os.environ)
    if args.env_file:
        env.update(_load_env_file(args.env_file))
    errors, warnings = check(env, args.mode)
    for w in warnings:
        print(f"WARN: {w}")
    for e in errors:
        print(f"ERROR: {e}")
    if errors:
        print(f"NOT READY: {len(errors)} blocking error(s)")
        return 1
    print(f"READY ({len(warnings)} warning(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main())
