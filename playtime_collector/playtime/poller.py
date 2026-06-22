"""Polling loop: read the PS3 and turn snapshots into playtime sessions.

webMAN's own per-session "Play" timer is used as the session length when
available (accurate), otherwise we fall back to counting poll intervals.
"""
import asyncio
import logging
from pathlib import Path

from . import config, db, psn, trophies
from .ps3 import fetch_snapshot, list_profiles, resolve_username

log = logging.getLogger("playtime.poller")


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


def handle_snapshot(snapshot, account):
    platform = config.PLATFORM
    now = db.now_iso()

    # Offline (console off / HEN not enabled) or at the home menu: close any
    # running session so we never count time while nothing is playing.
    if not snapshot.online:
        db.close_open_sessions(platform)
        return

    db.set_meta("last_poll_at", now)

    if not snapshot.title_id:
        db.close_open_sessions(platform)
        return

    # Skip untracked profiles (e.g. the technical "Vlad" account).
    if account in config.IGNORE_ACCOUNTS:
        db.close_open_sessions(platform)
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
    else:
        # New game, or the active profile changed -> start a fresh session.
        db.open_session(platform, account, snapshot.title_id, snapshot.title, seconds or 0, now)


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


async def refresh_trophies(client):
    """Scan every tracked profile's trophy sets and store the summaries."""
    profiles = await list_profiles(config.PS3_HOST, client)
    for profile_id, name in profiles:
        # Skip if the name didn't resolve: it gates the ignore-list, and we don't
        # want ugly ps3-<id> rows or to accidentally scan a technical account.
        if not name or name in config.IGNORE_ACCOUNTS:
            continue
        account = name
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


async def trophy_loop(client):
    while True:
        delay = config.TROPHY_INTERVAL
        try:
            # Only scan when the console is reachable (HEN on). If it's offline,
            # retry soon instead of waiting a full interval, so a console that
            # was off at startup gets scanned shortly after it comes up.
            if (await fetch_snapshot(config.PS3_HOST, client)).online:
                await refresh_trophies(client)
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
