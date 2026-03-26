#!/usr/bin/env python3
"""
Telegram Compromised Account Recovery v3
==========================================

QR login → 2FA auth → lockdown → intel dump → warn contacts

PREREQUISITES:
  pip install telethon qrcode

USAGE:
  python recovery_v3.py
"""

import asyncio
import json
import os
import time
from datetime import datetime, timezone

from telethon import TelegramClient, errors
from telethon.tl.functions.account import (
    DeclinePasswordResetRequest,
    GetAuthorizationsRequest,
    GetPasswordRequest,
    GetWebAuthorizationsRequest,
    ResetWebAuthorizationsRequest,
    SetAccountTTLRequest,
    SetAuthorizationTTLRequest,
    SetPrivacyRequest,
    UpdateProfileRequest,
    UpdateUsernameRequest,
)
from telethon.tl.functions.auth import ResetAuthorizationsRequest
from telethon.tl.functions.channels import EditAdminRequest, LeaveChannelRequest
from telethon.tl.functions.contacts import (
    GetContactsRequest,
    ResetSavedRequest,
    ToggleTopPeersRequest,
)
from telethon.tl.functions.payments import ClearSavedInfoRequest
from telethon.tl.functions.photos import DeletePhotosRequest, GetUserPhotosRequest
from telethon.tl.types import (
    AccountDaysTTL,
    Channel,
    ChatAdminRights,
    InputPhoto,
    InputPrivacyKeyAbout,
    InputPrivacyKeyAddedByPhone,
    InputPrivacyKeyBirthday,
    InputPrivacyKeyChatInvite,
    InputPrivacyKeyForwards,
    InputPrivacyKeyPhoneCall,
    InputPrivacyKeyPhoneNumber,
    InputPrivacyKeyPhoneP2P,
    InputPrivacyKeyProfilePhoto,
    InputPrivacyKeyStatusTimestamp,
    InputPrivacyKeyVoiceMessages,
    InputPrivacyValueAllowAll,
    InputPrivacyValueDisallowAll,
)

# ============================================================
# CONFIGURE BEFORE RUNNING
# ============================================================

# Phone number in the international format: +61xxxxxxxxxxxxx
PHONE = ""

# 2FA password and recovery email
RECOVERY_2FA_PASSWORD = ""
RECOVERY_EMAIL = ""

# Telegram APP ID & HASH
API_ID = 0
API_HASH = ""

# Date when account was hacked
DIALOG_CUTOFF = datetime(2026, 1, 1, tzinfo=timezone.utc)
# ============================================================

SESSION_NAME = "recovery_session"
RECOVERY_2FA_HINT = "recovery script"

OUTPUT_DIR = "recovery_dump"

HACKED_WARNING = (
    "\u26a0\ufe0f MY ACCOUNT HAS BEEN HACKED \u26a0\ufe0f\n\n"
    "Do NOT trust any messages from this account.\n"
    "Do NOT click any links.\n"
    "Do NOT send money or codes.\n\n"
    "This is an automated recovery message from the real account owner."
)


def ensure_output_dir():
    os.makedirs(OUTPUT_DIR, exist_ok=True)


def save_json(filename, data):
    """Save data to JSON in output dir. Overwrites existing."""
    ensure_output_dir()
    path = os.path.join(OUTPUT_DIR, filename)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, default=str)
    return path


def ts(dt):
    """Convert datetime to readable string."""
    if dt is None:
        return None
    if isinstance(dt, (int, float)):
        try:
            dt = datetime.fromtimestamp(dt, tz=timezone.utc)
        except Exception:
            return str(dt)
    try:
        return dt.strftime("%Y-%m-%d %H:%M:%S UTC")
    except Exception:
        return str(dt)


def ensure_utc(dt):
    """Ensure datetime is timezone-aware (UTC). Handles both aware and naive."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def log(msg):
    elapsed = time.monotonic() - _start_time
    print(f"  [{elapsed:6.1f}s] {msg}")


_start_time = time.monotonic()


# ============================================================
# QR LOGIN
# ============================================================


async def qr_login(client):
    """Authenticate via QR code. Returns True on success."""
    try:
        import qrcode
    except ImportError:
        print("  ❌ qrcode library not installed. Run: pip install qrcode")
        return False

    try:
        qr_login_obj = await client.qr_login()

        qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_L)
        qr.add_data(qr_login_obj.url)
        qr.make(fit=True)
        qr.print_ascii(invert=True)

        print()
        print("  SCAN THIS QR CODE from your Telegram app:")
        print("  Settings -> Devices -> Link Desktop Device")
        print()
        print("  Waiting for scan (2 min timeout)...")

        try:
            await asyncio.wait_for(qr_login_obj.wait(), timeout=120)
        except asyncio.TimeoutError:
            log("❌ QR code timed out. Run again.")
            return False

        log("✅ QR scan accepted!")
        return True

    except errors.SessionPasswordNeededError:
        log("2FA required — using recovery password...")
        try:
            await client.sign_in(password=RECOVERY_2FA_PASSWORD)
            log("✅ 2FA accepted!")
            return True
        except Exception as e:
            log(f"❌ 2FA failed: {type(e).__name__}: {e}")
            return False
    except Exception as e:
        log(f"❌ QR login failed: {type(e).__name__}: {e}")
        return False


# ============================================================
# WAVE 1: CRITICAL
# ============================================================


async def cancel_2fa_reset(client):
    """Cancel any pending 2FA password reset."""
    try:
        await client(DeclinePasswordResetRequest())
        log("✅ 2FA reset CANCELLED — attacker's 7-day clock is dead")
        return True
    except Exception as e:
        err = str(e)
        if "RESET_REQUEST_MISSING" in err:
            log("✅ No pending 2FA reset — safe")
            return True
        log(f"⚠️  DeclinePasswordReset: {type(e).__name__}: {e}")
        return False


async def verify_2fa(client):
    """Verify 2FA is active. Re-enable if removed."""
    try:
        pwd = await client(GetPasswordRequest())
        if not pwd.has_password:
            log("❌ 2FA IS NOT SET! Re-enabling...")
            try:
                await client.edit_2fa(
                    current_password=None,
                    new_password=RECOVERY_2FA_PASSWORD,
                    hint=RECOVERY_2FA_HINT,
                )
                log("✅ 2FA re-enabled!")
            except Exception as e2:
                log(f"❌ Failed to set 2FA: {type(e2).__name__}: {e2}")
            return

        log("✅ 2FA is ACTIVE")

        if pwd.pending_reset_date:
            log(f"⚠️  PENDING RESET detected! Date: {ts(pwd.pending_reset_date)}")
            try:
                await client(DeclinePasswordResetRequest())
                log("✅ Pending reset cancelled!")
            except Exception as e2:
                log(f"⚠️  Could not cancel pending reset: {e2}")
        else:
            log("✅ No pending reset")
    except Exception as e:
        log(f"❌ Password check failed: {type(e).__name__}: {e}")


async def dump_sessions(client):
    """Dump all active sessions to file."""
    sessions = []
    try:
        result = await client(GetAuthorizationsRequest())
        for auth in result.authorizations:
            info = {
                "current": auth.current,
                "device": auth.device_model,
                "platform": auth.platform,
                "system": auth.system_version,
                "app": f"{auth.app_name} {auth.app_version}",
                "api_id": auth.api_id,
                "ip": auth.ip,
                "country": auth.country,
                "region": auth.region,
                "created": ts(auth.date_created),
                "active": ts(auth.date_active),
                "official_app": auth.official_app,
                "password_pending": auth.password_pending,
                "hash": auth.hash,
            }
            sessions.append(info)
            marker = " <-- THIS SESSION" if auth.current else " <-- ATTACKER"
            log(
                f"  {auth.device_model} | {auth.platform} | "
                f"IP: {auth.ip} | {auth.country} {auth.region}{marker}"
            )

        path = save_json("sessions.json", sessions)
        log(f"✅ {len(sessions)} sessions saved to {path}")
    except Exception as e:
        log(f"❌ Session dump failed: {type(e).__name__}: {e}")
        if sessions:
            path = save_json("sessions.json", sessions)
            log(f"  Partial data saved: {len(sessions)} session(s) → {path}")


# ============================================================
# WAVE 2: DAMAGE CONTROL
# ============================================================


async def change_profile(client):
    """Change name and bio to hacked warnings."""
    try:
        await client(
            UpdateProfileRequest(
                first_name="HACKED",
                last_name="ACCOUNT",
                about="\u26a0\ufe0f HACKED ACCOUNT \u2014 DO NOT TRUST ANY MESSAGES \u26a0\ufe0f",
            )
        )
        log("✅ Name → HACKED ACCOUNT, bio → warning")
    except Exception as e:
        log(f"❌ Profile update failed: {type(e).__name__}: {e}")


async def revoke_username(client):
    """Remove public username."""
    try:
        await client(UpdateUsernameRequest(username=""))
        log("✅ Username revoked")
    except Exception as e:
        err = str(e)
        if "USERNAME_NOT_MODIFIED" in err:
            log("✅ No username to revoke")
        else:
            log(f"❌ Username revoke failed: {type(e).__name__}: {e}")


async def lockdown_privacy(client):
    """Set all privacy settings to nobody, except bio (allow all)."""
    # Keys to lock down (set to DisallowAll)
    deny_keys = [
        ("Status (last seen)", InputPrivacyKeyStatusTimestamp()),
        ("Phone number", InputPrivacyKeyPhoneNumber()),
        ("Profile photo", InputPrivacyKeyProfilePhoto()),
        ("Forwards", InputPrivacyKeyForwards()),
        ("Calls", InputPrivacyKeyPhoneCall()),
        ("Call P2P", InputPrivacyKeyPhoneP2P()),
        ("Groups/channels invite", InputPrivacyKeyChatInvite()),
        ("Voice messages", InputPrivacyKeyVoiceMessages()),
        ("Added by phone", InputPrivacyKeyAddedByPhone()),
        ("Birthday", InputPrivacyKeyBirthday()),
    ]
    # Bio stays visible
    allow_keys = [
        ("About/bio", InputPrivacyKeyAbout()),
    ]

    for label, key in deny_keys:
        try:
            await client(
                SetPrivacyRequest(
                    key=key,
                    rules=[InputPrivacyValueDisallowAll()],
                )
            )
            log(f"  🔒 {label} → nobody")
        except Exception as e:
            log(f"  ⚠️  {label} failed: {type(e).__name__}: {e}")

    for label, key in allow_keys:
        try:
            await client(
                SetPrivacyRequest(
                    key=key,
                    rules=[InputPrivacyValueAllowAll()],
                )
            )
            log(f"  🔓 {label} → everyone")
        except Exception as e:
            log(f"  ⚠️  {label} failed: {type(e).__name__}: {e}")

    log("✅ Privacy lockdown complete")


async def delete_profile_photos(client):
    """Delete all profile photos."""
    try:
        me = await client.get_me()
        result = await client(
            GetUserPhotosRequest(
                user_id=me,
                offset=0,
                max_id=0,
                limit=100,
            )
        )
        if not result.photos:
            log("✅ No profile photos to delete")
            return
        input_photos = [
            InputPhoto(
                id=p.id, access_hash=p.access_hash, file_reference=p.file_reference
            )
            for p in result.photos
        ]
        # Try batch delete first
        try:
            await client(DeletePhotosRequest(id=input_photos))
            log(f"✅ Deleted {len(input_photos)} profile photo(s)")
        except Exception:
            # Fallback: delete one by one (handles stale file_references)
            deleted = 0
            for photo in input_photos:
                try:
                    await client(DeletePhotosRequest(id=[photo]))
                    deleted += 1
                except Exception:
                    pass
            log(
                f"✅ Deleted {deleted}/{len(input_photos)} photo(s) (one-by-one fallback)"
            )
    except Exception as e:
        log(f"❌ Photo deletion failed: {type(e).__name__}: {e}")


async def kill_web_authorizations(client):
    """Dump and revoke all web authorizations (Telegram Login on websites)."""
    try:
        result = await client(GetWebAuthorizationsRequest())
        if result.authorizations:
            web_auths = []
            for auth in result.authorizations:
                web_auths.append(
                    {
                        "domain": auth.domain,
                        "browser": auth.browser,
                        "platform": auth.platform,
                        "ip": auth.ip,
                        "region": auth.region,
                        "created": ts(auth.date_created),
                        "active": ts(auth.date_active),
                    }
                )
                log(f"  Web auth: {auth.domain} | {auth.browser} | {auth.ip}")
            save_json("web_authorizations.json", web_auths)
            await client(ResetWebAuthorizationsRequest())
            log(f"✅ Revoked {len(result.authorizations)} web authorization(s)")
        else:
            log("✅ No web authorizations to revoke")
    except Exception as e:
        log(f"❌ Web auth revoke failed: {type(e).__name__}: {e}")


async def clear_payments(client):
    """Clear saved payment credentials and shipping info."""
    try:
        await client(ClearSavedInfoRequest(credentials=True, info=True))
        log("✅ Payment credentials and shipping info cleared")
    except Exception as e:
        log(f"❌ Clear payments failed: {type(e).__name__}: {e}")


async def clear_contacts(client):
    """Remove synced contacts from server and disable top peers."""
    try:
        await client(ResetSavedRequest())
        log("✅ Synced contacts cleared from server")
    except Exception as e:
        log(f"❌ Clear synced contacts failed: {type(e).__name__}: {e}")

    try:
        await client(ToggleTopPeersRequest(enabled=False))
        log("✅ Top peers (frequent contacts) disabled")
    except Exception as e:
        log(f"⚠️  Disable top peers failed: {type(e).__name__}: {e}")


async def set_session_ttl(client):
    """Set inactive session auto-terminate to 7 days."""
    try:
        await client(SetAuthorizationTTLRequest(authorization_ttl_days=7))
        log("✅ Session auto-terminate set to 7 days")
    except Exception as e:
        log(f"❌ Session TTL failed: {type(e).__name__}: {e}")


async def set_account_ttl(client):
    """Set account auto-delete to 30 days (insurance)."""
    try:
        await client(SetAccountTTLRequest(ttl=AccountDaysTTL(days=30)))
        log("✅ Account auto-delete set to 30 days")
    except Exception as e:
        log(f"❌ Account TTL failed: {type(e).__name__}: {e}")


async def handle_admin_channels(client):
    """
    Iterate channels/groups. For admin (not owner): strip rights + leave.
    For owner: log for manual handling. Save full list.
    """
    channels_info = []
    stripped = 0
    try:
        dialogs = await client.get_dialogs()
        me = await client.get_me()

        for dialog in dialogs:
            entity = dialog.entity
            if not isinstance(entity, Channel):
                continue

            info = {
                "title": entity.title,
                "id": entity.id,
                "username": getattr(entity, "username", None),
                "creator": entity.creator,
                "has_admin_rights": entity.admin_rights is not None,
                "members": getattr(entity, "participants_count", None),
            }
            channels_info.append(info)

            if entity.creator:
                log(f"  👑 OWNER: {entity.title} — handle manually after recovery")
            elif entity.admin_rights:
                try:
                    await client(
                        EditAdminRequest(
                            channel=entity,
                            user_id=me,
                            admin_rights=ChatAdminRights(),
                            rank="",
                        )
                    )
                    await client(LeaveChannelRequest(channel=entity))
                    log(f"  ✅ Stripped admin + left: {entity.title}")
                    stripped += 1
                except Exception as e:
                    log(
                        f"  ⚠️  Failed to strip/leave {entity.title}: {type(e).__name__}: {e}"
                    )

        path = save_json("channels.json", channels_info)
        log(
            f"✅ {len(channels_info)} channels catalogued, {stripped} admin roles stripped → {path}"
        )
    except Exception as e:
        log(f"❌ Channel handling failed: {type(e).__name__}: {e}")
        if channels_info:
            path = save_json("channels.json", channels_info)
            log(f"  Partial data saved: {len(channels_info)} channel(s) → {path}")


async def try_terminate_sessions(client):
    """Attempt to terminate all other sessions."""
    try:
        await client(ResetAuthorizationsRequest())
        log("✅ ALL OTHER SESSIONS TERMINATED!")
        log("🎉 ATTACKER IS OUT!")
        return True
    except Exception as e:
        log(f"❌ Session termination failed: {type(e).__name__}: {e}")
        log("   Expected — 24h restriction. Run again tomorrow.")
        return False


# ============================================================
# WAVE 3: INTEL
# ============================================================


async def dump_dialogs_and_messages(client):
    """
    Dump dialog list and recent messages since DIALOG_CUTOFF.
    Saves incrementally per dialog so partial results are preserved.
    """
    dialog_list = []
    dialogs = []
    try:
        log("Fetching dialogs...")
        dialogs = await client.get_dialogs()

        for dialog in dialogs:
            if dialog.date and ensure_utc(dialog.date) < DIALOG_CUTOFF:
                break

            entity = dialog.entity
            name = getattr(entity, "title", None) or getattr(
                entity, "first_name", ""
            ) + " " + (getattr(entity, "last_name", "") or "")
            name = name.strip()

            dialog_info = {
                "name": name,
                "id": dialog.id,
                "type": type(entity).__name__,
                "date": ts(dialog.date),
                "unread": dialog.unread_count,
                "username": getattr(entity, "username", None),
            }
            dialog_list.append(dialog_info)

        path = save_json("dialogs.json", dialog_list)
        log(f"✅ {len(dialog_list)} recent dialogs saved to {path}")
    except Exception as e:
        log(f"❌ Dialog list failed: {type(e).__name__}: {e}")
        if dialog_list:
            path = save_json("dialogs.json", dialog_list)
            log(f"  Partial data saved: {len(dialog_list)} dialog(s) → {path}")

    # Dump messages per dialog (separate try so dialog list is always saved first)
    try:
        if not dialogs:
            return

        log("Dumping messages (since March 4)...")
        msg_dir = os.path.join(OUTPUT_DIR, "messages")
        os.makedirs(msg_dir, exist_ok=True)

        for i, dialog in enumerate(dialogs):
            if dialog.date and ensure_utc(dialog.date) < DIALOG_CUTOFF:
                break

            entity = dialog.entity
            name = getattr(entity, "title", None) or getattr(
                entity, "first_name", ""
            ) + " " + (getattr(entity, "last_name", "") or "")
            name = name.strip()

            try:
                messages = []
                async for msg in client.iter_messages(
                    dialog.entity,
                    offset_date=datetime.now(tz=timezone.utc),
                    reverse=False,
                    limit=100,
                ):
                    if msg.date and ensure_utc(msg.date) < DIALOG_CUTOFF:
                        break
                    messages.append(
                        {
                            "id": msg.id,
                            "date": ts(msg.date),
                            "from_id": msg.sender_id,
                            "text": msg.text or "",
                            "media_type": type(msg.media).__name__
                            if msg.media
                            else None,
                        }
                    )

                if messages:
                    safe_name = "".join(
                        c if c.isalnum() or c in " _-" else "_" for c in name
                    )
                    filename = f"{dialog.id}_{safe_name[:50]}.json"
                    filepath = os.path.join(msg_dir, filename)
                    with open(filepath, "w", encoding="utf-8") as f:
                        json.dump(
                            messages, f, indent=2, ensure_ascii=False, default=str
                        )

                if (i + 1) % 10 == 0:
                    log(f"  ... processed {i + 1} dialogs")

            except Exception as e:
                log(f"  ⚠️  Failed to dump {name}: {type(e).__name__}: {e}")
                # Save whatever messages we collected for this dialog
                if messages:
                    safe_name = "".join(
                        c if c.isalnum() or c in " _-" else "_" for c in name
                    )
                    filename = f"{dialog.id}_{safe_name[:50]}_partial.json"
                    filepath = os.path.join(msg_dir, filename)
                    try:
                        with open(filepath, "w", encoding="utf-8") as f:
                            json.dump(
                                messages, f, indent=2, ensure_ascii=False, default=str
                            )
                        log(
                            f"    Saved {len(messages)} partial message(s) → {filename}"
                        )
                    except Exception:
                        pass

        log(f"✅ Message dump complete → {msg_dir}/")
    except Exception as e:
        log(f"❌ Message dump failed: {type(e).__name__}: {e}")


# ============================================================
# WAVE 4: WARN CONTACTS
# ============================================================


async def warn_contacts(client):
    """Send hacked warning to all contacts, rate-limited."""
    try:
        result = await client(GetContactsRequest(hash=0))
        contacts = result.users
        if not contacts:
            log("No contacts to warn")
            return

        log(f"Sending warnings to {len(contacts)} contacts...")
        sent = 0
        failed = 0

        for user in contacts:
            try:
                await client.send_message(user.id, HACKED_WARNING)
                sent += 1
                await asyncio.sleep(0.5)  # Rate limit protection
            except errors.FloodWaitError as e:
                log(f"  ⚠️  Flood wait {e.seconds}s — sent {sent} so far, pausing...")
                await asyncio.sleep(min(e.seconds, 30))
            except Exception:
                failed += 1

        log(f"✅ Warned {sent}/{len(contacts)} contacts ({failed} failed)")
    except Exception as e:
        log(f"❌ Contact warning failed: {type(e).__name__}: {e}")


# ============================================================
# MAIN
# ============================================================


async def main():
    print()
    print("=" * 60)
    print("  TELEGRAM ACCOUNT RECOVERY v3")
    print("=" * 60)
    print()
    print(f"  Phone:  {PHONE}")
    print(f"  2FA:    {RECOVERY_2FA_PASSWORD}")
    print(f"  Output: {OUTPUT_DIR}/")
    print()

    client = TelegramClient(
        SESSION_NAME,
        API_ID,
        API_HASH,
        device_model="Recovery",
        system_version="Linux",
        app_version="1.0",
    )
    await client.connect()

    # --- AUTHENTICATE ---
    if await client.is_user_authorized():
        log("✅ Existing session still alive")
    else:
        log("Authenticating via QR code...")
        print()
        if not await qr_login(client):
            await client.disconnect()
            return
        print()

    me = await client.get_me()
    log(f"✅ Logged in as: {me.first_name} {me.last_name or ''} (ID: {me.id})")

    # --- WAVE 1: CRITICAL ---
    print()
    print("  ── WAVE 1: CRITICAL ──")
    await cancel_2fa_reset(client)
    await verify_2fa(client)
    await dump_sessions(client)

    # --- WAVE 2: DAMAGE CONTROL ---
    print()
    print("  ── WAVE 2: DAMAGE CONTROL ──")
    await change_profile(client)
    await revoke_username(client)
    await lockdown_privacy(client)
    await delete_profile_photos(client)
    await kill_web_authorizations(client)
    await clear_payments(client)
    await clear_contacts(client)
    await set_session_ttl(client)
    await set_account_ttl(client)
    await handle_admin_channels(client)
    await try_terminate_sessions(client)

    # --- WAVE 3: INTEL ---
    print()
    print("  ── WAVE 3: INTEL ──")
    await dump_dialogs_and_messages(client)

    # --- WAVE 4: WARN CONTACTS ---
    print()
    print("  ── WAVE 4: NOTIFY ──")
    await warn_contacts(client)

    # --- SUMMARY ---
    elapsed = time.monotonic() - _start_time
    print()
    print("  " + "=" * 50)
    print(f"  RECOVERY COMPLETE — {elapsed:.1f}s total")
    print("  " + "=" * 50)
    print()
    print(f"  Evidence saved to: {OUTPUT_DIR}/")
    print(f"  2FA password: {RECOVERY_2FA_PASSWORD}")
    print()
    print("  If attacker session is still active:")
    print("    Wait 24h, run this script again to terminate.")
    print()

    await client.disconnect()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n  Interrupted. Partial results saved.")
