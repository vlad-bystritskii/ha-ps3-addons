<div align="center">

# 🕹️ Playtime Collector

**A Home Assistant add-on that tracks PlayStation 3 playtime & trophies — and serves them as a clean JSON API.**

Point it at your jailbroken PS3 and get per-profile playtime, full trophy lists, and
optional global PSN rarity — ready for dashboards, bots, or your own stats site.

![home assistant](https://img.shields.io/badge/Home%20Assistant-add--on-41BDF5?logo=home-assistant&logoColor=white)
![console](https://img.shields.io/badge/console-PS3%20HEN%20%2F%20CFW-003791)
![api](https://img.shields.io/badge/API-JSON%20over%20HTTP-success)
![license](https://img.shields.io/badge/license-MIT-blue)

</div>

---

## What it does

Your jailbroken PS3 already runs an HTTP server ([webMAN MOD]) while HEN is enabled.
This always-on add-on (running on your Home Assistant box) turns that into a proper
data source:

- 🖥️ **Built-in web dashboard** — top players with their **real PS3 profile avatars**,
  top games with **real game icons**, now-playing, a by-day chart, click-through
  player/game detail modals, and a **trophy activity feed** with real trophy icons.
  One click from the add-on page (**Open Web UI**).
- ⏱️ **Playtime** per **profile** and **game** — who played what, for how long.
- 🏆 **Trophies** read **straight off the console** — so they work even for profiles
  that were never synced to PSN.
- 💎 **Global PSN rarity** (optional) — enrich trophies with the % of players who earned them.
- ✨ **Clean game titles** — strips the trademark glyphs / promo tags games bake into their
  own metadata (the XMB hides these too), via a configurable override list.
- 🌐 **Clean JSON API** with an optional auth token — poll it from anywhere.
- 🗄️ **SQLite storage**, multi-platform/multi-account schema (other consoles can push later).

[webMAN MOD]: https://github.com/aldostools/webMAN-MOD

## 🔀 Two ways to collect — pick whatever you have

| `playtime_source` | How it works | Needs |
|---|---|---|
| **`webman`** | The add-on polls the console's `cpursx.ps3` over the LAN and builds sessions itself. | Nothing on the console |
| **`plugin`** | Ingests the log written by the on-console [PS3PlaytimeTracker] plugin — captures play **even off-network** (console taken elsewhere), with no polling gaps. | The plugin installed |
| **`auto`** *(default)* | Uses the plugin's log when present, otherwise LAN polling. With both, the plugin is the source of truth (no double counting). | — |

[PS3PlaytimeTracker]: https://github.com/vlad-bystritskii/PS3PlaytimeTracker

> Trophies and PSN rarity are collected regardless of this setting.

## 📥 Install

1. In Home Assistant: **Settings → Add-ons → Add-on Store → ⋮ → Repositories**.
2. Add this repository URL:
   ```
   https://github.com/vlad-bystritskii/ha-ps3-addon
   ```
3. Install **Playtime Collector**, set `ps3_host` (and a long `auth_token`), and start it.

[![Add repository to your Home Assistant](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2Fvlad-bystritskii%2Fha-ps3-addon)

## ⚙️ Configuration

| Option | Default | Description |
|---|---|---|
| `ps3_host` | — | PS3 IP address (required), e.g. `192.168.1.72` |
| `playtime_source` | `auto` | `auto` / `webman` / `plugin` (see above) |
| `poll_interval` | `30` | Seconds between LAN polls |
| `trophy_interval` | `1800` | Seconds between trophy scans |
| `ignore_accounts` | `Vlad` | Comma-separated profiles to skip (e.g. technical ones) |
| `auth_token` | empty | If set, required in the `X-Auth-Token` header |
| `psn_npsso` | empty | Optional PSN NPSSO token for global trophy rarity |
| `title_overrides` | defaults | Clean up game names (see below) |

Full option docs: [`playtime_collector/DOCS.md`](playtime_collector/DOCS.md).

### ✨ Clean titles

Some PS3 games bake trademark glyphs (`®`, `™`) or promo tags into their own metadata
(`PARAM.SFO`, trophy config) — the XMB hides these when it draws the name, and so does
this add-on via the `title_overrides` option. Each entry is `"<match>=<replacement>"`,
where `<match>` is a **title id** (e.g. `BCES01585`) or an **exact title string**
(e.g. `KILLZONE®`); a title-id match wins. Overrides apply to new sessions, trophy sets
and the live "now playing", **and retroactively to titles already stored** on start.
Sensible defaults ship out of the box — edit the list in the add-on **Configuration** tab.

```yaml
title_overrides:
  - "BCES01585=The Last of Us"
  - "KILLZONE®=KILLZONE"
  - "Dante's Inferno™=Dante's Inferno"
```

## 🖥️ Web dashboard

Open it straight from the add-on page — **Settings → Add-ons → Playtime Collector →
Open Web UI** (or browse to `http://<your-ha-host>:3301/`). No URL to remember.

- **Top players** with their **real PS3 profile avatars** and **top games** with **real
  game icons** — click either for a detail modal (stats, sessions log, trophies, by-weekday).
- **Now playing**, a **by-day** chart, and a **trophy activity feed** showing recent
  unlocks with the actual trophy icons, rarity, and grade.

Where the images come from (all pulled over webMAN, **cached to disk so they survive the
console being off**):

- **Avatars** — the profile's chosen avatar, resolved from the firmware gallery via the
  console registry. Works for **locally-set avatars with no PSN login**.
- **Game icons** — the game's own `ICON0.PNG` from the console, falling back to
  [GameTDB] cover art for anything not installed.

[GameTDB]: https://www.gametdb.com

## 🌐 API

Served on port `3301` (send the optional `X-Auth-Token` header; image routes are open
so the dashboard `<img>` tags load):

```
GET /                                      web dashboard (HTML)
GET /stats                                playtime totals per profile/game (+ ?from=&to=)
GET /sessions                             raw sessions
GET /trophies                             trophy summary per profile
GET /trophies/{account}                   full trophy list for a profile
GET /trophies/{account}/{npwr}            per-trophy detail (earned, rarity, icon URL)
GET /trophy-icon/{account}/{npwr}/{id}    trophy icon PNG
GET /avatar/{account}                     profile avatar PNG (cached)
GET /game-icon/{titleId}                  game icon PNG/JPEG (console ICON0 / GameTDB)
GET /health
```

Full HTTP/JSON contract: [`CONTRACT.md`](CONTRACT.md).

```jsonc
// GET /stats  (excerpt)
{
  "currentlyPlaying": [{ "account": "Eplring", "titleName": "inFamous", "totalSeconds": 4187 }],
  "games": [
    { "account": "Eplring", "titleId": "BCES00609", "titleName": "inFamous",
      "totalSeconds": 4187, "sessions": 3 }
  ]
}
```

## 🏆 Trophies & rarity

Trophies are read locally from the console (`TROPCONF.SFM` + `TROPUSR.DAT`, keyed by
`npcommid` — the same id PSN uses), so they're available even for offline profiles
and even while the PS3 is off (icons are cached). Set `psn_npsso` to a PSN account's
NPSSO token to add the global **earn rate** and **rare tier** to each trophy — get it
by logging into <https://www.playstation.com>, then opening
<https://ca.account.sony.com/api/v1/ssocookie> and copying the `npsso` value.

## 🔗 Going further: the on-console plugin

Want to capture playtime when the console is **away from your network**? Install the
companion **[PS3PlaytimeTracker]** plugin on the PS3 — it logs sessions on the
console itself, and this add-on ingests them automatically (`playtime_source: plugin`
or `auto`).

## 🛠️ Development

A small Python service (FastAPI + SQLite + httpx) in `playtime_collector/playtime/`.
Run it standalone:

```sh
cd playtime_collector
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
PS3_HOST=192.168.1.x AUTH_TOKEN=secret python -m playtime
```

## 📝 Notes

- The PS3 only serves webMAN while HEN is enabled, so it's reachable while gaming;
  an unreachable console is treated as idle, not an error.
- PS2-emulator titles drop HEN/webMAN access and can't be tracked over the LAN.

## 📜 License

MIT — see [LICENSE](LICENSE). For homebrew / personal use with your own console.
