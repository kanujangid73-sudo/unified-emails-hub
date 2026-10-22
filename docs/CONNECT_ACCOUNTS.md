# Connecting real mailboxes

The demo works with no setup. To connect real accounts, the server needs credentials for the
providers you want. All three options below are free.

| Provider | How it connects | Server setup |
|---|---|---|
| Any IMAP mailbox (Yahoo, iCloud, Zoho, Fastmail, AOL, company servers…) | Address + app password | None |
| Gmail | "Sign in with Google" (OAuth) | A Google Cloud OAuth client |
| Outlook.com, Hotmail, Microsoft 365 | "Sign in with Microsoft" (OAuth) | A Microsoft Entra app registration |

Whatever you configure, set `ENCRYPTION_KEY` in `backend/.env` first, so stored passwords
and tokens survive restarts:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

## IMAP (no setup)

1. In the app: **Add or manage accounts → Other (IMAP)**.
2. Type your address; for common providers the servers fill in automatically.
3. Use an **app password**, not your normal password. Providers with 2-step verification
   refuse normal passwords over IMAP. Create one in your account's security settings:
   Yahoo (Account security → Generate app password), iCloud (appleid.apple.com → App-Specific
   Passwords), Gmail (myaccount.google.com/apppasswords).

Only encrypted connections are allowed (IMAP on port 993, SMTP on 465 or 587).

## Gmail

1. Open [console.cloud.google.com](https://console.cloud.google.com), create a project.
2. **APIs & Services → Library**: enable the **Gmail API**.
3. **APIs & Services → OAuth consent screen**: choose **External**, fill in the app name and
   your email. Under **Scopes** add `https://www.googleapis.com/auth/gmail.modify`.
   Under **Test users** add the Gmail addresses you'll connect (up to 100).
4. **APIs & Services → Credentials → Create credentials → OAuth client ID**:
   type **Web application**, authorized redirect URI:
   `http://localhost:8000/api/oauth/gmail/callback` (and your deployed API URL later).
5. Put the client id and secret in `backend/.env`:

   ```
   GOOGLE_CLIENT_ID=....apps.googleusercontent.com
   GOOGLE_CLIENT_SECRET=...
   ```

Things to know:

- While the app is in **Testing** mode, Google shows an "unverified app" warning (click
  *Continue*), and **refresh tokens expire after 7 days**, so the account will ask to be
  reconnected weekly. That's fine for a portfolio. Making it public needs Google's
  verification, which includes a paid security assessment for Gmail scopes.
- `gmail.modify` allows reading, labelling (read, star, archive) and sending, but never
  permanent deletion.

## Outlook / Microsoft 365

1. Open [entra.microsoft.com](https://entra.microsoft.com) (sign in with any Microsoft account)
   → **App registrations → New registration**.
2. Supported account types: **Accounts in any organizational directory and personal Microsoft
   accounts**. Redirect URI: platform **Web**, `http://localhost:8000/api/oauth/outlook/callback`.
3. **Certificates & secrets → New client secret**; copy the *Value*.
4. **API permissions → Add → Microsoft Graph → Delegated**: `Mail.ReadWrite`, `Mail.Send`,
   `User.Read`, `offline_access`.
5. In `backend/.env`:

   ```
   MICROSOFT_CLIENT_ID=<Application (client) ID>
   MICROSOFT_CLIENT_SECRET=<secret value>
   ```

## When deployed

Set `PUBLIC_API_URL` (the API's address) and `FRONTEND_URL` (the web app's address), and add
`<PUBLIC_API_URL>/api/oauth/gmail/callback` and `.../outlook/callback` as redirect URIs in the
Google and Microsoft consoles.
