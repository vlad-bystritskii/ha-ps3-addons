"""Polling loop: read the PS3 and turn snapshots into playtime sessions.

webMAN's own per-session "Play" timer is used as the session length when
available (accurate), otherwise we fall back to counting poll intervals.
"""
import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

from . import config, db, psn, trophies
from .ps3 import fetch_avatar, fetch_snapshot, list_profiles, resolve_username

log = logging.getLogger("playtime")

# Heartbeat: log "still playing" at most once per this many seconds of a session.
HEARTBEAT_SECONDS = 900
_last_heartbeat = 0

# Set by plugin_sync_loop when the on-console plugin log is present. While true the
# plugin is the source of truth for sessions and the LAN poller defers (no double count).
PLUGIN_ACTIVE = False


def fmt_dur(seconds):
    seconds = int(seconds or 0)
    h, m = seconds // 3600, (seconds % 3600) // 60
    if h:
        return "%dh%02dm" % (h, m)
    if m:
        return "%dm" % m
    return "%ds" % seconds


def close_active(platform, reason):
    """Close the open session (if any) and log how long it ran."""
    current = db.get_open_session(platform)
    if current:
        log.info("⏹ %s — %s · %s (%s)",
                 current["account"], current["title"] or current["title_id"],
                 fmt_dur(current["seconds"]), reason)
    db.close_open_sessions(platform)


def icon_path(account, npcommid, trophy_id):
    return Path(config.ICON_DIR) / account / npcommid / ("%d.png" % int(trophy_id))


async def cache_icon(client, profile_id, account, npcommid, trophy_id):
    """Save a trophy icon to disk so it stays available with the console off."""
    path = icon_path(account, npcommid, trophy_id)
    if path.exists():
        return
    try:
        png = await trophies.fetch_icon(config.PS3_HOST, client, profile_id, npcommid, trophy_id)
    except Exception:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(png)


def avatar_path(account):
    return Path(config.ICON_DIR) / "avatars" / (account + ".png")


async def cache_avatar(client, profile_id, account):
    """Save a profile's avatar to disk so it's served with the console off.

    Refetched only when missing — avatars change rarely and the cache is what
    keeps faces visible while the console is offline / lent out."""
    path = avatar_path(account)
    if path.exists():
        return
    try:
        png = await fetch_avatar(config.PS3_HOST, client, profile_id, account)
    except Exception:
        return
    if not png:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(png)


def handle_snapshot(snapshot, account):
    global _last_heartbeat
    platform = config.PLATFORM
    now = db.now_iso()

    # The on-console plugin is the source of truth for sessions; when it's active
    # the LAN poller must not also write sessions (would double count). It still
    # records liveness so /health reflects that we're reaching the console.
    if PLUGIN_ACTIVE:
        if snapshot.online:
            db.set_meta("last_poll_at", now)
        return

    # Offline (console off / HEN not enabled) or at the home menu: close any
    # running session so we never count time while nothing is playing.
    if not snapshot.online:
        close_active(platform, "offline")
        return

    db.set_meta("last_poll_at", now)

    if not snapshot.title_id:
        close_active(platform, "home menu")
        return

    # Skip untracked profiles (e.g. the technical "Vlad" account).
    if account in config.IGNORE_ACCOUNTS:
        close_active(platform, "ignored profile")
        return

    seconds = snapshot.play_seconds
    current = db.get_open_session(platform)

    same = (
        current is not None
        and current["account"] == account
        and current["title_id"] == snapshot.title_id
    )
    relaunched = same and seconds is not None and seconds < current["seconds"]

    if same and not relaunched:
        if seconds is None:
            seconds = current["seconds"] + config.POLL_INTERVAL
        db.update_open_session(current["id"], seconds, snapshot.title, now)
        if seconds - _last_heartbeat >= HEARTBEAT_SECONDS:
            log.info("… %s playing %s · %s",
                     account, snapshot.title or snapshot.title_id, fmt_dur(seconds))
            _last_heartbeat = seconds
    else:
        # New game, or the active profile changed -> start a fresh session.
        if current:
            log.info("⏹ %s — %s · %s (switched)",
                     current["account"], current["title"] or current["title_id"],
                     fmt_dur(current["seconds"]))
        db.open_session(platform, account, snapshot.title_id, snapshot.title, seconds or 0, now)
        _last_heartbeat = seconds or 0
        log.info("▶ %s started %s (%s)",
                 account, snapshot.title or snapshot.title_id, snapshot.title_id)


async def poll_loop(client):
    log.info("polling %s every %ss", config.PS3_HOST or "(no host set)", config.POLL_INTERVAL)
    while True:
        try:
            snapshot = await fetch_snapshot(config.PS3_HOST, client)
            account = config.ACCOUNT
            if snapshot.online and snapshot.title_id and snapshot.profile_id:
                name = await resolve_username(config.PS3_HOST, client, snapshot.profile_id)
                if name:
                    account = name
            handle_snapshot(snapshot, account)
        except Exception:  # never let the loop die
            log.exception("poll failed")
        await asyncio.sleep(config.POLL_INTERVAL)


PLUGIN_BASE = "http://%s/dev_hdd0/playtime/"


async def _resolve_account(client, account_field):
    """Map a plugin 'account' (the home/<id> 8-digit) to a username; fall back."""
    home_id = str(account_field or "")
    if home_id.isdigit():
        name = await resolve_username(config.PS3_HOST, client, home_id)
        if name:
            return name
        return "ps3-" + home_id
    return home_id or config.ACCOUNT


async def ingest_sessions(client):
    """Pull the plugin's append-only sessions.jsonl and store new lines.

    Returns True if the plugin log is reachable (=> plugin is the source of truth).
    A byte offset is kept in meta so each line is ingested exactly once.
    """
    try:
        resp = await client.get(PLUGIN_BASE % config.PS3_HOST + "sessions.jsonl", timeout=10.0)
    except (httpx.HTTPError, OSError):
        return False
    if resp.status_code == 404:
        return False  # plugin not installed / nothing logged yet
    resp.raise_for_status()

    data = resp.content
    offset = int(db.get_meta("plugin_offset") or 0)
    if len(data) < offset:
        offset = 0  # log was reset (e.g. plugin reinstalled)

    chunk = data[offset:]
    cut = chunk.rfind(b"\n")
    if cut < 0:
        return True  # no complete new line yet

    inserted = 0
    for raw in chunk[:cut].split(b"\n"):
        raw = raw.strip()
        if not raw:
            continue
        try:
            s = json.loads(raw)
        except ValueError:
            continue
        seconds = int(s.get("seconds", 0))
        if seconds <= 0:
            continue
        account = await _resolve_account(client, s.get("account"))
        if account in config.IGNORE_ACCOUNTS:
            continue
        db.insert_closed_session(
            config.PLATFORM, account, s.get("titleId", "?"), s.get("title"), seconds, db.now_iso())
        inserted += 1
        log.info("⏹ %s — %s · %s (plugin)",
                 account, s.get("title") or s.get("titleId"), fmt_dur(seconds))

    db.set_meta("plugin_offset", str(offset + cut + 1))
    if inserted:
        log.info("ingested %d plugin session(s)", inserted)
    return True


async def ingest_current(client):
    """Mirror the plugin's current.json as the live 'currently playing' session."""
    try:
        resp = await client.get(PLUGIN_BASE % config.PS3_HOST + "current.json", timeout=10.0)
    except (httpx.HTTPError, OSError):
        return
    body = resp.content.strip() if resp.status_code == 200 else b""
    if not body:
        db.clear_live_session(config.PLATFORM)
        return
    try:
        s = json.loads(body)
    except ValueError:
        db.clear_live_session(config.PLATFORM)
        return
    account = await _resolve_account(client, s.get("account"))
    if account in config.IGNORE_ACCOUNTS:
        db.clear_live_session(config.PLATFORM)
        return
    db.set_live_session(
        config.PLATFORM, account, s.get("titleId", "?"), s.get("title"),
        int(s.get("seconds", 0)), db.now_iso())


async def plugin_sync_loop(client):
    """Sync the on-console plugin log into the DB. Idempotent; safe with the LAN poll."""
    global PLUGIN_ACTIVE
    log.info("plugin sync every %ss (%ssessions.jsonl)", config.PLUGIN_SYNC_INTERVAL,
             PLUGIN_BASE % config.PS3_HOST)
    while True:
        try:
            active = await ingest_sessions(client)
            if active and not PLUGIN_ACTIVE:
                log.info("on-console plugin detected — it is now the source of truth")
            elif PLUGIN_ACTIVE and not active:
                log.info("on-console plugin no longer reachable — LAN poller resumes")
            PLUGIN_ACTIVE = active
            if active:
                db.set_meta("last_poll_at", db.now_iso())
                await ingest_current(client)
        except Exception:
            log.exception("plugin sync failed")
        await asyncio.sleep(config.PLUGIN_SYNC_INTERVAL)


async def refresh_trophies(client):
    """Scan every tracked profile's trophy sets and store the summaries.

    Returns the number of profiles found. 0 means the listing came back empty
    (console busy / transient) — the caller should retry soon rather than treat
    it as a clean "nothing to do".
    """
    profiles = await list_profiles(config.PS3_HOST, client)
    if not profiles:
        log.warning("trophy scan found 0 profiles (console busy?) — will retry soon")
        return 0
    for profile_id, name in profiles:
        # Skip if the name didn't resolve: it gates the ignore-list, and we don't
        # want ugly ps3-<id> rows or to accidentally scan a technical account.
        if not name or name in config.IGNORE_ACCOUNTS:
            continue
        account = name
        await cache_avatar(client, profile_id, account)
        try:
            sets = await trophies.list_sets(config.PS3_HOST, client, profile_id)
        except Exception:
            continue
        for npcommid in sets:
            try:
                summary, items = await trophies.fetch_set_full(
                    config.PS3_HOST, client, profile_id, npcommid)
            except Exception:
                continue
            db.upsert_trophies(config.PLATFORM, account, summary)
            db.upsert_trophy_items(config.PLATFORM, account, summary["npcommid"], items)
            # Cache icons of earned trophies so they're served even when PS3 is off.
            for item in items:
                if item["unlocked"]:
                    await cache_icon(client, profile_id, account, summary["npcommid"], item["id"])
    db.set_meta("trophies_refreshed_at", db.now_iso())
    log.info("trophies refreshed for %s profile(s)", len(profiles))
    return len(profiles)


async def trophy_loop(client):
    while True:
        delay = config.TROPHY_INTERVAL
        try:
            # Only scan when the console is reachable (HEN on). If it's offline,
            # retry soon instead of waiting a full interval, so a console that
            # was off at startup gets scanned shortly after it comes up.
            if (await fetch_snapshot(config.PS3_HOST, client)).online:
                scanned = await refresh_trophies(client)
                if not scanned:
                    delay = min(120, config.TROPHY_INTERVAL)
            else:
                delay = min(300, config.TROPHY_INTERVAL)
        except Exception:
            log.exception("trophy refresh failed")
        await asyncio.sleep(delay)


async def refresh_rarity():
    """Enrich every known trophy set with global PSN rarity (needs NPSSO; internet,
    independent of the console). PSNAWP is sync, so run it in a thread."""
    if not config.PSN_NPSSO:
        return
    npcommids = db.distinct_npcommids()
    enriched = 0
    for npcommid in npcommids:
        try:
            rarity = await asyncio.to_thread(psn.fetch_title_rarity, config.PSN_NPSSO, npcommid)
        except Exception:
            log.exception("PSN rarity fetch failed for %s", npcommid)
            continue
        if rarity:
            db.upsert_rarity(npcommid, rarity)
            enriched += 1
    db.set_meta("rarity_refreshed_at", db.now_iso())
    log.info("rarity refreshed for %s/%s sets", enriched, len(npcommids))


async def rarity_loop():
    while True:
        delay = config.RARITY_INTERVAL
        try:
            if config.PSN_NPSSO and not db.distinct_npcommids():
                # Trophies not scanned yet — check back soon instead of waiting a day.
                delay = 120
            else:
                await refresh_rarity()
        except Exception:
            log.exception("rarity refresh failed")
        await asyncio.sleep(delay)


def log_daily_summary():
    since = (datetime.now(timezone.utc) - timedelta(seconds=config.SUMMARY_INTERVAL)).isoformat()
    totals = db.totals(frm=since)
    log.info("── last %s ──", fmt_dur(config.SUMMARY_INTERVAL))
    if totals:
        for row in totals:
            log.info("   %s · %s · %s",
                     row["account"], row["title"] or row["title_id"], fmt_dur(row["total_seconds"]))
    else:
        log.info("   no playtime")
    for account, count in db.trophies_earned_since(since):
        log.info("   %s · +%d trophies", account, count)


async def summary_loop():
    while True:
        await asyncio.sleep(config.SUMMARY_INTERVAL)
        try:
            log_daily_summary()
        except Exception:
            log.exception("summary failed")
