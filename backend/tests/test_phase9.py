"""Phase 9 tests: deploy check + deployment config files.

Run: cd backend && python -m pytest tests -q
"""
import importlib.util
import os
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]

sys.path.insert(0, str(ROOT / "scripts"))
import deploy_check  # noqa: E402


def _good_env():
    from cryptography.fernet import Fernet

    return {
        "TOKEN_ENCRYPTION_KEY": Fernet.generate_key().decode(),
        "SECRET_KEY": "a-real-secret",
        "ADMIN_EMAIL": "admin@example.com",
        "ADMIN_PASSWORD": "pw",
        "DATABASE_URL": "postgresql://u:p@host:5432/aisystem",
        "PUBLIC_MEDIA_BASE_URL": "https://api.example.com/media",
        "GOOGLE_CLIENT_ID": "x",
        "GOOGLE_CLIENT_SECRET": "y",
        "META_APP_ID": "z",
        "META_APP_SECRET": "w",
    }


def test_production_check_passes_for_good_env():
    errors, warnings = deploy_check.check(_good_env(), "production")
    assert errors == []


def test_production_check_blocks_sqlite_and_localhost_media():
    env = _good_env()
    env["DATABASE_URL"] = "sqlite:///./data/app.db"
    env["PUBLIC_MEDIA_BASE_URL"] = "http://localhost:8000/media"
    errors, _ = deploy_check.check(env, "production")
    assert any("postgresql" in e for e in errors)
    assert any("HTTPS" in e for e in errors)


def test_check_blocks_missing_or_invalid_keys():
    env = _good_env()
    env["TOKEN_ENCRYPTION_KEY"] = "not-a-fernet-key"
    env["SECRET_KEY"] = "change-me-in-production"
    errors, _ = deploy_check.check(env, "production")
    assert len(errors) >= 2


def test_check_warns_but_does_not_block_missing_oauth():
    env = _good_env()
    del env["GOOGLE_CLIENT_ID"]
    errors, warnings = deploy_check.check(env, "production")
    assert errors == []
    assert any("GOOGLE_CLIENT_ID" in w for w in warnings)


def test_compose_file_is_valid_and_has_worker():
    data = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
    services = data["services"]
    assert {"db", "backend", "worker", "frontend"} <= set(services)
    assert services["worker"]["command"] == ["python", "-m", "app.worker"]
    assert services["backend"]["environment"]["ENABLE_SCHEDULER"] == "false"
    # Backend and worker share the media volume.
    backend_vols = " ".join(services["backend"]["volumes"])
    worker_vols = " ".join(services["worker"]["volumes"])
    assert "media_temp" in backend_vols and "media_temp" in worker_vols


def test_dockerfiles_and_procfile_exist():
    assert (ROOT / "backend" / "Dockerfile").read_text().count("ffmpeg") >= 1
    frontend_df = (ROOT / "frontend" / "Dockerfile").read_text()
    assert "npm ci" in frontend_df and "NEXT_PUBLIC_API_URL" in frontend_df
    procfile = (ROOT / "Procfile").read_text()
    assert "uvicorn app.main:app" in procfile and "app.worker" in procfile
    assert (ROOT / "render.yaml").exists()
    assert (ROOT / ".env.production.example").exists()
    assert (ROOT / "deploy" / "aisystem-backend.service").exists()
    assert (ROOT / "deploy" / "aisystem-worker.service").exists()
