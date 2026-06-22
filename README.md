# Playtime Collector — Home Assistant add-on

Track game **playtime** and **trophies** from a jailbroken **PS3** and expose them
over a small JSON API — without installing anything on the console.

The PS3 already runs an HTTP server ([webMAN MOD]) while HEN is enabled, so an
always-on collector (this add-on, running on Home Assistant) just polls it,
attributes playtime to the active PS3 profile, reads trophies off the console, and
stores everything in SQLite. The schema is multi-platform/multi-account, so other
consoles can push data later via `/ingest`.

[webMAN MOD]: https://github.com/aldostools/webMAN-MOD

## Install (Home Assistant)

1. **Settings → Add-ons → Add-on Store → ⋮ (top right) → Repositories.**
2. Add this repository URL:
   ```
   https://github.com/OWNER/playtime-collector
   ```
3. Install **Playtime Collector** from the store, set the options
   (`ps3_host`, `auth_token`, …), and start it.

[![Open your Home Assistant instance and show the add add-on repository dialog with a specific repository URL pre-filled.](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2FOWNER%2Fplaytime-collector)

Add-on configuration and options are documented in
[`playtime_collector/DOCS.md`](playtime_collector/DOCS.md).

## API

The full HTTP/JSON contract is in [`CONTRACT.md`](CONTRACT.md): playtime
(`/stats`, `/sessions`), trophies (`/trophies`, per-game detail, icons), time
ranges, and the `/ingest` push endpoint for future platforms.

## How it works

- Polls `http://<ps3>/cpursx.ps3`; when a game runs it exposes the title id, the
  name, webMAN's per-session play timer, and the active profile.
- Playtime is attributed to the resolved PS3 username; technical accounts can be
  ignored (`ignore_accounts`).
- Trophies are read from `home/<profile>/trophy/<NPWR>/` (`TROPCONF.SFM` +
  `TROPUSR.DAT`) and keyed by `npcommid` — the same id PSN uses.

## Limitations

- HEN must be on (the PS3 is invisible otherwise — handled as idle, not an error).
- PS2-emulator titles drop HEN/webMAN and can't be tracked.
- Trophies are read locally (for profiles not synced to PSN).

## Development

The add-on is a small Python service (FastAPI + SQLite + httpx) in
`playtime_collector/playtime/`. Run it standalone:

```sh
cd playtime_collector
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
PS3_HOST=192.168.1.x AUTH_TOKEN=secret python -m playtime
```

## License

MIT — see [LICENSE](LICENSE).
