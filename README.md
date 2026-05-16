# Jira Explorer - Gravity Data

Desktop Jira ticket viewer with full comment threads, filtering, search, and an analytics dashboard.
Built with Python + PyQt5, styled in Data Dimensions brand colors.

---

## Features

| Feature | Details |
|---|---|
| **My Issues** | All tickets assigned to you, auto-loaded on startup |
| **Filters** | Project · Status · Priority · Issue Type — all independent |
| **Live Search** | Instant key + summary search as you type |
| **Issue Detail** | Summary, status/priority/type badges, description (ADF rendered), metadata |
| **Comments** | Full comment thread with author avatars, timestamps, rich text |
| **Analytics** | 6 charts: by status, priority, type, project, creation trend, summary stats |
| **Pagination** | Fetches all assigned issues automatically (handles > 100) |
| **Secure auth** | API token stored in Windows Credential Manager / macOS Keychain via `keyring` |
| **Dark theme** | Deep navy Data Dimensions palette throughout |

---

## Setup

### 1. Install Python 3.10+

Verify: `python --version`

### 2. Install dependencies

```
pip install PyQt5 requests keyring matplotlib
```

Or from the requirements file:

```
pip install -r requirements.txt
```

> **PyQt5 on Windows:** If `pip install PyQt5` fails, try:
> `pip install PyQt5 --only-binary=PyQt5`

### 3. Get a Jira API token

1. Go to https://id.atlassian.com/manage-profile/security/api-tokens
2. Click **Create API token**
3. Label it `DD Jira Explorer`
4. Copy the token — you only see it once

### 4. Run the app

```
python jira_explorer.py
```

The **Settings** screen will open on first launch. Enter:

| Field | Value |
|---|---|
| Jira Base URL | `https://datadimensions2.atlassian.net` |
| Email Address | Your Atlassian login email |
| API Token | The token you just generated |

Click **Save & Connect** — the app will verify the connection and load your issues.

---

## Authentication Notes

**API Token (recommended for this app)**

Jira Cloud's REST API requires Basic Auth with your **email address** and an **API token** — not your account password. The token is stored in your OS keychain (Windows Credential Manager or macOS Keychain) via the `keyring` package so it is not written to disk in plaintext.

**Why not Microsoft SSO / OAuth?**

Microsoft SSO via Atlassian works in the browser. A desktop Python app connecting to Jira's REST API cannot participate in that browser-based OAuth flow without a registered Azure AD application, callback server, and consent grant — significant setup for a tool you run yourself. The API token path is the standard way to authenticate Jira REST API clients and is fully supported by Atlassian.

---

## Usage

### My Issues tab

- All issues assigned to you load on startup
- Use the **four dropdowns** to filter by Project / Status / Priority / Type — independently and in combination
- Type in the search box to instantly filter by key or summary text
- Click any row to open the full issue detail in the right panel
- Click the **Comments** tab to see the full comment thread (loaded asynchronously)
- Press **⟳ Refresh** to re-fetch from Jira

### Analytics tab

Click **Analytics** in the left sidebar to see:

- Issues by Status (horizontal bar)
- Issues by Priority (donut chart)
- Issues by Type (bar)
- Issues by Project (bar, sorted by count)
- Created over the last 90 days (weekly line chart)
- Summary stats panel (total, open, closed, oldest/newest)

Analytics reflect the currently-loaded issue set, so refresh first if needed.

### Settings tab

Update your URL, email, or token at any time. Clicking **Test Connection** validates credentials without saving. **Save & Connect** saves and re-connects immediately.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `ModuleNotFoundError: PyQt5` | `pip install PyQt5` |
| `ModuleNotFoundError: requests` | `pip install requests` |
| Charts missing | `pip install matplotlib` |
| 401 Authentication failed | Wrong email or expired/invalid token — regenerate at id.atlassian.com |
| 403 Access denied | Your token may lack Jira project access — check with Jim/Justin |
| Cannot reach Jira | Check VPN / network — Jira Cloud requires internet access |
| App opens to Settings every time | Credentials not saved — complete Settings and click Save & Connect |

---

## File Structure

```
jira_explorer/
├── jira_explorer.py    ← Single-file application (run this)
├── requirements.txt    ← pip dependencies
└── README.md           ← This file
```

Settings are persisted via `QSettings` (Windows Registry under `HKCU\Software\DataDimensions\Jira Explorer`). Credential is in Windows Credential Manager as `dd_jira_explorer`.

---

## Jira Projects Known to Be Available

Based on your DataDimensions instance (`datadimensions2.atlassian.net`):

- **CHS** — Client/helpdesk tickets
- **DBA** — Database & Analytics team work items
- **DC** — Data center / infrastructure

The Project filter will auto-populate from whatever projects appear in your assigned issues.
