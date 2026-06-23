"""HTTP API. Serves accumulated playtime and accepts pushed events.

The poll loop runs as a background task started on app startup.
"""
import asyncio
import logging
from pathlib import Path

import httpx
from fastapi import FastAPI, Header, HTTPException, Query, Request, Response
from contextlib import asynccontextmanager

from . import config, db, ps3, trophies
from .poller import poll_loop, trophy_loop, rarity_loop, summary_loop, plugin_sync_loop

log = logging.getLogger("playtime")


@asynccontextmanager
async def lifespan(app):
    db.init_db()
    log.info("playtime-collector starting · PS3 %s · source %s · poll %ss",
             config.PS3_HOST or "(unset)", config.PLAYTIME_SOURCE, config.POLL_INTERVAL)
    client = httpx.AsyncClient()
    # Playtime source is selectable so each install runs only what it has.
    tasks = []
    if config.PLAYTIME_SOURCE in ("auto", "webman"):
        tasks.append(asyncio.create_task(poll_loop(client)))
    if config.PLAYTIME_SOURCE in ("auto", "plugin"):
        tasks.append(asyncio.create_task(plugin_sync_loop(client)))
    # Trophies + rarity are independent of the playtime source.
    tasks += [
        asyncio.create_task(trophy_loop(client)),
        asyncio.create_task(rarity_loop()),
        asyncio.create_task(summary_loop()),
    ]
    try:
        yield
    finally:
        for task in tasks:
            task.cancel()
        await client.aclose()


app = FastAPI(title="playtime-collector", lifespan=lifespan)


def check_auth(token):
    if config.AUTH_TOKEN and token != config.AUTH_TOKEN:
        raise HTTPException(status_code=401, detail="invalid token")


def game_entry(row, open_keys):
    key = (row["platform"], row["account"], row["title_id"])
    return {
        "key": row["platform"] + ":" + row["account"] + ":" + row["title_id"],
        "platform": row["platform"],
        "account": row["account"],
        "titleId": row["title_id"],
        "titleName": row["title"],
        "totalSeconds": row["total_seconds"],
        "sessions": row["sessions"],
        "firstPlayed": row.get("first_played"),
        "lastPlayed": row["last_played"],
        "playing": key in open_keys,
    }


def build_stats(platform=None, frm=None, to=None):
    open_rows = db.open_sessions(platform)
    open_keys = {(r["platform"], r["account"], r["title_id"]) for r in open_rows}
    games = [game_entry(row, open_keys) for row in db.totals(platform, frm, to)]
    return {
        "generatedAt": db.now_iso(),
        "trackedSince": db.get_meta("tracked_since"),
        "lastPollAt": db.get_meta("last_poll_at"),
        "range": {"from": frm, "to": to},
        "summary": db.summary(platform, frm, to),
        "currentlyPlaying": [game_entry(row, open_keys) for row in open_rows],
        "games": games,
    }


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/stats")
def stats(
    from_: str | None = Query(default=None, alias="from"),
    to: str | None = Query(default=None),
    x_auth_token: str | None = Header(default=None),
):
    check_auth(x_auth_token)
    return build_stats(None, from_, to)


@app.get("/stats/{platform}")
def stats_for_platform(
    platform: str,
    from_: str | None = Query(default=None, alias="from"),
    to: str | None = Query(default=None),
    x_auth_token: str | None = Header(default=None),
):
    check_auth(x_auth_token)
    return build_stats(platform, from_, to)


@app.get("/sessions")
def sessions(
    platform: str | None = Query(default=None),
    from_: str | None = Query(default=None, alias="from"),
    to: str | None = Query(default=None),
    limit: int = Query(default=500),
    x_auth_token: str | None = Header(default=None),
):
    check_auth(x_auth_token)
    return {"sessions": db.list_sessions(platform, from_, to, limit)}


@app.get("/trophies")
def trophies_list(
    account: str | None = Query(default=None),
    x_auth_token: str | None = Header(default=None),
):
    check_auth(x_auth_token)
    return {
        "refreshedAt": db.get_meta("trophies_refreshed_at"),
        "trophies": db.query_trophies(config.PLATFORM, account),
    }


def with_icons(account, npcommid, items):
    """Add the icon URL and global PSN rarity (if fetched) to each trophy item."""
    rarity = db.get_rarity(npcommid)
    for trophy in items:
        trophy["icon"] = "/trophy-icon/%s/%s/%d" % (account, npcommid, trophy["id"])
        info = rarity.get(trophy["id"])
        trophy["earnedRate"] = info["earned_rate"] if info else None
        trophy["rare"] = info["rare"] if info else None
    return items


@app.get("/trophies/{account}")
def trophy_detail_account(
    account: str,
    x_auth_token: str | None = Header(default=None),
):
    """Every trophy of a player, across all games (from storage; always available)."""
    check_auth(x_auth_token)
    sets = db.query_trophies(config.PLATFORM, account)
    if not sets:
        raise HTTPException(status_code=404, detail="unknown account")
    for entry in sets:
        items = db.query_trophy_items(config.PLATFORM, account, entry["npcommid"])
        entry["trophies"] = with_icons(account, entry["npcommid"], items)
    return {
        "account": account,
        "refreshedAt": db.get_meta("trophies_refreshed_at"),
        "sets": sets,
    }


@app.get("/trophies/{account}/{npcommid}")
def trophy_detail(
    account: str,
    npcommid: str,
    x_auth_token: str | None = Header(default=None),
):
    """Per-trophy detail for one game (from storage; always available)."""
    check_auth(x_auth_token)
    items = db.query_trophy_items(config.PLATFORM, account, npcommid)
    if not items:
        raise HTTPException(status_code=404, detail="unknown account/game")
    sets = db.query_trophies(config.PLATFORM, account)
    title = next((s["title"] for s in sets if s["npcommid"] == npcommid), None)
    return {
        "account": account,
        "npcommid": npcommid,
        "title": title,
        "trophies": with_icons(account, npcommid, items),
    }


@app.get("/trophy-icon/{account}/{npcommid}/{trophy_id}")
async def trophy_icon(
    account: str,
    npcommid: str,
    trophy_id: int,
    token: str | None = Query(default=None),
    x_auth_token: str | None = Header(default=None),
):
    """Trophy icon PNG. Served from disk cache; fetched + cached live on a miss."""
    check_auth(x_auth_token or token)
    headers = {"Cache-Control": "max-age=86400"}
    path = Path(config.ICON_DIR) / account / npcommid / ("%d.png" % trophy_id)
    if path.exists():
        return Response(content=path.read_bytes(), media_type="image/png", headers=headers)
    async with httpx.AsyncClient() as client:
        profile_id = await ps3.profile_id_for(config.PS3_HOST, client, account)
        if not profile_id:
            raise HTTPException(status_code=404, detail="unknown account")
        try:
            png = await trophies.fetch_icon(config.PS3_HOST, client, profile_id, npcommid, trophy_id)
        except (httpx.HTTPError, OSError):
            raise HTTPException(status_code=503, detail="PS3 unreachable and icon not cached")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(png)
    return Response(content=png, media_type="image/png", headers=headers)


@app.delete("/sessions")
def delete_sessions(
    account: str = Query(...),
    x_auth_token: str | None = Header(default=None),
):
    check_auth(x_auth_token)
    return {"deleted": db.delete_sessions(account)}


@app.post("/ingest")
async def ingest(request: Request, x_auth_token: str | None = Header(default=None)):
    """Accept a pushed playtime event from a non-PS3 platform (future use).

    Body: {platform, account, titleId, title, seconds}
    """
    check_auth(x_auth_token)
    body = await request.json()
    db.insert_closed_session(
        body["platform"],
        body.get("account", "default"),
        body["titleId"],
        body.get("title"),
        int(body.get("seconds", 0)),
        db.now_iso(),
    )
    return {"ok": True}
