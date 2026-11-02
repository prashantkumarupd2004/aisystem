# Google Drive setup (Phase 2)

You need a Google Cloud project. No code change is needed — only
environment variables and a consent-screen configuration.

1. Go to https://console.cloud.google.com → create a project.
2. APIs & Services → Library → enable **Google Drive API**.
3. APIs & Services → OAuth consent screen:
   - User type: External (or Internal if you use Google Workspace).
   - Add scope `https://www.googleapis.com/auth/drive.readonly`.
   - Add yourself as a test user while the app is in Testing mode.
     (Testing-mode apps can only be used by test users; publishing the
     app for general use requires Google verification — not needed for
     your own single central Drive account.)
4. APIs & Services → Credentials → Create OAuth client ID →
   Web application.
   - Authorised redirect URI (must match exactly):
     `http://localhost:8000/api/drive/oauth/callback`
   - For a deployed backend, add its public callback URL too and set
     `GOOGLE_REDIRECT_URI` / `FRONTEND_URL` to match.
5. Copy the client ID + secret into `backend/.env`:
   ```
   GOOGLE_CLIENT_ID=...
   GOOGLE_CLIENT_SECRET=...
   GOOGLE_REDIRECT_URI=http://localhost:8000/api/drive/oauth/callback
   FRONTEND_URL=http://localhost:3000
   ```
6. In the dashboard, open **Google Drive Integration** → Connect.
   The backend exchanges the code, stores access + refresh tokens
   encrypted, and marks the connection CONNECTED.
7. Click **Sync folders**. The expected Drive layout is:
   ```
   Instagram-Automation/
       XYZ/
       ABC/
       Travel_USA/
   ```
   Mapping then pairs each Instagram account with exactly one folder
   (see the Account-Folder Mapping page). A folder name is only a
   display label — the mapping stores the permanent Drive folder ID.

Notes:
- Scope is read-only on purpose: the system never writes to, renames
  or deletes your Drive videos.
- If the refresh token stops working (revoked in your Google account),
  the connection shows an error on the next sync and you simply
  reconnect; no video rows are deleted by a disconnect.
- Phase 4 will use the changes feed (`POST /api/drive/changes/sync`)
  to detect new videos without a full re-scan.
