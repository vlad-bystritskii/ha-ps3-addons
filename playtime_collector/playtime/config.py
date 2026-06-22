"""Configuration.

Reads Home Assistant add-on options (/data/options.json) if present, otherwise
environment variables, otherwise defaults. The same image therefore runs as a
HAOS add-on and as a plain script (Docker or local).
"""
import json
import os
from pathlib import Path

OPTIONS_FILE = Path("/data/options.json")


def load_options():
    if OPTIONS_FILE.exists():
        try:
            return json.loads(OPTIONS_FILE.read_text())
        except (ValueError, OSError):
            return {}
    return {}


options = load_options()


def get(key, env, default):
    value = options.get(key)
    if value not in (None, ""):
        return value
    return os.environ.get(env, default)


PLATFORM = "ps3"

# IP of the PS3 running webMAN MOD. No default: set it per install.
PS3_HOST = get("ps3_host", "PS3_HOST", "")

# How often to poll the console, in seconds.
POLL_INTERVAL = int(get("poll_interval", "POLL_INTERVAL", 30))

# How often to refresh trophies, in seconds (changes slowly; keep it gentle).
TROPHY_INTERVAL = int(get("trophy_interval", "TROPHY_INTERVAL", 1800))

# Fallback player label when the active PS3 profile can't be resolved.
ACCOUNT = get("account", "ACCOUNT", "ps3")

# Profiles to NOT track (e.g. a technical account). List, or comma-separated string.
_ignore_raw = get("ignore_accounts", "IGNORE_ACCOUNTS", "Vlad")
if isinstance(_ignore_raw, list):
    IGNORE_ACCOUNTS = [str(a).strip() for a in _ignore_raw if str(a).strip()]
else:
    IGNORE_ACCOUNTS = [a.strip() for a in str(_ignore_raw).split(",") if a.strip()]

# Shared token required in the X-Auth-Token header to read the API.
# Empty = no auth (fine on a trusted LAN; set one before exposing publicly).
AUTH_TOKEN = get("auth_token", "AUTH_TOKEN", "")

HTTP_PORT = int(get("http_port", "HTTP_PORT", 3301))

# /data is provided by HAOS add-ons; otherwise store next to the code.
data_dir = Path("/data") if Path("/data").is_dir() else Path(__file__).resolve().parent.parent / "data"
DB_PATH = get("db_path", "DB_PATH", str(data_dir / "playtime.db"))
ICON_DIR = get("icon_dir", "ICON_DIR", str(data_dir / "icons"))

# Optional PSN NPSSO token to enrich trophies with global rarity (% of players).
# Rarity is a PSN-server stat, not on the console; leave empty to disable.
PSN_NPSSO = get("psn_npsso", "PSN_NPSSO", "")
# How often to refresh PSN rarity, in seconds (changes slowly).
RARITY_INTERVAL = int(get("rarity_interval", "RARITY_INTERVAL", 86400))

# How often to log a "last 24h" activity summary, in seconds.
SUMMARY_INTERVAL = int(get("summary_interval", "SUMMARY_INTERVAL", 86400))
