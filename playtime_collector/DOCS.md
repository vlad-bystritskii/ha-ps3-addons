# Playtime Collector

Polls a jailbroken **PS3** (webMAN MOD) over the LAN, accumulates per-profile
**playtime**, reads **trophies** off the console, and serves everything as a small
JSON API. Nothing is installed on the console.

## Configuration

| Option            | Default | Description                                             |
|-------------------|---------|---------------------------------------------------------|
| `ps3_host`        | —       | PS3 IP address (required), e.g. `192.168.1.72`          |
| `playtime_source` | `auto`  | Where playtime comes from: `auto` / `webman` / `plugin` |
| `poll_interval`   | `30`    | Seconds between playtime polls                          |
| `trophy_interval` | `1800`  | Seconds between trophy scans                            |
| `account`         | `ps3`   | Fallback player label if a profile can't be resolved    |
| `ignore_accounts` | `Vlad`  | Comma-separated profiles to skip (e.g. technical ones)  |
| `auth_token`      | empty   | If set, required in the `X-Auth-Token` header           |
| `psn_npsso`       | empty   | Optional PSN NPSSO token to enrich trophies with global rarity |

Example:

```yaml
ps3_host: "192.168.1.72"
poll_interval: 30
trophy_interval: 1800
account: "ps3"
ignore_accounts: "Vlad"
auth_token: "change-me-to-a-long-secret"
psn_npsso: ""
```

### Playtime source

There are two independent ways to collect playtime — pick whichever you have:

- **`webman`** — the add-on polls the console's `cpursx.ps3` over the LAN and builds
  sessions itself. Nothing is installed on the PS3. Only captures time while the
  console is reachable on your network.
- **`plugin`** — an on-console plugin ([ps3-playtime-plugin]) logs every session to
  `/dev_hdd0/playtime/` even when no observer is watching (e.g. the console taken
  elsewhere); the add-on ingests that log when it can reach the console. No ~30s
  polling gaps, and it captures away-from-home play.
- **`auto`** (default) — use the plugin's log when it's present, otherwise fall back
  to LAN polling. With both, the plugin is the source of truth and LAN polling does
  not double-count.

Trophy and rarity collection run regardless of this setting.

### Trophy rarity (optional)

Rarity (the % of players who earned a trophy) is a global PSN statistic and is not
stored on the console. Set `psn_npsso` to a PSN account's NPSSO token to fetch it
per trophy and add `earnedRate` / `rare` to the trophy API. Get the token by
logging into <https://www.playstation.com>, then opening
<https://ca.account.sony.com/api/v1/ssocookie> and copying the `npsso` value.

## Usage

The API is served on port `3301`. With the PS3 on and HEN enabled:

- `GET /stats` — playtime totals per profile/game
- `GET /trophies` — trophy summary; `GET /trophies/{account}` — full list
- `GET /trophy-icon/{account}/{npcommid}/{id}` — trophy icon PNG

See the full API in `CONTRACT.md` at the repository root.

## Notes

- The PS3 only serves webMAN while HEN is enabled, so it is only reachable while
  gaming. An unreachable console is treated as idle, not an error.
- PS2-emulator titles drop HEN/webMAN access and cannot be tracked.
- Trophies are read locally from the console (for profiles not synced to PSN).
