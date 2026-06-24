"""HTTP API. Serves accumulated playtime and accepts pushed events.

The poll loop runs as a background task started on app startup.
"""
import asyncio
import logging
from pathlib import Path

import httpx
from fastapi import FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse
from contextlib import asynccontextmanager

from . import config, db, ps3, trophies
from . import dashboard as dashpage
from .poller import (
    poll_loop, trophy_loop, rarity_loop, summary_loop, plugin_sync_loop,
    avatar_path, cache_avatar,
)

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


# ---- web dashboard ---------------------------------------------------------

def _fmt_dur(s):
    s = int(s or 0)
    h, m = s // 3600, (s % 3600) // 60
    if h:
        return f"{h}h {m:02d}m"
    return f"{m}m" if m else f"{s}s"


def _esc(t):
    return (str(t or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


_DASH_CSS = """
:root{--bg:#0a0e1a;--panel:#121a2c;--panel2:#0d1422;--head:#142a4e;
--accent:#29c6e6;--blue:#2a9df4;--white:#e9f1ff;--dim:#8aa0c0;--barbg:#1c2740}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--white);
font:15px/1.4 -apple-system,Segoe UI,Roboto,sans-serif}
.wrap{max-width:920px;margin:0 auto;padding:16px}
.head{display:flex;align-items:center;gap:14px;border-left:6px solid var(--accent);
padding:10px 16px;background:var(--head);border-radius:10px}
.head h1{margin:0;font-size:24px;letter-spacing:.5px}
.head .sub{color:var(--dim);font-size:12px}
.chips{display:flex;gap:10px;flex-wrap:wrap;margin:14px 0}
.chip{background:var(--panel);border-radius:10px;padding:10px 14px;flex:1;min-width:120px}
.chip b{display:block;font-size:22px;color:var(--accent)}
.chip span{color:var(--dim);font-size:12px;text-transform:uppercase;letter-spacing:.5px}
h2{font-size:14px;color:var(--dim);text-transform:uppercase;letter-spacing:.6px;
margin:24px 0 10px}
.now{background:linear-gradient(90deg,#163a2a,#121a2c);border:1px solid #2e7d52;
border-radius:10px;padding:12px 16px;margin-bottom:8px}
.now .live{color:#37e08a;font-weight:600}
.row{background:var(--panel);border-radius:10px;padding:10px 14px;margin-bottom:8px}
.row .top{display:flex;justify-content:space-between;align-items:baseline;gap:10px}
.row .name{font-weight:600}
.row .who{color:var(--dim);font-size:12px}
.row .time{color:var(--accent);font-weight:600;white-space:nowrap}
.bar{height:8px;background:var(--barbg);border-radius:5px;margin-top:8px;overflow:hidden}
.bar i{display:block;height:100%;background:linear-gradient(90deg,var(--blue),var(--accent))}
.tp{display:flex;align-items:center;gap:10px;background:var(--panel);border-radius:10px;
padding:8px 14px;margin-bottom:6px}
.tp .name{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.tp .med{color:var(--dim);font-size:13px;white-space:nowrap}
.tp .pct{color:var(--accent);font-weight:600;width:54px;text-align:right}
.acct{margin:16px 0 6px;color:var(--white);font-weight:600}
.foot{color:var(--dim);font-size:11px;text-align:center;margin:24px 0 8px}
a{color:var(--accent)}
"""


def _render_dashboard():
    st = build_stats()
    games = sorted(st["games"], key=lambda g: g["totalSeconds"], reverse=True)
    maxs = max((g["totalSeconds"] for g in games), default=1) or 1
    summ = st["summary"]
    troph = sorted(db.query_trophies(config.PLATFORM, None),
                   key=lambda t: (t["account"], -t.get("earnedCount", 0)))

    out = ['<!doctype html><html lang="en"><head><meta charset="utf-8">',
           '<meta name="viewport" content="width=device-width,initial-scale=1">',
           '<meta http-equiv="refresh" content="30">',
           '<title>PS3 Playtime</title><style>', _DASH_CSS, '</style></head><body><div class="wrap">']

    out.append(f'<div class="head"><h1>🎮 PS3 PLAYTIME</h1>'
               f'<div class="sub">updated {_esc(st["generatedAt"])[:19]}<br>'
               f'last poll {_esc(st["lastPollAt"])[:19] if st["lastPollAt"] else "—"}</div></div>')

    out.append(f'<div class="chips">'
               f'<div class="chip"><b>{_fmt_dur(summ["seconds_total"])}</b><span>total played</span></div>'
               f'<div class="chip"><b>{summ["sessions_total"]}</b><span>sessions</span></div>'
               f'<div class="chip"><b>{len(games)}</b><span>games</span></div></div>')

    now = st["currentlyPlaying"]
    if now:
        out.append('<h2>Now playing</h2>')
        for g in now:
            out.append(f'<div class="now"><span class="live">● LIVE</span> '
                       f'<b>{_esc(g["titleName"])}</b> · {_esc(g["account"])} · '
                       f'{_fmt_dur(g["totalSeconds"])}</div>')

    out.append('<h2>Playtime by game</h2>')
    if not games:
        out.append('<div class="row">No sessions yet — play a game with the tracker loaded.</div>')
    for g in games:
        pct = int(g["totalSeconds"] * 100 / maxs)
        out.append(f'<div class="row"><div class="top">'
                   f'<div><span class="name">{_esc(g["titleName"])}</span> '
                   f'<span class="who">· {_esc(g["account"])} · {g["sessions"]} sess</span></div>'
                   f'<div class="time">{_fmt_dur(g["totalSeconds"])}</div></div>'
                   f'<div class="bar"><i style="width:{pct}%"></i></div></div>')

    if troph:
        out.append('<h2>Trophies</h2>')
        cur = None
        for t in troph:
            if t["account"] != cur:
                cur = t["account"]
                out.append(f'<div class="acct">👤 {_esc(cur)}</div>')
            e, tot = t.get("earnedCount", 0), t.get("totalCount", 0)
            pct = int(e * 100 / tot) if tot else 0
            ear = t.get("earned", {})
            med = (f'🥉{ear.get("bronze",0)} 🥈{ear.get("silver",0)} '
                   f'🥇{ear.get("gold",0)} 🏆{ear.get("platinum",0)}')
            out.append(f'<div class="tp"><span class="name">{_esc(t["title"])}</span>'
                       f'<span class="med">{med}</span>'
                       f'<span class="pct">{e}/{tot}</span>'
                       f'<span class="pct">{pct}%</span></div>')

    out.append('<div class="foot">PS3 Playtime Collector · auto-refresh 30s · '
               '<a href="/stats">/stats</a> · <a href="/trophies">/trophies</a></div>')
    out.append('</div></body></html>')
    return "".join(out)


@app.get("/", response_class=HTMLResponse)
@app.get("/dashboard", response_class=HTMLResponse)
def dashboard():
    return dashpage.render()


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
    """Trophy icon PNG. Served from disk cache; fetched + cached live on a miss.
    Left open (no token) so the dashboard's <img> tags can load icons."""
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


@app.get("/avatar/{account}")
async def avatar(
    account: str,
    token: str | None = Query(default=None),
    x_auth_token: str | None = Header(default=None),
):
    """Profile avatar PNG. Served from disk cache; fetched + cached live on a miss.
    Left open (no token) so the dashboard's <img> tags can load it. 404 when the
    console has no avatar for this profile (the dashboard falls back to initials)."""
    headers = {"Cache-Control": "max-age=86400"}
    path = avatar_path(account)
    if path.exists():
        return Response(content=path.read_bytes(), media_type="image/png", headers=headers)
    async with httpx.AsyncClient() as client:
        profile_id = await ps3.profile_id_for(config.PS3_HOST, client, account)
        if not profile_id:
            raise HTTPException(status_code=404, detail="unknown account")
        await cache_avatar(client, profile_id, account)
    if path.exists():
        return Response(content=path.read_bytes(), media_type="image/png", headers=headers)
    raise HTTPException(status_code=404, detail="no avatar")


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
