# Telegram Account Recovery

> **Background:** Read the story behind this tool — [How a 30-Year IT Veteran Got Pwned by a Telegram Phishing Link and Took Their Account Back](https://medium.com/@roman.kulish/how-a-30-year-it-veteran-got-pwned-by-a-telegram-phishing-link-and-took-their-account-back-e193569b35f8)

Automated recovery script for a compromised Telegram account. Connects via QR login, then executes four sequential waves of actions to evict an attacker, lock the account down, collect forensic evidence, and warn your contacts — all in a single run.

---

## What it does

### Wave 1 — Critical
- Cancels any pending 2FA password reset the attacker may have initiated (kills their 7-day takeover window)
- Verifies 2FA is active; re-enables it with your recovery password if the attacker disabled it
- Dumps all active sessions (device, IP, country) to `recovery_dump/sessions.json`

### Wave 2 — Damage Control
- Changes profile name to **HACKED ACCOUNT** and bio to a public warning
- Revokes the public username
- Locks all privacy settings (last seen, phone number, profile photo, calls, forwards, voice messages, etc.) to **Nobody**
- Deletes all profile photos
- Dumps and revokes all Telegram Login web authorizations (third-party sites)
- Clears saved payment credentials and shipping info
- Clears synced contacts and disables frequent-contact tracking
- Sets inactive session auto-termination to **7 days**
- Sets account auto-delete to **30 days** as a failsafe
- Strips admin rights from and leaves all channels/groups where the account is an admin (owned channels are logged for manual handling)
- Attempts to terminate all other active sessions (may be blocked by Telegram's 24 h restriction — re-run the next day if needed)

### Wave 3 — Intel
- Dumps all recent dialogs (since `DIALOG_CUTOFF`) to `recovery_dump/dialogs.json`
- Dumps recent messages from each dialog into `recovery_dump/messages/<id>_<name>.json`

### Wave 4 — Notify
- Sends a **"this account was hacked — do not trust messages"** warning to every contact, with flood-wait handling

All output is written to `recovery_dump/` for forensic review.

---

## Prerequisites

Python 3.8+ and two packages:

```bash
pip install telethon qrcode
```

You also need a **Telegram API ID and API Hash** — obtain them from [my.telegram.org](https://my.telegram.org) under *API development tools*.

---

## Configuration

Edit the constants at the top of `recovery.py` before running:

| Variable | Description |
|---|---|
| `PHONE` | Your phone number in international format, e.g. `+61412345678` |
| `RECOVERY_2FA_PASSWORD` | The 2FA password to verify or restore on the account |
| `RECOVERY_EMAIL` | Recovery email (for reference; not used programmatically) |
| `API_ID` | Integer API ID from my.telegram.org |
| `API_HASH` | String API hash from my.telegram.org |
| `DIALOG_CUTOFF` | `datetime` — messages/dialogs older than this are ignored during the intel dump. Set it to just before the hack date. |

Example:

```python
PHONE = "+61412345678"
RECOVERY_2FA_PASSWORD = "StrongPassword123!"
RECOVERY_EMAIL = "you@example.com"
API_ID = 12345678
API_HASH = "abcdef1234567890abcdef1234567890"
DIALOG_CUTOFF = datetime(2026, 3, 1, tzinfo=timezone.utc)
```

---

## Usage

```bash
python recovery.py
```

On first run you will be prompted to scan a QR code:

1. Open Telegram on your phone
2. Go to **Settings → Devices → Link Desktop Device**
3. Scan the QR code printed in the terminal

If 2FA is active, the script signs in automatically using `RECOVERY_2FA_PASSWORD`.

The session is saved locally (`recovery_session.session`) so subsequent runs skip the QR step.

### If attacker sessions survive Wave 2

Telegram enforces a 24-hour restriction on terminating all sessions after a new login. If the termination step fails, wait 24 hours and run the script again — the existing session will be reused and only the termination will be retried (all other steps are idempotent).

---

## Output files

| File | Contents |
|---|---|
| `recovery_dump/sessions.json` | All active sessions at time of recovery |
| `recovery_dump/web_authorizations.json` | Third-party web logins (if any existed) |
| `recovery_dump/channels.json` | All channels/groups the account belongs to |
| `recovery_dump/dialogs.json` | Recent dialog list since cutoff date |
| `recovery_dump/messages/<id>_<name>.json` | Per-chat message dumps since cutoff date |

---

## Security notes

- **Never commit your filled-in credentials.** Keep `recovery.py` with real values out of version control, or use environment variables / a `.env` file.
- The script does not delete any messages — it is read-only for message history.
- Profile changes (name, bio) and privacy changes are reversible — update them manually after recovery.

---

## License

MIT
