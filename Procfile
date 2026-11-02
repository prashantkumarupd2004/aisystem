# Railway / Render / Heroku-style process types (Phase 9).
# Backend code lives in backend/app, so PYTHONPATH=backend is required.
# Web (API) and worker MUST be separate processes in production.
web: PYTHONPATH=backend uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
worker: PYTHONPATH=backend python -m app.worker
