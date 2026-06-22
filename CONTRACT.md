# API Contract

Everything below is served by the collector on HAOS. All endpoints answer from
storage, so they stay available 24/7 even when the PS3 is off — except a *locked*
trophy's icon, which may need the console online the first time it's requested.

- **Base URL:** `https://playtime.gwm-eplring.netcraze.club` (LAN: `http://192.168.1.106:3301`)
- **Auth:** header `X-Auth-Token: <token>` on every endpoint except `/health`.
  `/trophy-icon` also accepts `?token=<token>` (handy for `<img>`).
  Missing/invalid token → `401 {"detail":"invalid token"}`.
- **Time:** ISO-8601 UTC (e.g. `2026-06-22T16:37:44.969878+00:00`).
- **Conventions:** `account` = real PS3 profile (a technical account like `Vlad`
  is excluded); `key` = `platform:account:titleId`; trophies are keyed by
  `npcommid` (`NPWR…`, the same id PSN uses). Playtime refreshes every ~30s,
  trophies every ~30min and at startup.

---

## GET /health
No auth.
```json
{ "status": "ok" }
```

## GET /stats · GET /stats/{platform}
Playtime totals. `{platform}` filters (e.g. `ps3`).
**Query (optional):** `from`, `to` — ISO timestamp or `YYYY-MM-DD`, UTC, `to` is
exclusive. Example: `/stats?from=2026-06-22&to=2026-06-23`.

```json
{
  "generatedAt": "…",
  "trackedSince": "…",
  "lastPollAt": "…",
  "range": { "from": null, "to": null },
  "summary": { "seconds_total": 2091, "sessions_total": 1, "playing_count": 1 },
  "currentlyPlaying": [ Game ],
  "games": [ Game ]
}
```

**Game:**
```json
{
  "key": "ps3:Ashe-raddo:BLES01138",
  "platform": "ps3",
  "account": "Ashe-raddo",
  "titleId": "BLES01138",
  "titleName": "Far Cry 3",
  "totalSeconds": 2091,
  "sessions": 1,
  "firstPlayed": "…",
  "lastPlayed": "…",
  "playing": true
}
```
`currentlyPlaying` always reflects "now" (independent of `from`/`to`).

## GET /sessions
Raw session rows for custom aggregation.
**Query (optional):** `platform`, `from`, `to`, `limit` (default 500).
```json
{ "sessions": [
  { "platform": "ps3", "account": "Ashe-raddo",
    "title_id": "BLES01138", "title": "Far Cry 3",
    "started_at": "…", "ended_at": "…", "seconds": 2091, "is_open": 1 }
]}
```
Note: this raw layer uses snake_case (`title_id`, `started_at`).

## GET /trophies
Per-set trophy summary. **Query (optional):** `account`.
```json
{ "refreshedAt": "…", "trophies": [ TrophySet ] }
```

**TrophySet:**
```json
{
  "platform": "ps3",
  "account": "Eplring",
  "npcommid": "NPWR00660_00",
  "title": "inFamous",
  "earned": { "bronze": 14, "silver": 3, "gold": 0, "platinum": 0 },
  "total":  { "bronze": 37, "silver": 11, "gold": 1, "platinum": 1 },
  "earnedCount": 17,
  "totalCount": 50,
  "lastEarnedAt": "2026-06-17T19:18:18+00:00",
  "updatedAt": "…"
}
```

## GET /trophies/{account}
Every trophy of a player, across all games.
```json
{
  "account": "Eplring",
  "refreshedAt": "…",
  "sets": [ { …TrophySet…, "trophies": [ Trophy ] } ]
}
```

## GET /trophies/{account}/{npcommid}
All trophies of one game.
```json
{
  "account": "Eplring",
  "npcommid": "NPWR00660_00",
  "title": "inFamous",
  "trophies": [ Trophy ]
}
```

**Trophy:**
```json
{
  "id": 21,
  "name": "Электрожаба",        // null if hidden and not yet earned
  "detail": "…",                 // null if hidden and not yet earned
  "grade": "bronze",             // bronze | silver | gold | platinum
  "hidden": false,
  "unlocked": true,
  "earnedAt": "2026-06-17T09:35:05+00:00",   // null if not earned
  "icon": "/trophy-icon/Eplring/NPWR00660_00/21"
}
```

## GET /trophy-icon/{account}/{npcommid}/{trophy_id}
Trophy icon as `image/png` (240×240). Token via header or `?token=`.
Earned-trophy icons are always served from cache; a locked one is fetched from
the console on first request (needs HEN on) and then cached.

## DELETE /sessions?account=<account>
Remove stored sessions for an account.
```json
{ "deleted": 3 }
```

## POST /ingest
For future push-based platforms (Switch / Vita / 3DS).
**Body:**
```json
{ "platform": "switch", "account": "nx",
  "titleId": "0100ABC", "title": "Zelda TOTK", "seconds": 3600 }
```
→ `{ "ok": true }`

---

## Errors
- `401` — missing/invalid token.
- `404` — unknown account / game (no stored data).
- `503` — needed the PS3 and it was unreachable (HEN off / powered down); only
  the live paths (uncached `/trophy-icon`) can return this.
