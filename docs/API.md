# API reference (all under /api, JWT Bearer, admin-only marked *)

Auth: POST /auth/login (form username/password) -> {access_token},
  GET /auth/me
Dashboard: GET /dashboard/stats, GET /dashboard/accounts-summary
Health (liveness, no auth): GET /api/health

Accounts: GET /accounts, POST /accounts *, GET /accounts/{id},
  POST /accounts/{id}/disconnect *
Drive: GET /drive/oauth/start *, GET /drive/oauth/callback,
  GET /drive/connection, POST /drive/disconnect *,
  GET /drive/folders, POST /drive/sync *,
  GET /drive/account-folders, POST /drive/changes/sync *
Instagram: GET /instagram/oauth/start *, GET /instagram/oauth/callback,
  POST /instagram/accounts/{id}/check,
  POST /instagram/accounts/{id}/reconnect *
Mappings: GET /mappings, POST /mappings *
Videos: GET /videos, GET /videos/{id}, PATCH /videos/{id}
  (caption/hashtags), POST /videos/scan *, POST /videos/scan/{account_id} *
Schedules: GET /schedules, POST /schedules, POST /schedules/bulk,
  GET /schedules/calendar, GET /schedules/next-eligible,
  GET /schedules/{id}/attempts, GET /schedules/{id}/logs,
  POST /schedules/{id}/reconcile *, POST /schedules/{id}/retry *,
  PATCH /schedules/{id}, POST /schedules/{id}/pause,
  POST /schedules/{id}/resume, POST /schedules/{id}/cancel
Media: GET /media/{signed-token}/{filename} (signed, short-lived)
Failed jobs: GET /failed-jobs
Notifications: GET /notifications, POST /notifications/{id}/read,
  POST /notifications/mark-all-read
Health: GET /health/accounts, GET /health/accounts/{id},
  POST /health/check-all *
Reports: GET /reports/daily, POST /reports/generate *,
  GET /reports, GET /reports/export.csv
Alerts: POST /alerts/test *

Full request/response shapes are the Pydantic schemas in
backend/app/schemas.py and the router code in backend/app/routers/.
No response ever includes a token field.
