# Meta / Instagram setup (Phase 3)

You need a Meta app. No code change is needed — only environment
variables and app configuration.

1. Go to https://developers.facebook.com → create an app
   (type: Business, or Other with the Instagram Graph API product).
2. Add the **Instagram Graph API** product (and Facebook Login).
3. App → Settings → Basic: note the App ID and App Secret.
4. Facebook Login → Settings → Valid OAuth Redirect URIs, add exactly:
   `http://localhost:8000/api/instagram/oauth/callback`
   (add the deployed backend URL too for cloud mode, and set
   `META_REDIRECT_URI` to match).
5. Instagram Graph API permissions requested by this system:
   `instagram_basic`, `instagram_content_publish`,
   `pages_show_list`, `pages_read_engagement`.
   Publishing Reels requires `instagram_content_publish` and an
   Instagram Business or Creator account linked to a Facebook Page.
   Personal Instagram accounts are NOT eligible and are skipped.
6. While the app is in Development mode, only test users / test
   Instagram accounts can connect. Add them under Roles → Test Users,
   or submit the app for App Review for the scopes above before
   connecting production accounts.
7. Copy into `backend/.env`:
   ```
   META_APP_ID=...
   META_APP_SECRET=...
   META_REDIRECT_URI=http://localhost:8000/api/instagram/oauth/callback
   ```
8. In the dashboard, open **Instagram Accounts** → Connect Instagram,
   complete Facebook Login, and grant the scopes. The callback creates
   or updates one account row per eligible Page-linked IG account
   (upsert by Instagram user ID, no duplicates) and stores the Page
   access token encrypted.

Token lifetime:
- The user token is exchanged for a long-lived token (~60 days) and
  stored encrypted. Refresh it before expiry; an expired/revoked
  token cannot be refreshed silently — the account shows
  TOKEN_EXPIRED / PERMISSION_REVOKED and must be reconnected.
- A successful API check means "API accessible" only. It is never
  presented as proof the account is not suspended — that cannot be
  confirmed through the authorised APIs, so an unconfirmable case
  stays UNKNOWN / NEEDS_MANUAL_REVIEW.
