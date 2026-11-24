#!/usr/bin/env python3


#If you change the credit, fuck your mother



"""▶~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~☯
DEVELOPER: @RBX404
WhatsApp: https://whatsapp.com/channel/0029Vb87t5X4o7qJuL6cYQ3N
telegram: https://t.me/BlackoutZoneRBX404
telegram: https://t.me/SkillShareBDCommunity

▶~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~☯
"""
"""RBX404 PREMIUM TEMP MAIL BOT - Telegram bot + Web Admin Panel (single file).

Run:  pip install -r requirements.txt && python main.py
All configuration comes from environment variables (see .env.example). This file holds no secrets.
"""
import os


def _load_dotenv(path):
    """Tiny .env reader (no dependency). Real environment variables always win."""
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k, v = k.strip(), v.split(" #")[0].strip().strip('"').strip("'")
                if k and k not in os.environ:
                    os.environ[k] = v
    except OSError:
        pass


_load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))


def _env(name, default=""):
    return os.environ.get(name, default).strip()


def _env_int(name, default):
    try:
        return int(_env(name, str(default)))
    except ValueError:
        return default


def _env_bool(name, default=False):
    v = _env(name, "1" if default else "0").lower()
    return v in ("1", "true", "yes", "on")


# =====================================================================================
#  CONFIG  -  environment variables (defaults shown). Everything below the first-run
#  values can also be changed later in the web panel.
# =====================================================================================
BOT_TOKEN = _env("BOT_TOKEN")                                   # REQUIRED, from @BotFather
ADMIN_IDS = [int(x) for x in _env("ADMIN_IDS").replace(";", ",").split(",") if x.strip().isdigit()]
                                   # Telegram user IDs; used ONLY to seed the admin list on first run

DB_PATH = _env("DB_PATH", "rbx404_tempmail.db")                 # point to a persistent disk on ephemeral hosts

BOT_NAME = _env("BOT_NAME", "RBX404 Temp Mail")
SUPPORT_USERNAME = _env("SUPPORT_USERNAME", "RBX404")           # without @
WELCOME_MESSAGE = ("Disposable inboxes in one tap.\nHi {name}, generate an address, use it anywhere, "
                   "and read incoming mail right here.")

# Media shown on each screen (first run only; manage afterwards in the panel). Empty = text only.
# Direct URLs ending in .jpg .jpeg .png .gif .mp4. Telegram limits by URL: photos 5 MB, gif/video 20 MB.
MEDIA = {
    "welcome": "https://res.cloudinary.com/gxskipes/image/upload/v1795331092/Gemini_Generated_Gif_mibd1dmibd1dmibd.gif",
    "generate": "https://res.cloudinary.com/gxskipes/image/upload/v1795333087/Gemini_Generated_Gif_23uxn723uxn723ux.gif",
    "inbox": "https://res.cloudinary.com/gxskipes/image/upload/v1795333316/Gemini_Generated_Gif_42wny542wny542wn.gif",
    "detail": "https://res.cloudinary.com/gxskipes/image/upload/v1795333578/Gemini_Generated_Gif_8bckwl8bckwl8bck.gif",
    "help": "https://res.cloudinary.com/gxskipes/image/upload/v1795333764/Gemini_Generated_Gif_4qsmy54qsmy54qsm.gif",
    "loading": "https://res.cloudinary.com/gxskipes/image/upload/v1795334221/Gemini_Generated_Gif_5sfzov5sfzov5sfz.gif",
    "error": "",
    "success": "https://res.cloudinary.com/gxskipes/image/upload/v1795334817/Gemini_Generated_Gif_2vhjtz2vhjtz2vhj.gif",
    "account": "",
    "join": "https://res.cloudinary.com/gxskipes/image/upload/v1795336776/Gemini_Generated_Gif_roy3meroy3meroy3.gif",
}

# Providers created on the first run only (manage them in the panel afterwards).
# api_type "mailtm"      -> documented mail.tm REST API (https://docs.mail.tm); mail.gw exposes the same API.
# api_type "onesecmail"  -> 1secmail API adapter (not enabled by default).
DEFAULT_PROVIDERS = [
    {"name": "mail.tm", "api_type": "mailtm", "base_url": "https://api.mail.tm", "priority": 1},
    {"name": "mail.gw", "api_type": "mailtm", "base_url": "https://api.mail.gw", "priority": 2},
]

MAX_EMAILS_PER_USER = _env_int("MAX_EMAILS_PER_USER", 3)        # simultaneously active addresses per user
EMAIL_TTL_MINUTES = _env_int("EMAIL_TTL_MINUTES", 60)           # 0 = never expires
MAX_MESSAGE_CHARS = _env_int("MAX_MESSAGE_CHARS", 2500)         # max characters of an email body shown (<= 3000)
HTTP_TIMEOUT = _env_int("HTTP_TIMEOUT", 15)                     # seconds, every provider request
HEALTH_INTERVAL = _env_int("HEALTH_INTERVAL", 60)               # seconds between background provider checks
PROVIDER_FAIL_THRESHOLD = _env_int("PROVIDER_FAIL_THRESHOLD", 3)  # consecutive failures before a provider is skipped
PROVIDER_COOLDOWN = _env_int("PROVIDER_COOLDOWN", 120)          # seconds a failed provider is skipped
# =====================================================================================

import asyncio
import hashlib
import hmac
import html
import json
import logging
import random
import re
import secrets
import signal
import sqlite3
import string
import sys
import tempfile
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import quote, urlparse

import aiohttp
import aiosqlite
from aiogram import Bot, Dispatcher, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import (TelegramAPIError, TelegramBadRequest, TelegramForbiddenError,
                                TelegramRetryAfter)
from aiogram.filters import Command
from aiogram.types import (BufferedInputFile, CallbackQuery, CopyTextButton, ErrorEvent, FSInputFile,
                           InlineKeyboardButton, InlineKeyboardMarkup, Message)

log = logging.getLogger("rbx404")
START_TIME = time.time()

# ------------------------------------------------------------------ helpers
def now() -> int:
    return int(time.time())


def esc(s) -> str:
    return html.escape("" if s is None else str(s), quote=True)


def path_is_file(p) -> bool:
    return os.path.isfile(p)


def fmt_ts(ts) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d %H:%M UTC") if ts else "-"


def to_int(v, lo, hi):
    try:
        n = int(str(v).strip())
    except (ValueError, TypeError):
        return None
    return n if lo <= n <= hi else None


def loads_obj(s):
    try:
        d = json.loads(s or "{}")
        return d if isinstance(d, dict) else {}
    except (ValueError, TypeError):
        return {}


MEDIA_LABELS = {
    "welcome": "Welcome / main menu", "generate": "New email created", "inbox": "Inbox",
    "detail": "Email details", "help": "Help", "loading": "Loading", "error": "Error",
    "success": "Success", "account": "Account", "join": "Force join",
}
MEDIA_EXT = {".jpg": "photo", ".jpeg": "photo", ".png": "photo", ".gif": "animation", ".mp4": "video"}


def media_kind(url: str):
    try:
        path = urlparse(url).path.lower()
    except ValueError:
        return None
    for ext, kind in MEDIA_EXT.items():
        if path.endswith(ext):
            return kind
    return None


def media_url_ok(url: str) -> bool:
    try:
        u = urlparse(url)
    except ValueError:
        return False
    return u.scheme in ("http", "https") and bool(u.netloc) and len(url) <= 1000 and media_kind(url) is not None


# ------------------------------------------------------------------ database
SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY, username TEXT, first_name TEXT, banned INTEGER NOT NULL DEFAULT 0,
  joined_at INTEGER NOT NULL, last_seen INTEGER NOT NULL, emails_created INTEGER NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS ix_users_seen ON users(last_seen);
CREATE TABLE IF NOT EXISTS providers(
  id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE, api_type TEXT NOT NULL,
  base_url TEXT NOT NULL, api_key TEXT NOT NULL DEFAULT '', headers TEXT NOT NULL DEFAULT '{}',
  extra TEXT NOT NULL DEFAULT '{}', enabled INTEGER NOT NULL DEFAULT 1, priority INTEGER NOT NULL DEFAULT 100,
  status TEXT NOT NULL DEFAULT 'unknown', fail_count INTEGER NOT NULL DEFAULT 0,
  down_until INTEGER NOT NULL DEFAULT 0, last_check INTEGER NOT NULL DEFAULT 0, last_error TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS generated_emails(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  provider_id INTEGER REFERENCES providers(id) ON DELETE SET NULL,
  address TEXT NOT NULL, secret TEXT NOT NULL DEFAULT '', created_at INTEGER NOT NULL,
  expires_at INTEGER NOT NULL DEFAULT 0, active INTEGER NOT NULL DEFAULT 1, msg_count INTEGER NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS ix_ge_user ON generated_emails(user_id, active);
CREATE INDEX IF NOT EXISTS ix_ge_exp ON generated_emails(active, expires_at);
CREATE TABLE IF NOT EXISTS force_join(
  id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, kind TEXT NOT NULL DEFAULT 'channel',
  chat_id TEXT NOT NULL, link TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS media_settings(
  key TEXT PRIMARY KEY, url TEXT NOT NULL DEFAULT '', updated_at INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS bot_settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS admins(
  id INTEGER PRIMARY KEY AUTOINCREMENT, tg_id INTEGER UNIQUE, username TEXT UNIQUE,
  password_hash TEXT, created_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS user_activity(
  id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  action TEXT NOT NULL, detail TEXT NOT NULL DEFAULT '', created_at INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS ix_ua_user ON user_activity(user_id, created_at);
"""


def file_backup(src_path: str, dest_path: str) -> None:
    """Consistent copy of a live SQLite database (works with WAL). Blocking: call via asyncio.to_thread."""
    src = sqlite3.connect(src_path)
    try:
        dst = sqlite3.connect(dest_path)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()


async def _has_col(conn, table, col) -> bool:
    cur = await conn.execute(f"PRAGMA table_info({table})")
    rows = await cur.fetchall()
    await cur.close()
    return any(r[1] == col for r in rows)


async def mig_2(conn):
    """Force every existing panel account to choose a new password at its next login."""
    if not await _has_col(conn, "admins", "must_change"):
        await conn.execute("ALTER TABLE admins ADD COLUMN must_change INTEGER NOT NULL DEFAULT 0")
    await conn.execute("UPDATE admins SET must_change=1 WHERE password_hash IS NOT NULL")


# (version, function). Version 1 is the original schema in SCHEMA (CREATE ... IF NOT EXISTS), so databases made by
# earlier releases are simply "version 1". Each migration runs in one transaction and is recorded once applied.
async def mig_3(conn):
    """Admin audit log (bot admin panel) and per-screen media enable/disable."""
    await conn.execute("CREATE TABLE IF NOT EXISTS admin_audit(id INTEGER PRIMARY KEY AUTOINCREMENT, admin_id INTEGER NOT NULL, "
                       "action TEXT NOT NULL, detail TEXT NOT NULL DEFAULT '', created_at INTEGER NOT NULL)")
    await conn.execute("CREATE INDEX IF NOT EXISTS ix_audit_time ON admin_audit(created_at)")
    if not await _has_col(conn, "media_settings", "enabled"):
        await conn.execute("ALTER TABLE media_settings ADD COLUMN enabled INTEGER NOT NULL DEFAULT 1")


MIGRATIONS = [(2, mig_2), (3, mig_3)]


class DB:
    conn: aiosqlite.Connection

    async def start(self, path):
        self.path = path
        self.conn = await aiosqlite.connect(path)
        self.conn.row_factory = aiosqlite.Row
        await self.conn.execute("PRAGMA journal_mode=WAL")
        await self.conn.execute("PRAGMA foreign_keys=ON")
        await self.conn.execute("PRAGMA busy_timeout=5000")
        await self.conn.executescript(SCHEMA)
        await self.conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations("
                                "version INTEGER PRIMARY KEY, applied_at INTEGER NOT NULL)")
        await self.conn.commit()
        await self.migrate()

    async def migrate(self):
        done = {r[0] for r in await (await self.conn.execute("SELECT version FROM schema_migrations")).fetchall()}
        pending = [(v, fn) for v, fn in MIGRATIONS if v not in done]
        if not pending:
            return
        has_data = (await (await self.conn.execute("SELECT COUNT(*) FROM users")).fetchone())[0] > 0 or \
                   (await (await self.conn.execute("SELECT COUNT(*) FROM admins")).fetchone())[0] > 0
        if has_data and path_is_file(self.path):
            bak = f"{self.path}.pre-v{pending[0][0]}.bak"
            await asyncio.to_thread(file_backup, self.path, bak)
            log.info("database backup before migration: %s", bak)
        for version, fn in pending:
            try:
                await self.conn.execute("BEGIN IMMEDIATE")
                await fn(self.conn)
                await self.conn.execute("INSERT INTO schema_migrations(version,applied_at) VALUES(?,?)", (version, now()))
                await self.conn.commit()
                log.info("applied database migration %s", version)
            except Exception:
                await self.conn.rollback()
                log.exception("database migration %s failed and was rolled back", version)
                raise

    async def all(self, sql, args=()):
        cur = await self.conn.execute(sql, args)
        rows = await cur.fetchall()
        await cur.close()
        return [dict(r) for r in rows]

    async def one(self, sql, args=()):
        rows = await self.all(sql, args)
        return rows[0] if rows else None

    async def run(self, sql, args=()):
        cur = await self.conn.execute(sql, args)
        await self.conn.commit()
        return cur.lastrowid

    async def close(self):
        await self.conn.close()


db = DB()
SETTINGS: dict = {}
ADMIN_SET: set = set()
SETTING_DEFAULTS = {
    "bot_name": BOT_NAME, "welcome_message": WELCOME_MESSAGE, "support_username": SUPPORT_USERNAME,
    "maintenance": "0", "maintenance_message": "Maintenance in progress. Please come back soon.",
    "max_emails_per_user": str(MAX_EMAILS_PER_USER), "email_ttl_minutes": str(EMAIL_TTL_MINUTES),
    "max_message_chars": str(MAX_MESSAGE_CHARS),
    "health_interval": str(HEALTH_INTERVAL), "provider_fail_threshold": str(PROVIDER_FAIL_THRESHOLD),
    "provider_cooldown": str(PROVIDER_COOLDOWN), "http_timeout": str(HTTP_TIMEOUT),
}
# key -> (kind, min, max, label): drives validation and the Settings screen of the admin panel
SETTING_META = {
    "bot_name": ("text", 1, 40, "Bot name"),
    "welcome_message": ("text", 1, 800, "Welcome message ({name} = first name)"),
    "support_username": ("user", 0, 32, "Support username"),
    "maintenance_message": ("text", 1, 300, "Maintenance message"),
    "max_emails_per_user": ("int", 1, 50, "Max active emails per user"),
    "email_ttl_minutes": ("int", 0, 100000, "Email lifetime in minutes (0 = never)"),
    "max_message_chars": ("int", 200, 3000, "Max message characters shown"),
    "health_interval": ("int", 15, 3600, "Provider health-check interval (seconds)"),
    "provider_fail_threshold": ("int", 1, 50, "Provider failure threshold"),
    "provider_cooldown": ("int", 10, 86400, "Provider cooldown (seconds)"),
    "http_timeout": ("int", 3, 60, "HTTP timeout (seconds)"),
}


def S(key):
    return SETTINGS.get(key, SETTING_DEFAULTS.get(key, ""))


def si(key) -> int:
    """Integer setting, clamped to its allowed range; falls back to the configured default."""
    _, lo, hi, _ = SETTING_META[key]
    n = to_int(S(key), lo, hi)
    return n if n is not None else int(SETTING_DEFAULTS[key])


async def set_setting(key, value):
    await db.run("INSERT INTO bot_settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                 (key, str(value)))
    SETTINGS[key] = str(value)


async def load_admins():
    ADMIN_SET.clear()
    ADMIN_SET.update(r["tg_id"] for r in await db.all("SELECT tg_id FROM admins WHERE tg_id IS NOT NULL"))


def hash_pw(pw: str) -> str:
    salt = secrets.token_bytes(16)
    h = hashlib.scrypt(pw.encode(), salt=salt, n=2 ** 14, r=8, p=1, dklen=32)
    return f"scrypt${salt.hex()}${h.hex()}"


def check_pw(pw: str, stored: str) -> bool:
    try:
        _, salt, h = stored.split("$")
        calc = hashlib.scrypt(pw.encode(), salt=bytes.fromhex(salt), n=2 ** 14, r=8, p=1, dklen=32)
        return hmac.compare_digest(calc.hex(), h)
    except (ValueError, TypeError):
        return False




async def init_data():
    for k, v in SETTING_DEFAULTS.items():
        await db.run("INSERT OR IGNORE INTO bot_settings(key,value) VALUES(?,?)", (k, v))
    SETTINGS.update({r["key"]: r["value"] for r in await db.all("SELECT key,value FROM bot_settings")})
    for k in MEDIA_LABELS:
        url = MEDIA.get(k, "")
        await db.run("INSERT OR IGNORE INTO media_settings(key,url,updated_at) VALUES(?,?,?)",
                     (k, url if (not url or media_url_ok(url)) else "", now()))
    if not await db.one("SELECT id FROM providers LIMIT 1"):
        for p in DEFAULT_PROVIDERS:
            await db.run("INSERT OR IGNORE INTO providers(name,api_type,base_url,priority) VALUES(?,?,?,?)",
                         (p["name"], p["api_type"], p["base_url"], p.get("priority", 100)))
    if not await db.one("SELECT id FROM admins WHERE tg_id IS NOT NULL LIMIT 1"):
        for i in ADMIN_IDS:
            await db.run("INSERT OR IGNORE INTO admins(tg_id,created_at) VALUES(?,?)", (int(i), now()))
    await load_admins()


async def log_act(uid, action, detail=""):
    try:
        await db.run("INSERT INTO user_activity(user_id,action,detail,created_at) VALUES(?,?,?,?)",
                     (uid, action, detail[:200], now()))
    except aiosqlite.Error:
        log.warning("activity log failed")


# ------------------------------------------------------------------ provider adapters
class ProviderError(Exception):
    def __init__(self, msg, kind="unavailable"):
        super().__init__(msg)
        self.kind = kind


MAILTM_TOKENS: dict = {}


def _members(d):
    if isinstance(d, dict):
        return d.get("hydra:member") or d.get("member") or []
    return d if isinstance(d, list) else []


def _who(name, addr):
    name, addr = (name or "").strip(), (addr or "").strip()
    return f"{name} <{addr}>" if name and addr else (addr or name or "unknown")


def _rand_local(n=10):
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=n))


class Adapter:
    def __init__(self, row, http):
        self.row, self.http = row, http
        self.base = row["base_url"].rstrip("/")
        self.extra = loads_obj(row["extra"])
        self.hdrs = {str(k): str(v) for k, v in loads_obj(row["headers"]).items()}
        if row["api_key"]:
            self.hdrs[str(self.extra.get("key_header", "X-API-Key"))] = row["api_key"]

    async def req(self, method, path, *, body=None, params=None, headers=None, ok=(200,)):
        h = {"Accept": "application/json", **self.hdrs, **(headers or {})}
        try:
            async with self.http.request(method, self.base + path, json=body, params=params,
                                         headers=h, allow_redirects=False,
                                         timeout=aiohttp.ClientTimeout(total=si("http_timeout"))) as r:
                if r.status == 404:
                    raise ProviderError("HTTP 404", "notfound")
                if r.status not in ok:
                    raise ProviderError(f"HTTP {r.status}")
                if r.status == 204:
                    return None
                try:
                    return await r.json(content_type=None)
                except ValueError:
                    raise ProviderError("invalid JSON response")
        except asyncio.TimeoutError:
            raise ProviderError("timeout", "timeout")
        except aiohttp.ClientError as ex:
            raise ProviderError(ex.__class__.__name__)

    # interface -------------------------------------------------------------
    async def health(self): raise NotImplementedError
    async def create(self): raise NotImplementedError          # -> (address, secret_json)
    async def list_messages(self, address, secret): raise NotImplementedError
    async def read_message(self, address, secret, mid): raise NotImplementedError
    async def delete(self, address, secret): return None


class MailTm(Adapter):
    """Documented mail.tm API (also served by mail.gw): /domains /accounts /token /messages."""

    async def health(self):
        await self.req("GET", "/domains")

    async def create(self):
        doms = [d for d in _members(await self.req("GET", "/domains"))
                if d.get("isActive", True) and not d.get("isPrivate", False) and d.get("domain")]
        want = self.extra.get("domain")
        if want:
            doms = [d for d in doms if d["domain"] == want]
        if not doms:
            raise ProviderError("no active domain")
        addr = f"{_rand_local()}@{random.choice(doms)['domain']}"
        pw = secrets.token_urlsafe(14)
        acc = await self.req("POST", "/accounts", body={"address": addr, "password": pw}, ok=(200, 201)) or {}
        return addr, json.dumps({"pw": pw, "id": acc.get("id")})

    async def _token(self, address, sec, force=False):
        k = (self.base, address)
        if not force and k in MAILTM_TOKENS:
            return MAILTM_TOKENS[k]
        d = await self.req("POST", "/token", body={"address": address, "password": sec["pw"]}) or {}
        if not d.get("token"):
            raise ProviderError("no token")
        if len(MAILTM_TOKENS) > 5000:
            MAILTM_TOKENS.clear()
        MAILTM_TOKENS[k] = d["token"]
        return d["token"]

    async def _authed(self, method, path, address, secret, **kw):
        sec = loads_obj(secret)
        if "pw" not in sec:
            raise ProviderError("missing credentials", "invalid")
        for attempt in (0, 1):
            tok = await self._token(address, sec, force=attempt == 1)
            try:
                return await self.req(method, path, headers={"Authorization": f"Bearer {tok}"}, **kw)
            except ProviderError as ex:
                if attempt == 0 and "401" in str(ex):
                    continue
                raise

    async def list_messages(self, address, secret):
        d = await self._authed("GET", "/messages", address, secret, params={"page": 1})
        out = []
        for m in _members(d):
            f = m.get("from") or {}
            out.append({"id": str(m.get("id")), "from": _who(f.get("name"), f.get("address")),
                        "subject": m.get("subject") or "", "date": m.get("createdAt") or ""})
        return out

    async def read_message(self, address, secret, mid):
        d = await self._authed("GET", f"/messages/{quote(mid, safe='')}", address, secret) or {}
        f = d.get("from") or {}
        h = d.get("html")
        return {"from": _who(f.get("name"), f.get("address")), "subject": d.get("subject") or "",
                "date": d.get("createdAt") or "", "text": d.get("text") or "",
                "html": "".join(h) if isinstance(h, list) else (h or "")}

    async def delete(self, address, secret):
        sec = loads_obj(secret)
        MAILTM_TOKENS.pop((self.base, address), None)
        if sec.get("id"):
            await self._authed("DELETE", f"/accounts/{quote(str(sec['id']), safe='')}", address, secret, ok=(200, 204))


class OneSecMail(Adapter):
    """Documented 1secmail API: ?action=genRandomMailbox | getMessages | readMessage | getDomainList."""

    async def api(self, **params):
        return await self.req("GET", "/", params=params)

    async def health(self):
        await self.api(action="getDomainList")

    async def create(self):
        want = self.extra.get("domain")
        if want:
            addr = f"{_rand_local()}@{want}"
        else:
            r = await self.api(action="genRandomMailbox", count=1)
            if not (isinstance(r, list) and r and "@" in str(r[0])):
                raise ProviderError("unexpected response")
            addr = str(r[0])
        return addr, "{}"

    async def list_messages(self, address, secret):
        login, _, dom = address.partition("@")
        r = await self.api(action="getMessages", login=login, domain=dom)
        out = [{"id": str(m.get("id")), "from": m.get("from") or "unknown", "subject": m.get("subject") or "",
                "date": m.get("date") or ""} for m in (r if isinstance(r, list) else [])]
        out.sort(key=lambda m: int(m["id"]) if m["id"].isdigit() else 0, reverse=True)
        return out

    async def read_message(self, address, secret, mid):
        login, _, dom = address.partition("@")
        d = await self.api(action="readMessage", login=login, domain=dom, id=mid)
        if not isinstance(d, dict):
            raise ProviderError("unexpected response")
        return {"from": d.get("from") or "unknown", "subject": d.get("subject") or "", "date": d.get("date") or "",
                "text": d.get("textBody") or "", "html": d.get("htmlBody") or d.get("body") or ""}


ADAPTERS = {"mailtm": MailTm, "onesecmail": OneSecMail}


class Providers:
    http: aiohttp.ClientSession

    def adapter(self, row):
        cls = ADAPTERS.get(row["api_type"])
        if not cls:
            raise ProviderError("unknown api type", "invalid")
        return cls(row, self.http)

    async def adapter_for(self, email_row):
        row = await db.one("SELECT * FROM providers WHERE id=?", (email_row["provider_id"],)) \
            if email_row["provider_id"] else None
        if not row:
            raise ProviderError("provider removed", "invalid")
        return self.adapter(row)

    async def ok(self, pid):
        await db.run("UPDATE providers SET status='up', fail_count=0, down_until=0, last_error='', last_check=? WHERE id=?",
                     (now(), pid))

    async def fail(self, pid, err):
        thr, cool = si("provider_fail_threshold"), si("provider_cooldown")
        await db.run(
            "UPDATE providers SET fail_count=fail_count+1, last_check=?, last_error=?, "
            "status=CASE WHEN fail_count+1>=? THEN 'down' ELSE 'degraded' END, "
            "down_until=CASE WHEN fail_count+1>=? THEN ? ELSE 0 END WHERE id=?",
            (now(), str(err)[:120], thr, thr, now() + cool, pid))

    async def create_mailbox(self):
        rows = await db.all("SELECT * FROM providers WHERE enabled=1 AND down_until<=? ORDER BY priority, id", (now(),))
        last = ProviderError("no provider available")
        for row in rows:
            try:
                addr, secret = await self.adapter(row).create()
                await self.ok(row["id"])
                return row, addr, secret
            except ProviderError as ex:
                last = ex
                await self.fail(row["id"], ex)
                log.warning("provider %s failed on create: %s", row["name"], ex)
        raise last

    async def check(self, row):
        try:
            await self.adapter(row).health()
            await self.ok(row["id"])
            return True, "OK"
        except ProviderError as ex:
            await self.fail(row["id"], ex)
            return False, str(ex)

    async def health_loop(self):
        while True:
            try:
                await asyncio.sleep(si("health_interval"))
                rows = await db.all("SELECT * FROM providers WHERE enabled=1")
                await asyncio.gather(*(self.check(r) for r in rows))
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("health loop error")


prov = Providers()
bot: Bot = None  # type: ignore

# ------------------------------------------------------------------ safe email rendering
class _Strip(HTMLParser):
    BLOCK = {"br", "p", "div", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6", "table", "blockquote"}
    SKIP = {"script", "style", "head", "title"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1
        elif tag in self.BLOCK:
            self.out.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP:
            self.skip = max(0, self.skip - 1)
        elif tag in self.BLOCK:
            self.out.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.out.append(data)


def html_to_text(src: str) -> str:
    p = _Strip()
    try:
        p.feed(src)
        p.close()
        t = "".join(p.out)
    except Exception:
        t = re.sub(r"<[^>]+>", "", src)
    t = re.sub(r"[ \t\r\f\v]+", " ", t)
    return re.sub(r"\n\s*\n+", "\n\n", t).strip()


def fmt_mail_date(s: str) -> str:
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    except (ValueError, AttributeError):
        return s or "-"


# ------------------------------------------------------------------ telegram UI
ERR = {
    "unavailable": "⚠️ <b>Provider unavailable</b>\nAll mail providers are busy right now. Please try again shortly.",
    "timeout": "⏱ <b>API timeout</b>\nThe mail provider took too long to answer. Please try again.",
    "inbox": "📭 <b>Inbox unavailable</b>\nThis inbox could not be loaded right now. Try refreshing in a moment.",
    "expired": "⌛ <b>Email expired</b>\nThis address has expired. Create a new one to keep receiving mail.",
    "invalid": "❌ <b>Invalid email</b>\nThis address is no longer available.",
    "db": "💾 <b>Database error</b>\nA temporary problem occurred. Please try again.",
    "banned": "🚫 <b>Access denied</b>\nYour account is not allowed to use this bot.",
    "limit": "📦 <b>Limit reached</b>\nYou already have the maximum number of active addresses ({n}). Delete one or wait for it to expire.",
    "generic": "⚠️ <b>Something went wrong</b>\nPlease try again. If it keeps happening, contact support.",
    "tg": "📡 <b>Telegram error</b>\nCould not complete that action. Please try again.",
    "media": "🖼 <b>Media unavailable</b>\nThe media could not be loaded; showing text only.",
}


def head(title: str) -> str:
    return f"🟥 <b>RBX404</b> · <b>{title}</b>\n━━━━━━━━━━━━━━━━\n"


def btn(text, data=None, url=None, copy=None):
    if copy is not None:
        return InlineKeyboardButton(text=text, copy_text=CopyTextButton(text=copy))
    return InlineKeyboardButton(text=text, callback_data=data, url=url)


def kb(*rows):
    return InlineKeyboardMarkup(inline_keyboard=[list(r) for r in rows])


MENU = btn("🏠 Menu", "home")
FILE_IDS: dict = {}
BAD_MEDIA: dict = {}


async def media_url(key):
    r = await db.one("SELECT url, enabled FROM media_settings WHERE key=?", (key,))
    return r["url"] if r and r["enabled"] else ""


async def send_with_media(chat_id, url, text, markup, _retry=True):
    kind = media_kind(url)
    if not kind or BAD_MEDIA.get(url, 0) > time.time() or len(text) > 1024:
        return None
    cached = url in FILE_IDS
    src = FILE_IDS.get(url, url)
    try:
        if kind == "photo":
            m = await bot.send_photo(chat_id, src, caption=text, reply_markup=markup)
            fid = m.photo[-1].file_id
        elif kind == "animation":
            m = await bot.send_animation(chat_id, src, caption=text, reply_markup=markup)
            fid = m.animation.file_id
        else:
            m = await bot.send_video(chat_id, src, caption=text, reply_markup=markup, supports_streaming=True)
            fid = m.video.file_id
        FILE_IDS[url] = fid
        return m
    except TelegramBadRequest as ex:
        if cached:
            FILE_IDS.pop(url, None)
            if _retry:
                return await send_with_media(chat_id, url, text, markup, False)
        BAD_MEDIA[url] = time.time() + 600
        log.warning("media rejected (%s): %s", kind, str(ex)[:80])
    except (TelegramForbiddenError, TelegramRetryAfter):
        raise
    except TelegramAPIError as ex:
        log.warning("media send failed: %s", ex.__class__.__name__)
    return None


async def _drop(msg):
    if isinstance(msg, Message):
        try:
            await msg.delete()
        except TelegramAPIError:
            pass


async def screen(ev, key, text, markup=None, replace=None):
    """Show a screen: media (if configured and valid) with text caption, else text-only. Returns the sent Message."""
    chat_id = ev.from_user.id
    old = replace if replace is not None else (ev.message if isinstance(ev, CallbackQuery) else None)
    if not isinstance(old, Message):
        old = None
    if len(text) > 4096:
        text = text[:4090] + "…"
    url = await media_url(key) if key else ""
    if url:
        m = await send_with_media(chat_id, url, text, markup)
        if m:
            await _drop(old)
            return m
    if old is not None and not (old.photo or old.video or old.animation or old.document):
        try:
            res = await old.edit_text(text, reply_markup=markup)
            return res if isinstance(res, Message) else old
        except TelegramBadRequest as ex:
            if "not modified" in str(ex).lower():
                return old
    m = await bot.send_message(chat_id, text, reply_markup=markup)
    await _drop(old)
    return m


def err_text(ex: ProviderError, default="unavailable"):
    return ERR["timeout"] if ex.kind == "timeout" else ERR.get(default, ERR["unavailable"])


# --- access guard ------------------------------------------------------------
LAST_HIT: dict = {}
JOIN_CACHE: dict = {}


async def missing_joins(uid, fresh=False):
    rows = await db.all("SELECT * FROM force_join WHERE enabled=1 ORDER BY id")
    missing = []
    for r in rows:
        k = (uid, r["chat_id"])
        hit = JOIN_CACHE.get(k)
        if hit and not fresh and time.time() - hit < 20:
            continue
        try:
            cm = await bot.get_chat_member(r["chat_id"], uid)
            if cm.status in ("creator", "administrator", "member") or (
                    cm.status == "restricted" and getattr(cm, "is_member", False)):
                JOIN_CACHE[k] = time.time()
            else:
                missing.append(r)
        except TelegramRetryAfter:
            continue
        except TelegramAPIError as ex:
            # Bot lacks access to that chat: cannot verify, so do not lock users out. Fix it in Force Join > Check.
            log.warning("force-join check failed for chat %s: %s", r["chat_id"], str(ex)[:80])
    return missing


async def join_screen(ev, missing):
    rows = [[btn(f"➕ Join {m['title']}", url=m["link"])] for m in missing]
    rows.append([btn("✅ I've joined - verify", "verify")])
    text = head("ACCESS") + "🔒 <b>Join required</b>\nJoin the chats below, then tap <b>Verify</b>:\n\n" + \
        "\n".join(f"• {esc(m['title'])}" for m in missing)
    await screen(ev, "join", text, kb(*rows))


async def guard(ev, fresh=False) -> bool:
    u = ev.from_user
    is_cb = isinstance(ev, CallbackQuery)
    t = time.monotonic()
    if is_cb:
        try:
            await ev.answer()
        except TelegramAPIError:
            pass
    if t - LAST_HIT.get(u.id, 0) < 0.4:
        return False
    LAST_HIT[u.id] = t
    await db.run("INSERT INTO users(id,username,first_name,joined_at,last_seen) VALUES(?,?,?,?,?) "
                 "ON CONFLICT(id) DO UPDATE SET username=excluded.username, first_name=excluded.first_name, "
                 "last_seen=excluded.last_seen", (u.id, u.username or "", (u.first_name or "")[:64], now(), now()))
    r = await db.one("SELECT banned FROM users WHERE id=?", (u.id,))
    if r and r["banned"]:
        await screen(ev, "error", ERR["banned"])
        return False
    if u.id in ADMIN_SET:
        return True
    if S("maintenance") == "1":
        await screen(ev, "error", head("MAINTENANCE") + "🛠 " + esc(S("maintenance_message")))
        return False
    missing = await missing_joins(u.id, fresh)
    if missing:
        await join_screen(ev, missing)
        return False
    return True


# --- screens -----------------------------------------------------------------
def alive_sql():
    return "active=1 AND (expires_at=0 OR expires_at>?)", now()


async def get_email(uid, eid):
    cond, ts = alive_sql()
    if eid == 0:
        return await db.one(f"SELECT * FROM generated_emails WHERE user_id=? AND {cond} ORDER BY id DESC LIMIT 1", (uid, ts))
    return await db.one("SELECT * FROM generated_emails WHERE id=? AND user_id=?", (eid, uid))


def is_alive(row):
    return bool(row["active"]) and (row["expires_at"] == 0 or row["expires_at"] > now())


def remaining(row):
    if not row["expires_at"]:
        return "never"
    m = max(0, (row["expires_at"] - now()) // 60)
    return f"{m} min" if m < 120 else f"{m // 60} h"


async def show_home(ev, replace=None):
    name = esc(ev.from_user.first_name or "there")
    text = head(esc(S("bot_name")).upper()) + esc(S("welcome_message")).replace("{name}", name)
    sup = S("support_username").lstrip("@")
    rows = [[btn("📨 New Email", "gen"), btn("📥 Inbox", "inbox:0")],
            [btn("🗂 My Emails", "list"), btn("👤 Account", "acct")],
            [btn("❓ Help", "help")] + ([btn("💬 Support", url=f"https://t.me/{sup}")] if sup else [])]
    if ev.from_user.id in ADMIN_SET:
        rows.append([ADMIN_HOME])
    await screen(ev, "welcome", text, kb(*rows), replace)


async def show_email(ev, row, replace=None, key="generate", extra=""):
    text = (head("YOUR EMAIL") + f"{extra}<code>{esc(row['address'])}</code>\n\n"
            f"⏳ Expires: <b>{remaining(row)}</b>\n<i>Tap the address to copy it, or use the button.</i>")
    markup = kb([btn("📋 Copy address", copy=row["address"])],
                [btn("📥 Inbox", f"inbox:{row['id']}"), btn("🔄 Replace", f"rep:{row['id']}")],
                [btn("🗑 Delete", f"askdel:{row['id']}"), MENU])
    await screen(ev, key, text, markup, replace)


async def do_generate(ev, replace_old=None):
    uid = ev.from_user.id
    cond, ts = alive_sql()
    n = (await db.one(f"SELECT COUNT(*) c FROM generated_emails WHERE user_id=? AND {cond}", (uid, ts)))["c"]
    limit = to_int(S("max_emails_per_user"), 1, 50) or MAX_EMAILS_PER_USER
    if n >= limit:
        await screen(ev, "error", ERR["limit"].format(n=limit), kb([btn("🗂 My Emails", "list"), MENU]), replace_old)
        return
    loading = await screen(ev, "loading", head("GENERATING") + "⏳ Creating your address…", None, replace_old)
    try:
        prow, addr, secret = await prov.create_mailbox()
    except ProviderError as ex:
        await screen(ev, "error", err_text(ex), kb([btn("🔁 Try again", "gen"), MENU]), loading)
        return
    ttl = to_int(S("email_ttl_minutes"), 0, 100000)
    ttl = EMAIL_TTL_MINUTES if ttl is None else ttl
    eid = await db.run("INSERT INTO generated_emails(user_id,provider_id,address,secret,created_at,expires_at) "
                       "VALUES(?,?,?,?,?,?)", (uid, prow["id"], addr, secret, now(), now() + ttl * 60 if ttl else 0))
    await db.run("UPDATE users SET emails_created=emails_created+1 WHERE id=?", (uid,))
    await log_act(uid, "generate", prow["name"])
    row = await db.one("SELECT * FROM generated_emails WHERE id=?", (eid,))
    await show_email(ev, row, loading, "generate", "✅ <b>Address ready</b>\n")


async def no_email(ev):
    await screen(ev, "error", head("INBOX") + "📪 You have no active email yet.",
                 kb([btn("📨 New Email", "gen")], [MENU]))


async def show_inbox(ev, eid):
    row = await get_email(ev.from_user.id, eid)
    if not row:
        return await no_email(ev) if eid == 0 else await screen(ev, "error", ERR["invalid"], kb([MENU]))
    if not is_alive(row):
        return await screen(ev, "error", ERR["expired"], kb([btn("📨 New Email", "gen"), MENU]))
    try:
        ad = await prov.adapter_for(row)
        msgs = await ad.list_messages(row["address"], row["secret"])
    except ProviderError as ex:
        log.warning("inbox error: %s", ex)
        return await screen(ev, "error", err_text(ex, "inbox"),
                            kb([btn("🔄 Retry", f"inbox:{row['id']}")], [btn("🔁 Replace", f"rep:{row['id']}"), MENU]))
    if len(msgs) > row["msg_count"]:
        await db.run("UPDATE generated_emails SET msg_count=? WHERE id=?", (len(msgs), row["id"]))
    rows = [[btn(("✉️ " + f"{m['from'].split('<')[0].strip() or m['from']} · {m['subject'] or '(no subject)'}")[:60],
                 f"read:{row['id']}:{m['id']}")] for m in msgs[:10]]
    rows.append([btn("🔄 Refresh", f"inbox:{row['id']}"), btn("📋 Address", f"mail:{row['id']}")])
    rows.append([MENU])
    body = (f"📬 <b>{len(msgs)}</b> message(s)" + (" (latest 10 shown)" if len(msgs) > 10 else "")
            if msgs else "📭 Inbox is empty. Waiting for new mail…")
    text = (head("INBOX") + f"<code>{esc(row['address'])}</code>\n\n{body}\n"
            f"<i>Updated {datetime.now(timezone.utc).strftime('%H:%M:%S')} UTC</i>")
    await screen(ev, "inbox", text, kb(*rows))


async def show_message(ev, eid, mid):
    row = await get_email(ev.from_user.id, eid)
    if not row or not re.fullmatch(r"[A-Za-z0-9_\-]{1,64}", mid or ""):
        return await screen(ev, "error", ERR["invalid"], kb([MENU]))
    if not is_alive(row):
        return await screen(ev, "error", ERR["expired"], kb([btn("📨 New Email", "gen"), MENU]))
    back = kb([btn("⬅️ Inbox", f"inbox:{row['id']}"), MENU])
    try:
        ad = await prov.adapter_for(row)
        m = await ad.read_message(row["address"], row["secret"], mid)
    except ProviderError as ex:
        log.warning("read error: %s", ex)
        return await screen(ev, "error", err_text(ex, "inbox"), back)
    body = m["text"].strip() or html_to_text(m["html"])
    body = body or "(empty message)"
    limit = min(to_int(S("max_message_chars"), 200, 3000) or MAX_MESSAGE_CHARS, 3000)
    raw = body[:limit] + ("…" if len(body) > limit else "")
    while True:
        text = (head("MESSAGE") + f"<b>From:</b> {esc(m['from'])}\n<b>Subject:</b> {esc(m['subject'] or '(none)')}\n"
                f"<b>Date:</b> {esc(fmt_mail_date(m['date']))}\n━━━━━━━━━━━━━━━━\n{esc(raw)}")
        if len(text) <= 4000:
            break
        raw = raw[:int(len(raw) * 0.8)]
    await log_act(ev.from_user.id, "read")
    await screen(ev, "detail", text, back)


async def kill_email(row):
    try:
        await (await prov.adapter_for(row)).delete(row["address"], row["secret"])
    except ProviderError:
        pass
    await db.run("UPDATE generated_emails SET active=0, secret='' WHERE id=?", (row["id"],))


HELP_TEXT = (head("HELP") + "<b>How it works</b>\n1️⃣ Tap <b>New Email</b> to get an address.\n"
             "2️⃣ Use it on any site or form.\n3️⃣ Open <b>Inbox</b> and tap <b>Refresh</b> to read incoming mail.\n\n"
             "<b>Commands</b>\n/start - main menu\n/help - this screen\n\n"
             "Addresses expire automatically. Never use a temporary address for important accounts.")


async def handle_callback(cb: CallbackQuery):
    action, _, rest = (cb.data or "").partition(":")
    uid = cb.from_user.id
    if not await guard(cb, fresh=(action == "verify")):
        return
    if action in ("home", "verify"):
        await show_home(cb)
    elif action == "help":
        await screen(cb, "help", HELP_TEXT, kb([MENU]))
    elif action == "gen":
        await do_generate(cb)
    elif action == "acct":
        u = await db.one("SELECT * FROM users WHERE id=?", (uid,))
        cond, ts = alive_sql()
        n = (await db.one(f"SELECT COUNT(*) c FROM generated_emails WHERE user_id=? AND {cond}", (uid, ts)))["c"]
        text = (head("ACCOUNT") + f"🆔 <code>{uid}</code>\n👤 {esc(cb.from_user.first_name)}\n"
                f"📨 Emails created: <b>{u['emails_created']}</b>\n🟢 Active now: <b>{n}</b>\n"
                f"📅 Joined: {fmt_ts(u['joined_at'])}")
        await screen(cb, "account", text, kb([MENU]))
    elif action == "list":
        cond, ts = alive_sql()
        rows = await db.all(f"SELECT * FROM generated_emails WHERE user_id=? AND {cond} ORDER BY id DESC LIMIT 20", (uid, ts))
        if not rows:
            return await no_email(cb)
        text = head("MY EMAILS") + "\n".join(f"• <code>{esc(r['address'])}</code> ({remaining(r)})" for r in rows)
        await screen(cb, "inbox", text, kb(*[[btn(f"📧 {r['address']}"[:60], f"mail:{r['id']}")] for r in rows], [MENU]))
    elif action in ("mail", "inbox", "askdel", "del", "rep", "read"):
        parts = rest.split(":")
        eid = to_int(parts[0], 0, 2 ** 62)
        if eid is None:
            return
        if action == "inbox":
            await show_inbox(cb, eid)
        elif action == "read":
            await show_message(cb, eid, parts[1] if len(parts) > 1 else "")
        else:
            row = await get_email(uid, eid)
            if not row:
                return await screen(cb, "error", ERR["invalid"], kb([MENU]))
            if action == "mail":
                await (show_email(cb, row) if is_alive(row) else screen(cb, "error", ERR["expired"], kb([btn("📨 New Email", "gen"), MENU])))
            elif action == "askdel":
                await screen(cb, None, head("DELETE") + f"Delete <code>{esc(row['address'])}</code>?\nIts inbox will be discarded.",
                             kb([btn("🗑 Yes, delete", f"del:{row['id']}"), btn("Cancel", f"mail:{row['id']}")]))
            elif action == "del":
                await kill_email(row)
                await log_act(uid, "delete")
                await screen(cb, "success", head("DONE") + "✅ Email deleted.", kb([btn("📨 New Email", "gen"), MENU]))
            elif action == "rep":
                await kill_email(row)
                await log_act(uid, "replace")
                await do_generate(cb)


async def cmd_start(m: Message):
    if m.from_user:
        PENDING.pop(m.from_user.id, None)
    if m.chat.type == "private" and await guard(m):
        await log_act(m.from_user.id, "start")
        await show_home(m)


async def cmd_help(m: Message):
    if m.chat.type == "private" and await guard(m):
        await screen(m, "help", HELP_TEXT, kb([MENU]))


async def on_error(event: ErrorEvent):
    ex = event.exception
    log.error("handler error: %s: %s", ex.__class__.__name__, str(ex)[:120])
    upd = event.update
    u = (upd.callback_query or upd.message)
    if u is not None and u.from_user:
        key = "db" if isinstance(ex, aiosqlite.Error) else ("tg" if isinstance(ex, TelegramAPIError) else "generic")
        try:
            await bot.send_message(u.from_user.id, ERR[key], reply_markup=kb([MENU]))
        except TelegramAPIError:
            pass
    return True


# ------------------------------------------------------------------ background jobs
async def cleanup_loop():
    while True:
        try:
            await asyncio.sleep(300)
            rows = await db.all("SELECT * FROM generated_emails WHERE active=1 AND expires_at>0 AND expires_at<=? LIMIT 30",
                                (now(),))
            for r in rows:
                await kill_email(r)
            await db.run("UPDATE generated_emails SET secret='' WHERE active=0 AND secret!=''")
            await db.run("DELETE FROM user_activity WHERE created_at<?", (now() - 30 * 86400,))
            t = time.monotonic()
            for k in [k for k, v in LAST_HIT.items() if t - v > 60]:
                LAST_HIT.pop(k, None)
            for k in [k for k, v in JOIN_CACHE.items() if time.time() - v > 60]:
                JOIN_CACHE.pop(k, None)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("cleanup error")


# ------------------------------------------------------------------ telegram admin panel
# Everything the old web panel did, inside the bot. Open with /admin (or the "Admin" button on the main menu).
# Admins = ADMIN_SET. Super admins (ADMIN_IDS from the environment) can also manage admins and download backups.
PENDING: dict = {}          # admin id -> {"act": ..., "exp": ts, ...}: the bot is waiting for that admin's next text message
SUPER_ADMINS = set(ADMIN_IDS)
BCJOB = {"running": False, "cancel": False, "total": 0, "sent": 0, "failed": 0, "blocked": 0, "started": 0, "task": None}
ADMIN_HOME = btn("🛠 Admin", "a:home")
CHAT_RE = re.compile(r"^(@[A-Za-z0-9_]{4,32}|-?\d{5,20})$")
LINK_RE = re.compile(r"^(https://(t|telegram)\.me/\S+|tg://\S+)$")
PSTAT = {"up": "🟢", "degraded": "🟡", "down": "🔴", "unknown": "⚪"}


def is_super(uid) -> bool:
    return uid in SUPER_ADMINS


# ---- pure validators / formatters (unit-tested) ----
def validate_setting(key, raw):
    kind, lo, hi, _ = SETTING_META[key]
    raw = (raw or "").strip()
    if kind == "int":
        n = to_int(raw, lo, hi)
        if n is None:
            raise ValueError(f"Enter a whole number from {lo} to {hi}")
        return str(n)
    if kind == "user":
        raw = raw.lstrip("@")
        if raw in ("", "-"):
            return ""
        if not re.fullmatch(r"[A-Za-z0-9_]{4,32}", raw):
            raise ValueError("Username: 4-32 letters, digits or _ (send - to hide the Support button)")
        return raw
    if not lo <= len(raw) <= hi:
        raise ValueError(f"Length must be {lo}-{hi} characters")
    return raw


def parse_json_obj(s, name):
    try:
        d = json.loads(s or "{}")
    except ValueError:
        raise ValueError(f"{name} is not valid JSON")
    if not isinstance(d, dict):
        raise ValueError(f"{name} must be a JSON object")
    return d


def check_headers(h: dict):
    for k, v in h.items():
        if not re.fullmatch(r"[A-Za-z0-9\-]{1,60}", str(k)) or re.search(r"[\r\n]", str(v)):
            raise ValueError("Invalid header name or value")


def valid_http_url(u: str) -> bool:
    try:
        p = urlparse(u)
    except ValueError:
        return False
    return p.scheme in ("http", "https") and bool(p.netloc) and " " not in u and len(u) <= 300


def csv_cell(v) -> str:
    s = "" if v is None else str(v)
    if s[:1] in ("=", "+", "-", "@", "\t", "\r"):
        s = "'" + s            # stop spreadsheet formula injection
    return '"' + s.replace('"', '""') + '"'


def users_csv(rows) -> bytes:
    cols = ["id", "username", "first_name", "banned", "joined_at", "last_seen", "emails_created"]
    out = [",".join(cols)]
    for r in rows:
        out.append(",".join(csv_cell(r[c]) for c in cols))
    return ("\n".join(out) + "\n").encode("utf-8")


# ---- helpers ----
async def audit(uid, action, detail=""):
    try:
        await db.run("INSERT INTO admin_audit(admin_id,action,detail,created_at) VALUES(?,?,?,?)",
                     (uid, action[:40], detail[:200], now()))
    except aiosqlite.Error:
        log.warning("audit log failed")


async def ascr(ev, text, markup=None):
    return await screen(ev, None, text, markup)


def back(to="a:home"):
    return btn("⬅️ Back", to)


async def ask(ev, uid, act, prompt, **data):
    PENDING[uid] = {"act": act, "exp": now() + 600, **data}
    await ascr(ev, head("ADMIN") + prompt + "\n\n<i>Send your answer as a message. /start cancels.</i>",
               kb([btn("✖️ Cancel", "a:cancel")]))


# ---- home / stats / audit ----
async def admin_home(ev):
    uid = ev.from_user.id
    rows = [[btn("📊 Stats", "a:stats"), btn("👥 Users", "a:us")],
            [btn("📨 Providers", "a:pv"), btn("🖼 Media", "a:md")],
            [btn("🔒 Force Join", "a:fj"), btn("⚙️ Settings", "a:st")],
            [btn("📣 Broadcast", "a:bc"), btn("🧾 Audit log", "a:au")]]
    if is_super(uid):
        rows.append([btn("👮 Admins", "a:ad"), btn("💾 Backup", "a:bk")])
    rows.append([MENU])
    await ascr(ev, head("ADMIN PANEL") + "Choose a section.", kb(*rows))


async def admin_stats(ev):
    def c(sql, a=()):
        return db.one(sql, a)
    total = (await c("SELECT COUNT(*) c FROM users"))["c"]
    act = (await c("SELECT COUNT(*) c FROM users WHERE last_seen>?", (now() - 86400,)))["c"]
    ban = (await c("SELECT COUNT(*) c FROM users WHERE banned=1"))["c"]
    em = await c("SELECT COUNT(*) c, COALESCE(SUM(msg_count),0) s FROM generated_emails")
    live = (await c("SELECT COUNT(*) c FROM generated_emails WHERE active=1 AND (expires_at=0 OR expires_at>?)", (now(),)))["c"]
    provs = await db.all("SELECT * FROM providers")
    usable = sum(1 for p in provs if p["enabled"] and p["status"] in ("up", "unknown") and p["down_until"] <= now())
    failed = sum(1 for p in provs if p["enabled"] and p["status"] == "down")
    fj = (await c("SELECT COUNT(*) c FROM force_join WHERE enabled=1"))["c"]
    acts = await db.all("SELECT user_id,action,created_at FROM user_activity ORDER BY id DESC LIMIT 5")
    up = now() - int(START_TIME)
    text = (head("STATS") + f"👥 Users: <b>{total}</b> · active 24h: <b>{act}</b> · banned: <b>{ban}</b>\n"
            f"📨 Emails created: <b>{em['c']}</b> · active now: <b>{live}</b>\n"
            f"📬 Messages seen: <b>{em['s']}</b> <i>(largest inbox size seen when opened)</i>\n"
            f"🌐 Providers usable: <b>{usable}/{len(provs)}</b> · down: <b>{failed}</b>\n"
            f"🔒 Force-join chats active: <b>{fj}</b> · maintenance: <b>{'ON' if S('maintenance') == '1' else 'off'}</b>\n"
            f"⏱ Uptime: <b>{up // 3600} h {up // 60 % 60} min</b>\n\n<b>Recent activity</b>\n"
            + ("\n".join(f"• <code>{a['user_id']}</code> {esc(a['action'])} · {fmt_ts(a['created_at'])}" for a in acts) or "none yet"))
    await ascr(ev, text, kb([btn("🔄 Refresh", "a:stats"), back()]))


async def admin_audit_view(ev):
    rows = await db.all("SELECT * FROM admin_audit ORDER BY id DESC LIMIT 15")
    text = head("AUDIT LOG") + ("\n".join(f"• {fmt_ts(r['created_at'])} <code>{r['admin_id']}</code> {esc(r['action'])} {esc(r['detail'])}"
                                          for r in rows) or "No admin actions recorded yet.")
    await ascr(ev, text, kb([back()]))


# ---- providers ----
async def prov_list(ev):
    rows = await db.all("SELECT * FROM providers ORDER BY priority,id")
    lines = [f"{PSTAT.get(p['status'], '⚪')} {'✅' if p['enabled'] else '⛔'} <b>{esc(p['name'])}</b> · {esc(p['api_type'])} · prio {p['priority']}"
             for p in rows] or ["No providers yet."]
    kbrows = [[btn(f"{PSTAT.get(p['status'], '⚪')} {p['name']}"[:40], f"a:pv:{p['id']}")] for p in rows]
    kbrows += [[btn("➕ Add provider", "a:pva")], [back()]]
    await ascr(ev, head("PROVIDERS") + "\n".join(lines) + "\n\n<i>Tried in priority order. Failing providers are skipped for a cooldown "
               "and re-checked automatically. Types: " + ", ".join(ADAPTERS) + ".</i>", kb(*kbrows))


async def prov_card(ev, pid, note=""):
    p = await db.one("SELECT * FROM providers WHERE id=?", (pid,))
    if not p:
        return await prov_list(ev)
    n = (await db.one("SELECT COUNT(*) c FROM generated_emails WHERE provider_id=? AND active=1", (pid,)))["c"]
    text = (head("PROVIDER") + note + f"<b>{esc(p['name'])}</b> ({esc(p['api_type'])})\nURL: <code>{esc(p['base_url'])}</code>\n"
            f"Priority: {p['priority']} · {'enabled' if p['enabled'] else 'disabled'}\n"
            f"Health: {PSTAT.get(p['status'], '⚪')} {esc(p['status'])} · failures: {p['fail_count']}\n"
            f"Last check: {fmt_ts(p['last_check'])}\nLast error: {esc(p['last_error'] or '-')}\n"
            f"API key: {'set' if p['api_key'] else 'none'} · headers: {'set' if loads_obj(p['headers']) else 'none'} · "
            f"extra: {'set' if loads_obj(p['extra']) else 'none'}\nActive mailboxes: {n}")
    i = p["id"]
    await ascr(ev, text, kb(
        [btn("⛔ Disable" if p["enabled"] else "✅ Enable", f"a:pvt:{i}"), btn("🧪 Test", f"a:pvc:{i}")],
        [btn("⬆️ Higher priority", f"a:pvu:{i}"), btn("⬇️ Lower priority", f"a:pvd:{i}")],
        [btn("✏️ Name", f"a:pve:{i}:name"), btn("🌐 URL", f"a:pve:{i}:url"), btn("🔢 Priority", f"a:pve:{i}:prio")],
        [btn("🔑 API key", f"a:pve:{i}:key"), btn("📋 Headers", f"a:pve:{i}:hdr"), btn("🧩 Config", f"a:pve:{i}:ext")],
        [btn("🗑 Delete", f"a:pvx:{i}"), back("a:pv")]))


PV_PROMPTS = {
    "name": "Send the new provider name (1-40 characters).",
    "url": "Send the API base URL, e.g. https://api.example.com",
    "prio": "Send the priority number 1-9999 (lower is tried first).",
    "key": "Send the API key. Your message is deleted right after. Send - to remove the stored key.",
    "hdr": 'Send extra request headers as a JSON object, e.g. {"X-Token":"abc"}. Send {} to clear.',
    "ext": 'Send custom config as a JSON object, e.g. {"domain":"example.com","key_header":"X-API-Key"}. Send {} to clear.',
}


async def pv_apply(pid, field, text):
    """Validate and store one provider field. Raises ValueError with a user-facing message."""
    text = text.strip()
    try:
        if field == "name":
            if not 1 <= len(text) <= 40:
                raise ValueError("Name must be 1-40 characters")
            await db.run("UPDATE providers SET name=? WHERE id=?", (text, pid))
        elif field == "url":
            u = text.rstrip("/")
            if not valid_http_url(u):
                raise ValueError("Send a valid http(s) URL")
            await db.run("UPDATE providers SET base_url=? WHERE id=?", (u, pid))
        elif field == "prio":
            n = to_int(text, 1, 9999)
            if n is None:
                raise ValueError("Priority must be 1-9999")
            await db.run("UPDATE providers SET priority=? WHERE id=?", (n, pid))
        elif field == "key":
            await db.run("UPDATE providers SET api_key=? WHERE id=?", ("" if text == "-" else text[:300], pid))
        elif field in ("hdr", "ext"):
            d = parse_json_obj(text, "Headers" if field == "hdr" else "Config")
            if field == "hdr":
                check_headers(d)
            await db.run(f"UPDATE providers SET {'headers' if field == 'hdr' else 'extra'}=? WHERE id=?", (json.dumps(d), pid))
        else:
            raise ValueError("Unknown field")
    except aiosqlite.IntegrityError:
        raise ValueError("A provider with that name already exists")


# ---- media ----
async def media_list(ev):
    rows = {r["key"]: r for r in await db.all("SELECT * FROM media_settings")}
    kbrows = []
    for k, label in MEDIA_LABELS.items():
        r = rows.get(k)
        mark = "–" if not (r and r["url"]) else ("✅" if r["enabled"] else "⛔")
        kbrows.append([btn(f"{mark} {label}", f"a:md:{k}")])
    kbrows.append([back()])
    await ascr(ev, head("MEDIA") + "✅ active · ⛔ disabled · – text only\nPick a screen to set its image / GIF / video URL.", kb(*kbrows))


async def media_card(ev, key, note=""):
    r = await db.one("SELECT * FROM media_settings WHERE key=?", (key,))
    url = (r or {}).get("url", "")
    kind = {"photo": "image", "animation": "GIF", "video": "video"}.get(media_kind(url) or "", "-")
    text = (head("MEDIA") + note + f"<b>{esc(MEDIA_LABELS[key])}</b>\nURL: " + (f"<code>{esc(url)}</code>" if url else "none (text only)")
            + f"\nType: {kind} · {'enabled' if (r or {}).get('enabled', 1) else 'disabled'}")
    rows = [[btn("✏️ Set URL", f"a:mds:{key}")]]
    if url:
        rows.append([btn("⛔ Disable" if r["enabled"] else "✅ Enable", f"a:mdt:{key}"), btn("🧪 Test", f"a:mdp:{key}")])
        rows.append([btn("🗑 Remove", f"a:mdr:{key}")])
    rows.append([back("a:md")])
    await ascr(ev, text, kb(*rows))


async def media_set(key, url):
    old = await media_url_raw(key)
    await db.run("UPDATE media_settings SET url=?, enabled=1, updated_at=? WHERE key=?", (url, now(), key))
    for u in (old, url):
        FILE_IDS.pop(u, None)
        BAD_MEDIA.pop(u, None)


async def media_url_raw(key):
    r = await db.one("SELECT url FROM media_settings WHERE key=?", (key,))
    return (r or {}).get("url", "")


# ---- force join ----
async def fj_list(ev):
    rows = await db.all("SELECT * FROM force_join ORDER BY id")
    lines = [f"{'✅' if r['enabled'] else '⛔'} <b>{esc(r['title'])}</b> · {esc(r['kind'])} · <code>{esc(r['chat_id'])}</code>" for r in rows] \
        or ["No requirements. Users are not asked to join anything."]
    kbrows = [[btn(f"{'✅' if r['enabled'] else '⛔'} {r['title']}"[:40], f"a:fj:{r['id']}")] for r in rows]
    kbrows += [[btn("➕ Add channel / group", "a:fja")], [back()]]
    await ascr(ev, head("FORCE JOIN") + "\n".join(lines) + "\n\n<i>The bot must be a member (admin for channels) of each chat. If it cannot "
               "access a chat, that requirement is skipped for users.</i>", kb(*kbrows))


async def fj_card(ev, fid, note=""):
    r = await db.one("SELECT * FROM force_join WHERE id=?", (fid,))
    if not r:
        return await fj_list(ev)
    text = (head("FORCE JOIN") + note + f"<b>{esc(r['title'])}</b> ({esc(r['kind'])})\nChat: <code>{esc(r['chat_id'])}</code>\n"
            f"Link: {esc(r['link'])}\nState: {'enabled' if r['enabled'] else 'disabled'}")
    i = r["id"]
    await ascr(ev, text, kb(
        [btn("⛔ Disable" if r["enabled"] else "✅ Enable", f"a:fjt:{i}")],
        [btn("🛡 Check bot permission", f"a:fjc:{i}"), btn("🧪 Test my membership", f"a:fjm:{i}")],
        [btn("✏️ Title", f"a:fje:{i}:title"), btn("🆔 Chat ID", f"a:fje:{i}:chat"), btn("🔗 Link", f"a:fje:{i}:link")],
        [btn("🗑 Remove", f"a:fjx:{i}"), back("a:fj")]))


def fj_validate(field, text):
    text = text.strip()
    if field == "title":
        if not 1 <= len(text) <= 40:
            raise ValueError("Title must be 1-40 characters")
    elif field == "chat":
        if not CHAT_RE.match(text):
            raise ValueError("Chat must be @username or a numeric ID like -1001234567890")
    elif field == "link":
        if not LINK_RE.match(text) or len(text) > 300:
            raise ValueError("Link must start with https://t.me/ (or telegram.me / tg://)")
    return text


FJ_COL = {"title": "title", "chat": "chat_id", "link": "link"}


# ---- settings ----
async def settings_list(ev):
    lines = []
    for k, (kind, lo, hi, label) in SETTING_META.items():
        v = S(k)
        shown = (v[:40] + "…") if len(v) > 40 else v
        lines.append(f"• {esc(label)}: <code>{esc(shown) or '-'}</code>")
    lines.append(f"• Maintenance mode: <b>{'ON' if S('maintenance') == '1' else 'off'}</b>")
    keys = list(SETTING_META)
    kbrows = [[btn("🛠 Turn maintenance " + ("OFF" if S("maintenance") == "1" else "ON"), "a:stm")]]
    for i in range(0, len(keys), 2):
        kbrows.append([btn("✏️ " + SETTING_META[k][3].split(" (")[0][:22], f"a:sts:{k}") for k in keys[i:i + 2]])
    kbrows.append([back()])
    await ascr(ev, head("SETTINGS") + "\n".join(lines) + "\n\n<i>Changes apply immediately, no restart needed.</i>", kb(*kbrows))


# ---- users ----
async def users_menu(ev):
    n = (await db.one("SELECT COUNT(*) c FROM users"))["c"]
    await ascr(ev, head("USERS") + f"{n} users in total.",
               kb([btn("🔎 Search", "a:uss"), btn("🕒 Recent", "a:usr")], [btn("📤 Export CSV", "a:usc")], [back()]))


async def users_pick(ev, rows, title):
    if not rows:
        return await ascr(ev, head("USERS") + "No users found.", kb([btn("🔎 Search again", "a:uss"), back("a:us")]))
    if len(rows) == 1:
        return await user_card(ev, rows[0]["id"])
    kbrows = [[btn(f"{'🚫 ' if r['banned'] else ''}{r['id']} · @{r['username'] or '-'} · {r['first_name']}"[:60], f"a:us:{r['id']}")] for r in rows[:10]]
    kbrows.append([back("a:us")])
    await ascr(ev, head("USERS") + title, kb(*kbrows))


async def user_card(ev, uid2, note=""):
    u = await db.one("SELECT * FROM users WHERE id=?", (uid2,))
    if not u:
        return await ascr(ev, head("USERS") + "User not found.", kb([back("a:us")]))
    cond, ts = alive_sql()
    live = (await db.one(f"SELECT COUNT(*) c FROM generated_emails WHERE user_id=? AND {cond}", (uid2, ts)))["c"]
    acts = await db.all("SELECT action,created_at FROM user_activity WHERE user_id=? ORDER BY id DESC LIMIT 5", (uid2,))
    text = (head("USER") + note + f"🆔 <code>{u['id']}</code> · @{esc(u['username'] or '-')} · {esc(u['first_name'])}\n"
            f"Status: {'🚫 BANNED' if u['banned'] else '🟢 active'}\nJoined: {fmt_ts(u['joined_at'])}\nLast seen: {fmt_ts(u['last_seen'])}\n"
            f"Emails created: <b>{u['emails_created']}</b> · active: <b>{live}</b>\n\n<b>Recent activity</b>\n"
            + ("\n".join(f"• {esc(a['action'])} · {fmt_ts(a['created_at'])}" for a in acts) or "none"))
    i = u["id"]
    await ascr(ev, text, kb(
        [btn("✅ Unban", f"a:usb:{i}:0") if u["banned"] else btn("🚫 Ban", f"a:usbq:{i}")],
        [btn("📧 Email records", f"a:use:{i}"), btn("🧹 Delete active emails", f"a:usx:{i}")],
        [back("a:us")]))


# ---- admins (super admins only) ----
async def admins_list(ev):
    rows = await db.all("SELECT * FROM admins WHERE tg_id IS NOT NULL ORDER BY id")
    lines = [f"{'👑' if is_super(r['tg_id']) else '👤'} <code>{r['tg_id']}</code> · added {fmt_ts(r['created_at'])}" for r in rows]
    kbrows = [[btn(f"🗑 Remove {r['tg_id']}", f"a:adx:{r['id']}")] for r in rows if not is_super(r["tg_id"])]
    kbrows += [[btn("➕ Add admin", "a:ada")], [back()]]
    await ascr(ev, head("ADMINS") + "\n".join(lines) + "\n\n👑 = super admin (from ADMIN_IDS, cannot be removed here). "
               "All admins bypass maintenance and force join.", kb(*kbrows))


# ---- broadcast ----
def bc_progress_text():
    done = BCJOB["sent"] + BCJOB["failed"] + BCJOB["blocked"]
    pct = int(done * 100 / BCJOB["total"]) if BCJOB["total"] else 100
    return (f"{'📤 Sending…' if BCJOB['running'] else '✅ Last broadcast finished'} {pct}%\nTotal {BCJOB['total']} · delivered {BCJOB['sent']} · "
            f"blocked {BCJOB['blocked']} · failed {BCJOB['failed']}\nStarted {fmt_ts(BCJOB['started'])}")


async def bc_edit(prog, text, markup=None):
    try:
        await bot.edit_message_text(text, chat_id=prog[0], message_id=prog[1], reply_markup=markup)
    except TelegramAPIError:
        pass        # message unchanged / deleted: progress display is best-effort


async def broadcast_worker(admin_id, src_chat, src_msg, markup, prog):
    ids = [r["id"] for r in await db.all("SELECT id FROM users WHERE banned=0")]
    BCJOB.update(running=True, cancel=False, total=len(ids), sent=0, failed=0, blocked=0, started=now())
    stop_kb = kb([btn("🛑 Cancel broadcast", "a:bcx")])
    try:
        for i, uid in enumerate(ids, 1):
            if BCJOB["cancel"]:
                break
            for _ in range(2):
                try:
                    await bot.copy_message(uid, src_chat, src_msg, reply_markup=markup)
                    BCJOB["sent"] += 1
                    break
                except TelegramRetryAfter as ex:
                    await asyncio.sleep(ex.retry_after + 1)
                except TelegramForbiddenError:
                    BCJOB["blocked"] += 1
                    break
                except TelegramAPIError:
                    BCJOB["failed"] += 1
                    break
            else:
                BCJOB["failed"] += 1
            if i % 25 == 0:
                await bc_edit(prog, head("BROADCAST") + bc_progress_text(), stop_kb)
            await asyncio.sleep(0.05)       # ~20 msg/s, below Telegram's ~30/s global limit
    finally:
        cancelled = BCJOB["cancel"]
        BCJOB["running"] = False
        await audit(admin_id, "broadcast", f"sent={BCJOB['sent']} failed={BCJOB['failed']} blocked={BCJOB['blocked']}"
                    + (" cancelled" if cancelled else ""))
        summary = ("🛑 Broadcast cancelled.\n" if cancelled else "✅ Broadcast finished.\n") + bc_progress_text()
        await bc_edit(prog, head("BROADCAST") + summary, kb([ADMIN_HOME]))
        try:
            await bot.send_message(admin_id, summary)
        except TelegramAPIError:
            pass


async def bc_start(ev, uid):
    if BCJOB["running"]:
        return await ascr(ev, head("BROADCAST") + bc_progress_text(),
                          kb([btn("🔄 Progress", "a:bc"), btn("🛑 Cancel broadcast", "a:bcx")], [back()]))
    last = ("\n\n<b>Last broadcast</b>\n" + bc_progress_text()) if BCJOB["started"] else ""
    await ask(ev, uid, "bc_msg", "Send me the message to broadcast: text, photo, GIF or video with a caption. "
              "Formatting is kept exactly. One message only; don't delete it until sending is done." + last)


async def bc_review(ev, uid, src_chat, src_msg, button):
    PENDING[uid] = {"act": "bc_confirm", "exp": now() + 900, "src_chat": src_chat, "src_msg": src_msg, "button": button}
    audience = (await db.one("SELECT COUNT(*) c FROM users WHERE banned=0"))["c"]
    await ascr(ev, head("BROADCAST") + "Preview below: users receive exactly this.")
    try:
        await bot.copy_message(uid, src_chat, src_msg, reply_markup=bc_markup(button))
    except TelegramAPIError as ex:
        PENDING.pop(uid, None)
        return await ascr(ev, head("BROADCAST") + f"⚠️ That message cannot be broadcast: {esc(str(ex)[:100])}", kb([back()]))
    await ascr(ev, head("BROADCAST") + f"Send to <b>{audience}</b> users?" + (f"\nButton: <b>{esc(button[0])}</b>" if button else ""),
               kb([btn(f"✅ Send to {audience}", "a:bcg")],
                  [btn("🔘 " + ("Change button" if button else "Add link button"), "a:bcb"), btn("✖️ Cancel", "a:cancel")]))


def bc_markup(button):
    if not button:
        return None
    return kb([btn(button[0], url=button[1])])


# ---- backup (super admins) ----
async def send_backup(ev, uid):
    tmp = os.path.join(tempfile.mkdtemp(), f"rbx404-backup-{now()}.db")
    try:
        await asyncio.to_thread(file_backup, db.path, tmp)
        await bot.send_document(uid, FSInputFile(tmp), caption="🔐 Database backup. It contains provider API keys and mailbox "
                                "credentials: keep it private and delete this message when done.")
    finally:
        try:
            os.remove(tmp)
            os.rmdir(os.path.dirname(tmp))
        except OSError:
            pass
    await audit(uid, "backup")


# ---- entry points ----
async def cmd_admin(m: Message):
    if m.chat.type == "private" and m.from_user and m.from_user.id in ADMIN_SET:
        PENDING.pop(m.from_user.id, None)
        await admin_home(m)


async def admin_cb(cb: CallbackQuery):
    uid = cb.from_user.id
    parts = (cb.data or "").split(":")
    sec = parts[1] if len(parts) > 1 else "home"
    toast = {"pvc": "🧪 Testing connection…", "mdp": "🧪 Loading media…", "fjc": "🛡 Checking…", "fjm": "🧪 Checking…",
             "usc": "📤 Preparing CSV…", "bk": "💾 Preparing backup…", "bcg": "📤 Starting broadcast…"}.get(sec)
    try:
        await cb.answer(toast if uid in ADMIN_SET else None)
    except TelegramAPIError:
        pass
    if uid not in ADMIN_SET:
        return
    arg = parts[2] if len(parts) > 2 else ""
    extra = parts[3] if len(parts) > 3 else ""
    if sec not in ("pvat", "fjak", "bcg", "bcb"):
        PENDING.pop(uid, None)
    n = to_int(arg, 0, 2 ** 62)
    yes = lambda t, cb_yes, cb_no: kb([btn("✅ Yes, confirm", cb_yes), btn("✖️ No", cb_no)])  # noqa: E731

    if sec in ("home", "cancel"):
        await admin_home(cb)
    elif sec == "stats":
        await admin_stats(cb)
    elif sec == "au":
        await admin_audit_view(cb)

    # providers
    elif sec == "pv":
        await (prov_card(cb, n) if n else prov_list(cb))
    elif sec in ("pvt", "pvc", "pvu", "pvd", "pvx", "pvX", "pve") and n:
        p = await db.one("SELECT * FROM providers WHERE id=?", (n,))
        if not p:
            return await prov_list(cb)
        if sec == "pvt":
            await db.run("UPDATE providers SET enabled=1-enabled, fail_count=0, down_until=0 WHERE id=?", (n,))
            await audit(uid, "provider_toggle", p["name"])
            await prov_card(cb, n, "✅ Updated.\n\n")
        elif sec == "pvc":
            ok, msg = await prov.check(p)
            await prov_card(cb, n, ("✅ Connection OK.\n\n" if ok else f"❌ Failed: {esc(msg)}\n\n"))
        elif sec in ("pvu", "pvd"):
            await db.run("UPDATE providers SET priority=MAX(1,MIN(9999,priority+?)) WHERE id=?", (-1 if sec == "pvu" else 1, n))
            await audit(uid, "provider_priority", p["name"])
            await prov_card(cb, n)
        elif sec == "pvx":
            live = (await db.one("SELECT COUNT(*) c FROM generated_emails WHERE provider_id=? AND active=1", (n,)))["c"]
            await ascr(cb, head("DELETE PROVIDER") + f"Delete <b>{esc(p['name'])}</b>?\n{live} active mailbox(es) use it and will stop working. "
                       "Other providers are not affected.", yes("", f"a:pvX:{n}", f"a:pv:{n}"))
        elif sec == "pvX":
            await db.run("DELETE FROM providers WHERE id=?", (n,))
            await audit(uid, "provider_delete", p["name"])
            await prov_list(cb)
        elif sec == "pve" and extra in PV_PROMPTS:
            await ask(cb, uid, "pv_edit", f"<b>{esc(p['name'])}</b>\n" + PV_PROMPTS[extra], id=n, field=extra)
    elif sec == "pva":
        await ask(cb, uid, "pv_add_name", "New provider: send its name (1-40 characters).")
    elif sec == "pvat":
        st = PENDING.get(uid)
        if st and st["act"] == "pv_add_type" and arg in ADAPTERS:
            await ask(cb, uid, "pv_add_url", f"Type <b>{esc(arg)}</b>. Now send the API base URL.", name=st["name"], type=arg)

    # media
    elif sec == "md":
        await (media_card(cb, arg) if arg in MEDIA_LABELS else media_list(cb))
    elif sec in ("mds", "mdr", "mdt", "mdp") and arg in MEDIA_LABELS:
        if sec == "mds":
            await ask(cb, uid, "md_set", f"<b>{esc(MEDIA_LABELS[arg])}</b>\nSend a direct URL ending in .jpg .jpeg .png .gif or .mp4 "
                      "(photos up to 5 MB, GIF/video up to 20 MB).", key=arg)
        elif sec == "mdr":
            await media_set(arg, "")
            await audit(uid, "media_remove", arg)
            await media_card(cb, arg, "✅ Removed. This screen is text only now.\n\n")
        elif sec == "mdt":
            await db.run("UPDATE media_settings SET enabled=1-enabled WHERE key=?", (arg,))
            await audit(uid, "media_toggle", arg)
            await media_card(cb, arg, "✅ Updated.\n\n")
        else:
            url = await media_url_raw(arg)
            BAD_MEDIA.pop(url, None)
            FILE_IDS.pop(url, None)
            try:
                sent = await send_with_media(uid, url, "🧪 Media test", None) if url else None
            except TelegramAPIError as ex:
                sent = None
                log.warning("media test error: %s", ex.__class__.__name__)
            await media_card(cb, arg, "✅ Telegram loaded the media (sent above).\n\n" if sent else
                             "❌ Telegram could not load this URL. Users would see text only.\n\n")

    # force join
    elif sec == "fj":
        await (fj_card(cb, n) if n else fj_list(cb))
    elif sec in ("fjt", "fjc", "fjm", "fjx", "fjX", "fje") and n:
        r = await db.one("SELECT * FROM force_join WHERE id=?", (n,))
        if not r:
            return await fj_list(cb)
        if sec == "fjt":
            await db.run("UPDATE force_join SET enabled=1-enabled WHERE id=?", (n,))
            JOIN_CACHE.clear()
            await audit(uid, "forcejoin_toggle", r["title"])
            await fj_card(cb, n, "✅ Updated.\n\n")
        elif sec == "fjc":
            try:
                chat = await bot.get_chat(r["chat_id"])
                me = await bot.get_chat_member(r["chat_id"], bot.id)
                good = me.status in ("administrator", "creator") or (me.status == "member" and chat.type != "channel")
                note = (f"{'✅' if good else '⚠️'} {esc(chat.title or r['chat_id'])}: bot status <b>{esc(me.status)}</b>"
                        + ("" if good else " - make the bot an admin so membership can be verified") + "\n\n")
            except TelegramAPIError as ex:
                note = f"❌ Bot cannot access this chat: {esc(str(ex)[:100])}\n\n"
            await fj_card(cb, n, note)
        elif sec == "fjm":
            try:
                cm = await bot.get_chat_member(r["chat_id"], uid)
                note = f"✅ Verification works. Your status there: <b>{esc(cm.status)}</b>\n\n"
            except TelegramAPIError as ex:
                note = f"❌ Verification failed (users are NOT blocked): {esc(str(ex)[:100])}\n\n"
            await fj_card(cb, n, note)
        elif sec == "fjx":
            await ascr(cb, head("REMOVE") + f"Remove <b>{esc(r['title'])}</b> from force join?", yes("", f"a:fjX:{n}", f"a:fj:{n}"))
        elif sec == "fjX":
            await db.run("DELETE FROM force_join WHERE id=?", (n,))
            JOIN_CACHE.clear()
            await audit(uid, "forcejoin_delete", r["title"])
            await fj_list(cb)
        elif sec == "fje" and extra in FJ_COL:
            await ask(cb, uid, "fj_edit", f"<b>{esc(r['title'])}</b>\nSend the new {extra}.", id=n, field=extra)
    elif sec == "fja":
        await ask(cb, uid, "fj_add_title", "New requirement: send the button title (1-40 characters), e.g. Our Channel.")
    elif sec == "fjak":
        st = PENDING.get(uid)
        if st and st["act"] == "fj_add_kind" and arg in ("channel", "group"):
            await ask(cb, uid, "fj_add_chat", f"{esc(arg).title()} <b>{esc(st['title'])}</b>.\nSend the chat @username or numeric ID "
                      "(private chats need -100…).", title=st["title"], kind=arg)

    # settings
    elif sec == "st":
        await settings_list(cb)
    elif sec == "stm":
        await set_setting("maintenance", "0" if S("maintenance") == "1" else "1")
        await audit(uid, "maintenance", S("maintenance"))
        await settings_list(cb)
    elif sec == "sts" and arg in SETTING_META:
        kind, lo, hi, label = SETTING_META[arg]
        rng = f"{lo} to {hi}" if kind == "int" else f"{lo}-{hi} characters"
        await ask(cb, uid, "st_edit", f"<b>{esc(label)}</b>\nCurrent: <code>{esc(S(arg)) or '-'}</code>\nSend the new value ({rng}).", key=arg)

    # users
    elif sec == "us":
        await (user_card(cb, n) if n else users_menu(cb))
    elif sec == "uss":
        await ask(cb, uid, "us_search", "Send a Telegram ID, @username or part of a name.")
    elif sec == "usr":
        await users_pick(cb, await db.all("SELECT * FROM users ORDER BY last_seen DESC LIMIT 10"), "Most recently active users:")
    elif sec == "usc":
        rows = await db.all("SELECT * FROM users ORDER BY id")
        await bot.send_document(uid, BufferedInputFile(users_csv(rows), filename=f"users-{now()}.csv"), caption=f"📤 {len(rows)} users")
        await audit(uid, "export_users", str(len(rows)))
    elif sec in ("usbq", "usb", "usx", "usX", "use") and n:
        if sec == "usbq":
            await ascr(cb, head("BAN") + f"Ban user <code>{n}</code>? They will lose access to the bot.", yes("", f"a:usb:{n}:1", f"a:us:{n}"))
        elif sec == "usb":
            if extra == "1" and n in ADMIN_SET:
                return await user_card(cb, n, "⚠️ Admins cannot be banned.\n\n")
            await db.run("UPDATE users SET banned=? WHERE id=?", (1 if extra == "1" else 0, n))
            await audit(uid, "ban" if extra == "1" else "unban", str(n))
            await user_card(cb, n, "✅ Done.\n\n")
        elif sec == "usx":
            await ascr(cb, head("DELETE EMAILS") + f"Delete all active addresses of <code>{n}</code>?", yes("", f"a:usX:{n}", f"a:us:{n}"))
        elif sec == "usX":
            rows = await db.all("SELECT * FROM generated_emails WHERE user_id=? AND active=1", (n,))
            for r in rows:
                await kill_email(r)
            await audit(uid, "delete_user_emails", f"{n} x{len(rows)}")
            await user_card(cb, n, f"✅ Deleted {len(rows)} address(es).\n\n")
        else:
            rows = await db.all("SELECT * FROM generated_emails WHERE user_id=? ORDER BY id DESC LIMIT 15", (n,))
            text = head("EMAIL RECORDS") + ("\n".join(f"• <code>{esc(r['address'])}</code> · {'active' if is_alive(r) else 'closed'} · "
                                                      f"{fmt_ts(r['created_at'])}" for r in rows) or "No records.")
            await ascr(cb, text, kb([back(f"a:us:{n}")]))

    # admins (super only)
    elif sec in ("ad", "ada", "adx", "adX"):
        if not is_super(uid):
            return await ascr(cb, head("ADMINS") + "Only super admins can manage admins.", kb([back()]))
        if sec == "ad":
            await admins_list(cb)
        elif sec == "ada":
            await ask(cb, uid, "ad_add", "Send the Telegram user ID of the new admin.")
        elif sec == "adx" and n:
            r = await db.one("SELECT * FROM admins WHERE id=? AND tg_id IS NOT NULL", (n,))
            if r and not is_super(r["tg_id"]):
                await ascr(cb, head("ADMINS") + f"Remove admin <code>{r['tg_id']}</code>?", yes("", f"a:adX:{n}", "a:ad"))
            else:
                await admins_list(cb)
        elif sec == "adX" and n:
            r = await db.one("SELECT * FROM admins WHERE id=? AND tg_id IS NOT NULL", (n,))
            if r and not is_super(r["tg_id"]):
                await db.run("DELETE FROM admins WHERE id=?", (n,))
                await load_admins()
                await audit(uid, "admin_remove", str(r["tg_id"]))
            await admins_list(cb)

    # broadcast
    elif sec == "bc":
        await bc_start(cb, uid)
    elif sec == "bcx":
        if BCJOB["running"]:
            BCJOB["cancel"] = True
        await ascr(cb, head("BROADCAST") + "🛑 Cancelling… a summary follows.", kb([back()]))
    elif sec == "bcb":
        st = PENDING.get(uid)
        if not st or st["act"] != "bc_confirm":
            return await admin_home(cb)
        await ask(cb, uid, "bc_button", "Send the button as  Label | https://link  (label up to 30 characters), or - for no button.",
                  src_chat=st["src_chat"], src_msg=st["src_msg"])
    elif sec == "bcg":
        st = PENDING.pop(uid, None)
        if not st or st["act"] != "bc_confirm":
            return await admin_home(cb)
        if BCJOB["running"]:
            return await bc_start(cb, uid)
        prog = (cb.message.chat.id, cb.message.message_id)
        await audit(uid, "broadcast_start", f"msg {st['src_msg']}")
        await ascr(cb, head("BROADCAST") + "📤 Starting…", kb([btn("🛑 Cancel broadcast", "a:bcx")]))
        BCJOB["task"] = asyncio.create_task(broadcast_worker(uid, st["src_chat"], st["src_msg"], bc_markup(st["button"]), prog))

    # backup
    elif sec == "bk":
        if not is_super(uid):
            return await ascr(cb, head("BACKUP") + "Only super admins can download backups.", kb([back()]))
        await send_backup(cb, uid)


async def admin_text(m: Message):
    uid = m.from_user.id
    st = PENDING.get(uid)
    if not st or uid not in ADMIN_SET:
        PENDING.pop(uid, None)
        return
    if st["exp"] < now():
        PENDING.pop(uid, None)
        return await ascr(m, head("ADMIN") + "That request expired.", kb([ADMIN_HOME]))
    text = (m.text or "").strip()
    act = st["act"]
    again = kb([btn("✖️ Cancel", "a:cancel")])
    try:
        if act != "bc_msg" and not text:
            raise ValueError("Please send a text message")
        if act == "pv_edit":
            await pv_apply(st["id"], st["field"], text)
            if st["field"] == "key":
                await _drop(m)
            PENDING.pop(uid, None)
            await audit(uid, "provider_edit", f"{st['id']}:{st['field']}")
            await prov_card(m, st["id"], "✅ Saved.\n\n")
        elif act == "pv_add_name":
            if not 1 <= len(text) <= 40:
                raise ValueError("Name must be 1-40 characters")
            if await db.one("SELECT id FROM providers WHERE name=?", (text,)):
                raise ValueError("A provider with that name already exists")
            PENDING[uid] = {"act": "pv_add_type", "exp": now() + 600, "name": text}
            await ascr(m, head("ADMIN") + f"Name <b>{esc(text)}</b>. Pick the API type:\n<i>Only mail.tm-compatible and 1secmail-compatible APIs "
                       "work without code; any other API needs a custom adapter written in Python.</i>",
                       kb([btn(t, f"a:pvat:{t}") for t in ADAPTERS], [btn("✖️ Cancel", "a:cancel")]))
        elif act == "pv_add_url":
            u = text.rstrip("/")
            if not valid_http_url(u):
                raise ValueError("Send a valid http(s) URL")
            prio = ((await db.one("SELECT COALESCE(MAX(priority),0) m FROM providers"))["m"] or 0) + 1
            pid = await db.run("INSERT INTO providers(name,api_type,base_url,priority) VALUES(?,?,?,?)", (st["name"], st["type"], u, min(prio, 9999)))
            PENDING.pop(uid, None)
            await audit(uid, "provider_add", st["name"])
            await prov_card(m, pid, "✅ Added. Tap Test to check the connection; add an API key / config from here if the API needs one.\n\n")
        elif act == "md_set":
            if not media_url_ok(text):
                raise ValueError("URL must be http(s) and end with .jpg .jpeg .png .gif or .mp4")
            await media_set(st["key"], text)
            PENDING.pop(uid, None)
            await audit(uid, "media_set", st["key"])
            await media_card(m, st["key"], "✅ Saved. Tap Test to confirm Telegram can load it.\n\n")
        elif act == "fj_add_title":
            PENDING[uid] = {"act": "fj_add_kind", "exp": now() + 600, "title": fj_validate("title", text)}
            await ascr(m, head("ADMIN") + "Is it a channel or a group?",
                       kb([btn("📢 Channel", "a:fjak:channel"), btn("👥 Group", "a:fjak:group")], [btn("✖️ Cancel", "a:cancel")]))
        elif act == "fj_add_chat":
            await ask(m, uid, "fj_add_link", "Send the join link (https://t.me/… or a private invite link).",
                      title=st["title"], kind=st["kind"], chat=fj_validate("chat", text))
        elif act == "fj_add_link":
            link = fj_validate("link", text)
            fid = await db.run("INSERT INTO force_join(title,kind,chat_id,link,enabled) VALUES(?,?,?,?,1)", (st["title"], st["kind"], st["chat"], link))
            PENDING.pop(uid, None)
            JOIN_CACHE.clear()
            await audit(uid, "forcejoin_add", st["title"])
            await fj_card(m, fid, "✅ Added. Run “Check bot permission” to confirm the bot can verify members.\n\n")
        elif act == "fj_edit":
            val = fj_validate(st["field"], text)
            await db.run(f"UPDATE force_join SET {FJ_COL[st['field']]}=? WHERE id=?", (val, st["id"]))
            PENDING.pop(uid, None)
            JOIN_CACHE.clear()
            await audit(uid, "forcejoin_edit", f"{st['id']}:{st['field']}")
            await fj_card(m, st["id"], "✅ Saved.\n\n")
        elif act == "st_edit":
            val = validate_setting(st["key"], text)
            await set_setting(st["key"], val)
            PENDING.pop(uid, None)
            await audit(uid, "setting", st["key"])
            await settings_list(m)
        elif act == "us_search":
            q = text.lstrip("@")[:64]
            PENDING.pop(uid, None)
            if q.isdigit():
                rows = await db.all("SELECT * FROM users WHERE id=?", (int(q),))
            else:
                like = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
                rows = await db.all("SELECT * FROM users WHERE username LIKE ? ESCAPE '\\' OR first_name LIKE ? ESCAPE '\\' "
                                    "ORDER BY last_seen DESC LIMIT 10", (like, like))
            await users_pick(m, rows, f"Matches for “{esc(q)}”:")
        elif act == "ad_add":
            if not is_super(uid):
                PENDING.pop(uid, None)
                return
            n = to_int(text, 1, 2 ** 62)
            if n is None:
                raise ValueError("Send a numeric Telegram user ID")
            await db.run("INSERT OR IGNORE INTO admins(tg_id,created_at) VALUES(?,?)", (n, now()))
            await load_admins()
            PENDING.pop(uid, None)
            await audit(uid, "admin_add", str(n))
            await admins_list(m)
        elif act == "bc_msg":
            await bc_review(m, uid, m.chat.id, m.message_id, None)
        elif act == "bc_button":
            button = None
            if text != "-":
                label, _, link = (x.strip() for x in text.partition("|"))
                if not 1 <= len(label) <= 30 or not valid_http_url(link):
                    raise ValueError("Format: Label | https://link  (label up to 30 characters)")
                button = (label, link)
            await bc_review(m, uid, st["src_chat"], st["src_msg"], button)
        else:
            PENDING.pop(uid, None)
    except ValueError as ex:
        await ascr(m, head("ADMIN") + f"⚠️ {esc(ex)}\nTry again, or cancel.", again)


# ------------------------------------------------------------------ startup / shutdown
bot_username = "?"


def check_config():
    if ":" not in BOT_TOKEN:
        sys.exit("CONFIG error: set the BOT_TOKEN environment variable (see .env.example)")


async def main():
    global bot, bot_username
    check_config()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("aiohttp.access").setLevel(logging.WARNING)
    await db.start(DB_PATH)
    await init_data()
    prov.http = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=HTTP_TIMEOUT),
                                      connector=aiohttp.TCPConnector(limit=50, ttl_dns_cache=300))
    bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML, link_preview_is_disabled=True))
    tasks = []
    try:
        me = await bot.get_me()
        bot_username = me.username or "?"
        await bot.delete_webhook(drop_pending_updates=False)
        router = Router()
        router.message.register(cmd_start, Command("start"))
        router.message.register(cmd_help, Command("help"))
        router.message.register(cmd_admin, Command("admin"))
        router.callback_query.register(admin_cb, lambda cb: (cb.data or "").startswith("a:"))
        router.callback_query.register(handle_callback)
        router.message.register(admin_text, lambda m: bool(m.from_user) and m.from_user.id in PENDING
                                and m.chat.type == "private")
        dp = Dispatcher()
        dp.include_router(router)
        dp.errors.register(on_error)

        log.info("Bot @%s running.", bot_username)

        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, stop.set)
            except (NotImplementedError, RuntimeError):
                pass
        poll = asyncio.create_task(dp.start_polling(bot, handle_signals=False, close_bot_session=False,
                                                    allowed_updates=["message", "callback_query"]))
        poll.add_done_callback(lambda t: stop.set())
        tasks = [poll, asyncio.create_task(prov.health_loop()), asyncio.create_task(cleanup_loop())]
        await stop.wait()
        log.info("Shutting down…")
        try:
            await dp.stop_polling()
        except RuntimeError:
            pass
    finally:
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await bot.session.close()
        await prov.http.close()
        await db.close()
        log.info("Stopped.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
