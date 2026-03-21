# Gmail API Setup Guide

## Step 1: Create a Google Cloud Project

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Click "New Project" and name it "BizOps" (or whatever you like)
3. Select the project

## Step 2: Enable the Gmail API

1. Go to **APIs & Services > Library**
2. Search for "Gmail API"
3. Click **Enable**

## Step 3: Create OAuth2 Credentials

1. Go to **APIs & Services > Credentials**
2. Click **Create Credentials > OAuth client ID**
3. If prompted, configure the OAuth consent screen:
   - User Type: **External** (or Internal if using Google Workspace)
   - App name: "BizOps"
   - Scopes: Add `https://www.googleapis.com/auth/gmail.readonly`
4. Application type: **Desktop app**
5. Name: "BizOps CLI"
6. Click **Create**
7. Click **Download JSON** — save as `credentials.json`

## Step 4: Configure BizOps

```bash
bizops config setup --credentials /path/to/credentials.json
```

The first time you run `bizops invoices pull`, a browser window will open asking you to authorize Gmail access. After authorization, a `token.json` is saved so you won't need to re-authorize.

## Security Notes

- BizOps only requests **read-only** Gmail access
- Credentials and tokens are stored locally (never uploaded)
- Add `credentials.json` and `token.json` to `.gitignore` (already done)
- You can revoke access anytime at [Google Account Permissions](https://myaccount.google.com/permissions)

## Troubleshooting

**"Access blocked" error**: Your app is in testing mode. Go to OAuth consent screen > Test users and add your Gmail address.

**"Token expired"**: Delete `token.json` and re-run. BizOps will prompt for re-authorization.

**"Quota exceeded"**: Gmail API has a limit of ~250 quota units/second. If you're processing thousands of emails, add `--max-results 50` to limit batch size.
