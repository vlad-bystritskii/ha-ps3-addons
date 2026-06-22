# Playtime Collector

Polls a jailbroken **PS3** (webMAN MOD) over the LAN, accumulates per-profile
**playtime**, reads **trophies** off the console, and serves everything as a small
JSON API. Nothing is installed on the console.

## Configuration

| Option            | Default | Description                                             |
|-------------------|---------|---------------------------------------------------------|
| `ps3_host`        | —       | PS3 IP address (required), e.g. `192.168.1.72`          |
| `poll_interval`   | `30`    | Seconds between playtime polls                          |
| `trophy_interval` | `1800`  | Seconds between trophy scans                            |
| `account`         | `ps3`   | Fallback player label if a profile can't be resolved    |
| `ignore_accounts` | `Vlad`  | Comma-separated profiles to skip (e.g. technical ones)  |
| `auth_token`      | empty   | If set, required in the `X-Auth-Token` header           |

Example:

```yaml
ps3_host: "192.168.1.72"
poll_interval: 30
trophy_interval: 1800
account: "ps3"
ignore_accounts: "Vlad"
auth_token: "change-me-to-a-long-secret"
```

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
