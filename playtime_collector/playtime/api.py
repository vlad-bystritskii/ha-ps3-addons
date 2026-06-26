"""HTTP API. Serves accumulated playtime and accepts pushed events.

The poll loop runs as a background task started on app startup.
"""
import asyncio
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
from fastapi import FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse
from contextlib import asynccontextmanager

from . import config, db, ps3, trophies
from . import dashboard as dashpage
from .poller import (
    poll_loop, trophy_loop, rarity_loop, summary_loop, plugin_sync_loop,
    avatar_path, cache_avatar, game_icon_path, cache_game_icon,
)
from .vita import vita_sync_loop

log = logging.getLogger("playtime")


@asynccontextmanager
async def lifespan(app):
    config.migrate_to_share()  # keep history when reinstalling / switching install type
    db.init_db()
    db.apply_title_overrides(config.TITLE_OVERRIDES)
    log.info("playtime-collector starting · PS3 %s · source %s · poll %ss · %d title override(s)",
             config.PS3_HOST or "(unset)", config.PLAYTIME_SOURCE, config.POLL_INTERVAL,
             len(config.TITLE_OVERRIDES))
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
    # PS Vita: pull its FTP session queue (separate console, runs if configured).
    if config.VITA_HOST:
        log.info("vita poller on · ftp %s:%s · account %s",
                 config.VITA_HOST, config.VITA_PORT, config.VITA_ACCOUNT)
        tasks.append(asyncio.create_task(vita_sync_loop()))
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


def platform_distribution(platform=None, frm=None, to=None, accounts=None):
    """[{platform, seconds, sessions, pct}] over the scoped range; pct is the
    share of total played time, one decimal. Empty when nothing is in range."""
    rows = db.platform_totals(platform, frm, to, accounts)
    total = sum((r["seconds"] or 0) for r in rows)
    return [
        {
            "platform": r["platform"],
            "seconds": r["seconds"] or 0,
            "sessions": r["sessions"],
            "pct": round((r["seconds"] or 0) * 100 / total, 1) if total else 0.0,
        }
        for r in rows
    ]


def build_stats(platform=None, frm=None, to=None, accounts=None):
    open_rows = db.open_sessions(platform, accounts)
    open_keys = {(r["platform"], r["account"], r["title_id"]) for r in open_rows}
    games = [game_entry(row, open_keys) for row in db.totals(platform, frm, to, accounts)]
    return {
        "generatedAt": db.now_iso(),
        "trackedSince": db.get_meta("tracked_since"),
        "lastPollAt": db.get_meta("last_poll_at"),
        "range": {"from": frm, "to": to},
        "summary": db.summary(platform, frm, to, accounts),
        "platformDistribution": platform_distribution(platform, frm, to, accounts),
        "currentlyPlaying": [game_entry(row, open_keys) for row in open_rows],
        "games": games,
    }


# ---- period-bucketed chart series ------------------------------------------
# Buckets sessions by start time into a fixed series per period. Boundaries are
# computed in the host's local time (started_at is stored UTC-aware, so it is
# converted on the way in); a whole session's seconds land in its start bucket.

_WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
_PERIODS = ("today", "week", "month", "year", "all")


def _local_now():
    return datetime.now(timezone.utc).astimezone()


def _to_local(iso):
    """Parse a stored ISO timestamp to a local-time datetime (None if unparsable)."""
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        return dt  # naive: assume already local
    return dt.astimezone()


def _utc_iso(dt):
    return dt.astimezone(timezone.utc).isoformat()


def _bucket_plan(period):
    """(start_local, end_local, labels, index_fn) for the calendar-anchored
    periods. 'all' is handled separately (its span depends on the data)."""
    now = _local_now()
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if period == "today":
        end = midnight + timedelta(days=1)
        return midnight, end, ["%02d" % h for h in range(24)], lambda dt: dt.hour
    if period == "week":
        start = midnight - timedelta(days=midnight.weekday())
        return start, start + timedelta(days=7), list(_WEEKDAYS), \
            lambda dt: (dt.date() - start.date()).days
    if period == "month":
        start = midnight.replace(day=1)
        end = start.replace(year=start.year + 1, month=1) if start.month == 12 \
            else start.replace(month=start.month + 1)
        days = (end - start).days
        return start, end, [str(d) for d in range(1, days + 1)], lambda dt: dt.day - 1
    # year
    start = midnight.replace(month=1, day=1)
    return start, start.replace(year=start.year + 1), list(_MONTHS), \
        lambda dt: dt.month - 1


def build_chart(period="week", platform=None, accounts=None):
    """{period, bars:[{label, value_seconds}], total_seconds, peak:{label,
    value_seconds}}. period in today|week|month|year|all."""
    period = (period or "week").lower()
    if period not in _PERIODS:
        raise HTTPException(status_code=400, detail="invalid period")

    if period == "all":
        rows = db.session_times(platform, None, None, accounts)
        local = [(_to_local(r["started_at"]), r["seconds"] or 0) for r in rows]
        years = [dt.year for dt, _ in local if dt]
        ymin = min(years) if years else _local_now().year
        ymax = max(years) if years else ymin
        labels = [str(y) for y in range(ymin, ymax + 1)]
        values = [0] * len(labels)
        for dt, sec in local:
            if dt:
                values[dt.year - ymin] += sec
    else:
        start, end, labels, index_fn = _bucket_plan(period)
        rows = db.session_times(platform, _utc_iso(start), _utc_iso(end), accounts)
        values = [0] * len(labels)
        for r in rows:
            dt = _to_local(r["started_at"])
            if dt is None:
                continue
            i = index_fn(dt)
            if 0 <= i < len(values):
                values[i] += r["seconds"] or 0

    bars = [{"label": l, "value_seconds": v} for l, v in zip(labels, values)]
    peak = max(bars, key=lambda b: b["value_seconds"]) if bars else None
    return {
        "period": period,
        "bars": bars,
        "total_seconds": sum(values),
        "peak": peak,
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
    troph = sorted(db.query_trophies(None, None),
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


# Static UI pages built by the front-end. Served as siblings of "/" so the
# navbar's relative ./people and ./config (and the pages' relative fetches to
# persons/links/settings) resolve correctly under HA ingress. Left open, like the
# "/" dashboard and the image routes — the pages carry no token.
TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"


def _serve_template(name):
    path = TEMPLATES_DIR / name
    try:
        return HTMLResponse(path.read_text(encoding="utf-8"))
    except OSError:
        raise HTTPException(status_code=404, detail="page not available")


@app.get("/people", response_class=HTMLResponse)
def people_page():
    return _serve_template("people.html")


@app.get("/config", response_class=HTMLResponse)
def config_page():
    return _serve_template("config.html")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/stats")
def stats(
    from_: str | None = Query(default=None, alias="from"),
    to: str | None = Query(default=None),
    person: int | None = Query(default=None),
    x_auth_token: str | None = Header(default=None),
):
    """Playtime totals across all platforms. With `?person=<id>` the totals are
    restricted to that person's linked accounts (across every platform)."""
    check_auth(x_auth_token)
    accounts = None
    if person is not None:
        if db.get_person(person) is None:
            raise HTTPException(status_code=404, detail="unknown person")
        accounts = db.accounts_for_person(person)
    return build_stats(None, from_, to, accounts)


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


def _resolve_accounts(person):
    """Map ?person=<id> to its (platform, account) pairs (404 if unknown).
    None when no person filter is requested."""
    if person is None:
        return None
    if db.get_person(person) is None:
        raise HTTPException(status_code=404, detail="unknown person")
    return db.accounts_for_person(person)


@app.get("/chart")
def chart(
    period: str = Query(default="week"),
    person: int | None = Query(default=None),
    platform: str | None = Query(default=None),
    x_auth_token: str | None = Header(default=None),
):
    """Period-bucketed playtime series for the dashboard chart.

    ?period=today|week|month|year|all (+ optional ?person=<id> and ?platform).
    today→24 hourly bars, week→7 weekday bars (current Mon–Sun), month→one bar
    per day of the current month, year→12 monthly bars, all→one bar per year.
    Returns {period, bars:[{label, value_seconds}], total_seconds,
    peak:{label, value_seconds}}.
    """
    check_auth(x_auth_token)
    accounts = _resolve_accounts(person)
    return build_chart(period, platform, accounts)


@app.get("/games/{platform}/{title_id}")
def game_detail(
    platform: str,
    title_id: str,
    x_auth_token: str | None = Header(default=None),
):
    """Per-game detail across every account that played it.

    {title, platform, titleId, totalSeconds, sessions, avgSession, firstPlayed,
     lastPlayed,
     players:[{account, person, personId, seconds, sessions, trophies, lastPlayed}],
     trophies:[{id, name, desc, grade, hidden, unlocked, earnedAt, rarityPct}]}

    Trophies are matched to the game by platform + title (PS3 trophy sets are
    keyed by npcommid); platforms without trophies return an empty list."""
    check_auth(x_auth_token)
    players_rows = db.game_players(platform, title_id)
    if not players_rows:
        raise HTTPException(status_code=404, detail="unknown game")

    pmap = db.account_person_map()
    accounts = [r["account"] for r in players_rows]
    title = next((r["title"] for r in players_rows if r["title"]), None)
    total = sum((r["total_seconds"] or 0) for r in players_rows)
    sessions = sum(r["sessions"] for r in players_rows)
    firsts = [r["first_played"] for r in players_rows if r["first_played"]]
    lasts = [r["last_played"] for r in players_rows if r["last_played"]]

    # Trophy sets that belong to this game (same platform + title), per account.
    sets = [s for s in db.query_trophies(platform, None)
            if s["title"] == title and s["account"] in accounts]
    earned_by_acct = {}
    npcommids = []
    for s in sets:
        earned_by_acct[s["account"]] = max(
            earned_by_acct.get(s["account"], 0), s["earnedCount"])
        if s["npcommid"] not in npcommids:
            npcommids.append(s["npcommid"])

    players = []
    for r in players_rows:
        person = pmap.get((platform, r["account"]))
        players.append({
            "account": r["account"],
            "person": person["name"] if person else None,
            "personId": person["id"] if person else None,
            "seconds": r["total_seconds"] or 0,
            "sessions": r["sessions"],
            "trophies": earned_by_acct.get(r["account"], 0),
            "lastPlayed": r["last_played"],
        })

    return {
        "title": title,
        "platform": platform,
        "titleId": title_id,
        "totalSeconds": total,
        "sessions": sessions,
        "avgSession": int(total / sessions) if sessions else 0,
        "firstPlayed": min(firsts) if firsts else None,
        "lastPlayed": max(lasts) if lasts else None,
        "players": players,
        "trophies": _game_trophies(platform, npcommids, accounts),
    }


def _game_trophies(platform, npcommids, accounts):
    """Union the trophy definitions for a game across the players who own the
    set: unlocked = anyone unlocked it, earnedAt = earliest unlock, rarityPct =
    global PSN rate. Empty list when there are no trophy sets (e.g. psvita)."""
    out = []
    for npcommid in npcommids:
        rarity = db.get_rarity(npcommid)
        agg = {}
        for acct in accounts:
            for it in db.query_trophy_items(platform, acct, npcommid):
                tid = it["id"]
                cur = agg.get(tid)
                if cur is None:
                    info = rarity.get(tid)
                    agg[tid] = {
                        "id": tid,
                        "name": it["name"],
                        "desc": it["detail"],
                        "grade": it["grade"],
                        "hidden": it["hidden"],
                        "unlocked": bool(it["unlocked"]),
                        "earnedAt": it["earnedAt"],
                        "rarityPct": info["earned_rate"] if info else None,
                        # Relative (no leading slash) for HA ingress; served by
                        # GET /trophy-icon/{account}/{npcommid}/{trophy_id}.
                        "iconUrl": "trophy-icon/%s/%s/%d" % (acct, npcommid, tid),
                    }
                elif it["unlocked"]:
                    cur["unlocked"] = True
                    if it["earnedAt"] and (cur["earnedAt"] is None
                                           or it["earnedAt"] < cur["earnedAt"]):
                        cur["earnedAt"] = it["earnedAt"]
        out.extend(sorted(agg.values(), key=lambda t: t["id"]))
    return out


@app.get("/history")
def history(
    person: int | None = Query(default=None),
    platform: str | None = Query(default=None),
    type: str = Query(default="all"),
    limit: int = Query(default=200),
    x_auth_token: str | None = Header(default=None),
):
    """Merged session + trophy activity feed, newest first.

    ?type=all|session|trophy, optional ?person=<id> and ?platform, ?limit.
    Each item: {kind:"session"|"trophy", datetime, title, platform, account,
    person, personId, ...}. Sessions add titleId, endedAt, durationSeconds,
    isOpen; trophies add name, detail, grade, rarityPct."""
    check_auth(x_auth_token)
    accounts = _resolve_accounts(person)
    typ = (type or "all").lower()
    if typ not in ("all", "session", "trophy"):
        raise HTTPException(status_code=400, detail="invalid type")

    pmap = db.account_person_map()
    items = []

    if typ in ("all", "session"):
        for s in db.session_history(platform, accounts, limit):
            who = pmap.get((s["platform"], s["account"]))
            items.append({
                "kind": "session",
                "datetime": s["started_at"],
                "endedAt": s["ended_at"],
                "title": s["title"],
                "titleId": s["title_id"],
                "platform": s["platform"],
                "account": s["account"],
                "person": who["name"] if who else None,
                "personId": who["id"] if who else None,
                "durationSeconds": s["seconds"],
                "isOpen": bool(s["is_open"]),
            })

    if typ in ("all", "trophy"):
        for t in db.trophy_history(platform, accounts, limit):
            who = pmap.get((t["platform"], t["account"]))
            item = {
                "kind": "trophy",
                "datetime": t["earned_at"],
                "title": t["game"],
                "name": t["name"],
                "detail": t["detail"],
                "grade": t["grade"],
                "platform": t["platform"],
                "account": t["account"],
                "person": who["name"] if who else None,
                "personId": who["id"] if who else None,
                "rarityPct": t["earned_rate"],
            }
            # Relative (no leading slash) for HA ingress; served by
            # GET /trophy-icon/{account}/{npcommid}/{trophy_id}. Omitted if a
            # trophy somehow lacks account/npcommid (shouldn't for PS3).
            if t["account"] and t["npcommid"]:
                item["iconUrl"] = "trophy-icon/%s/%s/%d" % (
                    t["account"], t["npcommid"], t["trophy_id"])
            items.append(item)

    items.sort(key=lambda x: x["datetime"] or "", reverse=True)
    return {"history": items[:limit]}


@app.get("/trophies")
def trophies_list(
    account: str | None = Query(default=None),
    platform: str | None = Query(default=None),
    x_auth_token: str | None = Header(default=None),
):
    check_auth(x_auth_token)
    return {
        "refreshedAt": db.get_meta("trophies_refreshed_at"),
        "trophies": db.query_trophies(platform, account),
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
    """Every trophy of a player, across all games and platforms (from storage)."""
    check_auth(x_auth_token)
    sets = db.query_trophies(None, account)
    if not sets:
        raise HTTPException(status_code=404, detail="unknown account")
    for entry in sets:
        items = db.query_trophy_items(entry["platform"], account, entry["npcommid"])
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
    items = db.query_trophy_items(None, account, npcommid)
    if not items:
        raise HTTPException(status_code=404, detail="unknown account/game")
    sets = db.query_trophies(None, account)
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


def _img_media_type(data):
    return "image/png" if data[:8] == b"\x89PNG\r\n\x1a\n" else "image/jpeg"


@app.get("/game-icon/{title_id}")
async def game_icon(
    title_id: str,
    token: str | None = Query(default=None),
    x_auth_token: str | None = Header(default=None),
):
    """Game icon (console ICON0 / GameTDB cover). Served from disk cache; fetched +
    cached live on a miss. Open (no token) for the dashboard's <img> tags. 404 when
    no icon can be found (the dashboard falls back to the initials square)."""
    headers = {"Cache-Control": "max-age=604800"}
    path = game_icon_path(title_id)
    if not path.exists():
        async with httpx.AsyncClient() as client:
            await cache_game_icon(client, title_id)
    if path.exists():
        data = path.read_bytes()
        return Response(content=data, media_type=_img_media_type(data), headers=headers)
    raise HTTPException(status_code=404, detail="no icon")


@app.get("/icon")
def app_icon():
    """The add-on's own icon.png, for the web UI's favicon. Open (no token), like
    the other image routes. 404 if the icon isn't present in the image."""
    path = Path("/app/icon.png")
    try:
        data = path.read_bytes()
    except OSError:
        raise HTTPException(status_code=404, detail="no icon")
    return Response(content=data, media_type="image/png",
                    headers={"Cache-Control": "max-age=604800"})


@app.delete("/sessions")
def delete_sessions(
    account: str = Query(...),
    x_auth_token: str | None = Header(default=None),
):
    check_auth(x_auth_token)
    return {"deleted": db.delete_sessions(account)}


# ---- persons & account links -----------------------------------------------
# A "person" groups platform accounts so playtime can be aggregated across
# consoles. account_links enforces UNIQUE (platform, account).
#
# These management endpoints are intentionally open (no check_auth): the People
# page (/people) fetches them from the browser with no token, exactly like the
# open "/" dashboard and the /avatar and /game-icon image routes. The shared
# token guards the documented machine-facing API (/stats, /trophies, /sessions,
# /ingest), not the LAN web UI.

@app.get("/persons")
def persons_list():
    return {"persons": db.list_persons()}


@app.post("/persons")
async def persons_create(request: Request):
    """Body: {name}. Returns the created person."""
    body = await request.json()
    name = str(body.get("name", "")).strip()
    if not name:
        raise HTTPException(status_code=400, detail="name required")
    person_id = db.add_person(name)
    return {"id": person_id, "name": name, "links": []}


@app.delete("/persons/{person_id}")
def persons_delete(person_id: int):
    """Remove a person and all of their account links."""
    return {"deleted": db.delete_person(person_id)}


@app.get("/links")
def links_list(person: int | None = Query(default=None)):
    """All account links, optionally filtered by `?person=<id>`."""
    return {"links": db.list_links(person)}


@app.post("/links")
async def links_create(request: Request):
    """Body: {personId, platform, account}. Links an account to a person.
    409 if that (platform, account) is already linked."""
    body = await request.json()
    person_id = body.get("personId", body.get("person_id"))
    platform = str(body.get("platform", "")).strip()
    account = str(body.get("account", "")).strip()
    if person_id is None or not platform or not account:
        raise HTTPException(status_code=400, detail="personId, platform and account required")
    person_id = int(person_id)
    if db.get_person(person_id) is None:
        raise HTTPException(status_code=404, detail="unknown person")
    if not db.add_link(person_id, platform, account):
        raise HTTPException(status_code=409, detail="account already linked")
    return {"ok": True, "link": {"person_id": person_id, "platform": platform, "account": account}}


@app.delete("/links")
def links_delete(
    platform: str = Query(...),
    account: str = Query(...),
):
    """Unlink an account, identified by its unique (platform, account)."""
    return {"deleted": db.delete_link(platform, account)}


# ---- settings (in-app config editor) ---------------------------------------
# Mirrors the add-on options the front-end Settings page (/config) edits. Open,
# like the page that consumes it. Option names/types match config.yaml's schema.

# The add-on option keys this editor exposes (in config.yaml's `schema`).
_SETTING_KEYS = [
    "ps3_host", "playtime_source", "account", "ignore_accounts",
    "poll_interval", "trophy_interval", "auth_token", "psn_npsso",
    "title_overrides",
]


@app.get("/settings")
def settings_get():
    """Current effective add-on options, as the Settings page expects them."""
    return {
        "ps3_host": config.PS3_HOST,
        "playtime_source": config.PLAYTIME_SOURCE,
        "account": config.ACCOUNT,
        # schema type is `str` (comma-separated); config parsed it into a list.
        "ignore_accounts": ", ".join(config.IGNORE_ACCOUNTS),
        "poll_interval": config.POLL_INTERVAL,
        "trophy_interval": config.TROPHY_INTERVAL,
        "auth_token": config.AUTH_TOKEN,
        "psn_npsso": config.PSN_NPSSO,
        # schema type is `list(str)`; config parsed it into a {match: replacement} map.
        "title_overrides": ["%s=%s" % (k, v) for k, v in config.TITLE_OVERRIDES.items()],
    }


def _options_from_body(body):
    """Pick only known option keys from the posted JSON (drops anything else)."""
    opts = {}
    for key in _SETTING_KEYS:
        if key in body and body[key] is not None:
            opts[key] = body[key]
    return opts


def _write_options_file(opts):
    """Persist options by merging into /data/options.json (the file config.py
    reads on startup), preserving any keys this editor doesn't manage."""
    path = config.OPTIONS_FILE
    current = {}
    if path.exists():
        try:
            current = json.loads(path.read_text())
        except (ValueError, OSError):
            current = {}
    current.update(opts)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(current, indent=2))


@app.post("/settings")
async def settings_save(request: Request):
    """Persist edited add-on options. Best-effort dual path, no privilege escalation:

    1. If a Supervisor token is present (env SUPERVISOR_TOKEN), try the Supervisor
       self-options API so HAOS stores them durably.
    2. On any failure (no token, 403 without hassio_api, network error) fall back
       to writing /data/options.json directly.

    NOTE: truly HAOS-persistent saving (surviving an add-on rebuild, editable from
    the add-on's own Configuration tab) needs `hassio_api: true` +
    `hassio_role: manager` in config.yaml. That is intentionally NOT added here —
    it would be a silent privilege escalation; the Supervisor call is best-effort.

    Config is read at process startup, so applied changes need an add-on restart.
    """
    body = await request.json()
    opts = _options_from_body(body)

    persisted = None
    token = os.environ.get("SUPERVISOR_TOKEN")
    if token:
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    "http://supervisor/addons/self/options",
                    json={"options": opts},
                    headers={"Authorization": "Bearer " + token},
                    timeout=10.0,
                )
            if resp.status_code < 400:
                persisted = "supervisor"
        except (httpx.HTTPError, OSError):
            persisted = None

    if persisted is None:
        _write_options_file(opts)
        persisted = "file"

    return {"ok": True, "persisted": persisted, "restart_required": True}


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
