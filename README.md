<div align="center">

# 📬 Unified Emails Hub

### All your email accounts. One beautiful inbox.

Gmail, Outlook, Yahoo, iCloud, Zoho, work mail: read, search, reply and clean up in one place,
without jumping between apps.

[![CI](https://github.com/kanujangid73-sudo/unified-emails-hub/actions/workflows/ci.yml/badge.svg)](https://github.com/kanujangid73-sudo/unified-emails-hub/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)
![React](https://img.shields.io/badge/React-18-61DAFB?logo=react&logoColor=black)
![Vite](https://img.shields.io/badge/Vite-646CFF?logo=vite&logoColor=white)

[**🚀 Quick start**](#-quick-start) · [**✨ Features**](#-features) · [**🔌 Connect accounts**](#-connect-your-real-email) · [**☁️ Deploy**](#️-put-it-online) · [**🔒 Privacy**](#-privacy--security)

<br>

![Unified inbox showing conversations from multiple email accounts](docs/screenshot-inbox.png)

</div>

---

## 🎮 Try it in 30 seconds: no email account needed

The built-in **demo** lets you explore everything safely:

1. Start the app ([Quick start](#-quick-start) below), or open your hosted copy.
2. Click **Try the demo** on the sign-in screen.
3. Explore **3 sample mailboxes** with about **170 messages**.

> 💡 Everyone in the demo is fictional, and demo accounts are deleted automatically after 24 hours.

---

## ✨ Features

| | Feature | What it does for you |
|:-:|---|---|
| 📥 | **One unified inbox** | See Gmail, Outlook and any IMAP mailbox (Yahoo, iCloud, Zoho, work email) side by side. |
| 💬 | **Threaded conversations** | Read, star, archive, and mark messages read or unread. Browse every folder. |
| 🔍 | **Search everything** | Search all accounts at once by sender, recipient, date, unread, starred or has-attachment. |
| ✍️ | **Write & reply** | Send new mail. Replies stay in the right conversation. |
| 📎 | **Attachments** | View, download and send attachments with any provider. |
| 🧹 | **Clean-up** | See which senders take up the most space and how much of their mail you open, then move it to Trash in bulk. Starred mail is always kept, and Trash stays recoverable for about 30 days. |
| 📰 | **Tidy your inbox** | Spot newsletters, review subscriptions, and find large or rarely opened messages. |
| 🕵️ | **Account Finder** | Find the services linked to your email address and export the list as CSV. |
| 🛡️ | **Phishing warnings** | Get warnings about suspicious messages and see your inbox sorted into categories. |
| 🤖 | **AI assistant** *(optional)* | Summarise messages and draft replies with a Gemini API key. |
| 📱 | **Works on your phone** | The layout adapts to small screens. |

---

## 📸 Screenshots

<table>
  <tr>
    <td width="65%" valign="top">
      <b>🕵️ Account Finder: services connected to your email</b><br><br>
      <img src="docs/screenshot-finder.png" alt="Account Finder showing services and the email addresses associated with them">
      <br><br>
      <b>🤖 AI reply drafts</b><br><br>
      <img src="docs/screenshot-draft.png" alt="An AI-drafted reply ready to edit before sending">
    </td>
    <td width="35%" valign="top" align="center">
      <b>📱 On your phone</b><br><br>
      <img src="docs/screenshot-mobile.png" alt="Unified Emails Hub displayed on a phone" width="260">
    </td>
  </tr>
</table>

---

## 🚀 Quick start

### What you need

| Tool | Version | Check with |
|---|---|---|
| 🐍 Python | 3.11 or newer | `python --version` |
| 🟢 Node.js | 20 or newer | `node --version` |

### Step 1: Start the backend (API)

Open a terminal in the project folder and run:

```powershell
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1        # macOS/Linux: source .venv/bin/activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload
```

✅ The API is now running at <http://localhost:8000> (interactive docs at <http://localhost:8000/docs>).

### Step 2: Start the frontend (web app)

Open a **second terminal** in the project folder and run:

```powershell
cd frontend
npm install
npm run dev
```

### Step 3: Open the app 🎉

Go to the address shown in the terminal (usually **<http://localhost:5173>**) and click **Try the demo**.

> ℹ️ The app uses a local SQLite database by default, so there's no database to set up. The demo
> needs no email credentials.

---

## 🔌 Connect your real email

| Provider | What you need |
|---|---|
| <img src="https://img.shields.io/badge/-Gmail-EA4335?logo=gmail&logoColor=white"> | A Google Cloud OAuth client |
| <img src="https://img.shields.io/badge/-Outlook-0078D4?logo=microsoftoutlook&logoColor=white"> | A Microsoft Entra app registration (Outlook or Microsoft 365) |
| <img src="https://img.shields.io/badge/-IMAP-6B7280?logo=maildotru&logoColor=white"> | Just your email address and an **app password** from your provider |

📖 Step-by-step guide: **[docs/CONNECT_ACCOUNTS.md](docs/CONNECT_ACCOUNTS.md)**

---

## ☁️ Put it online

Deploy the web app and API with the included **Render Blueprint**, using a free **Neon** Postgres database.

📖 Follow the **[Render deployment guide](docs/DEPLOY.md)**.

---

## 🔒 Privacy & security

- 🔐 **Encrypted secrets:** saved mailbox passwords and OAuth tokens are encrypted on the backend.
- 🧼 **Safe email viewing:** email HTML is sanitized and shown in a restricted frame. Remote
  images are **not** loaded automatically.
- 🤖 **AI only when you ask:** with Gemini configured, only the email you select is sent to
  Google, and only for that request. Review Google's terms before enabling it.
- 🗑️ **Clean-up never deletes permanently:** mail goes to your provider's Trash.

> ⚠️ **Never publish** `.env` files, API keys, OAuth secrets, or real email data.

---

## 🧰 Built with

| Layer | Technologies |
|---|---|
| 🖥️ Web app | React, Vite |
| ⚙️ API | Python, FastAPI |
| 🗄️ Database | SQLite (local) · Postgres (hosted) |
| ✉️ Email providers | Gmail API · Microsoft Graph · IMAP & SMTP |
| 🧪 Tests | Pytest · Vitest |

<details>
<summary><b>🧪 Running the tests</b></summary>

<br>

**Backend**, from `backend/`:

```powershell
pytest
```

**Frontend**, from `frontend/`:

```powershell
npm test
```

</details>

---

## 📚 More guides

| Guide | Read it when you want to |
|---|---|
| 🔌 [Connect real email accounts](docs/CONNECT_ACCOUNTS.md) | Add Gmail, Outlook or IMAP mailboxes |
| ☁️ [Deploy on Render](docs/DEPLOY.md) | Put the app on the internet |
| 🎬 [Demo walkthrough](docs/DEMO_SCRIPT.md) | Show the app to someone |
| 🧠 [Project decisions](docs/DECISIONS.md) | Understand why it's built this way |

<div align="center">

<br>

**Made with ❤️ to keep your inbox calm.**

If this project helps you, consider giving it a ⭐

</div>
