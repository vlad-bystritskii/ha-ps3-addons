"""PS3 webMAN MOD client and cpursx.ps3 parser.

How detection works (checked against webMAN MOD 1.47.48):

- GET /cpursx.ps3 returns an HTML page. When a game is running, it contains:
  - the running title id, e.g. a link ".../np/<TITLEID>/<TITLEID>-ver.xml"
    and a path "/dev_hdd0/game//<TITLEID>";
  - the display name (a google-search link);
  - a per-session play timer: title="Play">...</label> HH:MM:SS.
- At the home menu (no game) none of these appear.
- The PS3 is reachable only while HEN is enabled, i.e. while gaming, so a
  connection error just means "offline" (console off or HEN not enabled).
"""
import asyncio
import re
from dataclasses import dataclass

import httpx

TITLEID = r"[A-Z]{4}\d{5}"
TITLEID_RE = re.compile(r"/np/(" + TITLEID + r")/")
TITLEID_FALLBACK_RE = re.compile(r"/dev_hdd0/game//(" + TITLEID + r")")
TITLE_RE = re.compile(r'search\?q=[^"]*">([^<]+)</a>')
PLAY_RE = re.compile(r'title="Play">[^<]*</label>\s*(\d{1,3}:\d{2}:\d{2})')
VERSION_SUFFIX_RE = re.compile(r"\s+\d{2}\.\d{2}\s*$")
PROFILE_RE = re.compile(r"/dev_hdd0/home/(\d{8})")

# profile id -> local username, resolved once via webMAN and cached.
username_cache = {}


@dataclass
class Snapshot:
    online: bool
    title_id: str | None = None
    title: str | None = None
    play_seconds: int | None = None
    profile_id: str | None = None


def hms_to_seconds(text):
    hours, minutes, seconds = (int(part) for part in text.split(":"))
    return hours * 3600 + minutes * 60 + seconds


def parse_cpursx(html):
    """Turn a cpursx.ps3 page into a Snapshot (online=True)."""
    match = TITLEID_RE.search(html) or TITLEID_FALLBACK_RE.search(html)
    if not match:
        return Snapshot(online=True)  # reachable, but at the home menu

    title_id = match.group(1)

    title = None
    title_match = TITLE_RE.search(html)
    if title_match:
        title = VERSION_SUFFIX_RE.sub("", title_match.group(1).strip()) or None

    play_seconds = None
    play_match = PLAY_RE.search(html)
    if play_match:
        play_seconds = hms_to_seconds(play_match.group(1))

    profile_match = PROFILE_RE.search(html)
    profile_id = profile_match.group(1) if profile_match else None

    return Snapshot(
        online=True,
        title_id=title_id,
        title=title,
        play_seconds=play_seconds,
        profile_id=profile_id,
    )


async def fetch_snapshot(host, client):
    """Poll the PS3. Any connection/HTTP error means offline."""
    try:
        response = await client.get("http://" + host + "/cpursx.ps3", timeout=5.0)
        response.raise_for_status()
    except (httpx.HTTPError, OSError):
        return Snapshot(online=False)
    return parse_cpursx(response.text)


PROFILE_DIR_RE = re.compile(r'href="(\d{8})/?"')


async def list_profiles(host, client):
    """List local profiles as (profile_id, username). Used for trophy scanning.

    The directory listing is retried: right after the console/HEN comes up webMAN
    can be briefly busy, and a single failed GET here would otherwise wipe the
    whole scan (no profiles -> nothing scanned for a full interval).
    """
    text = None
    for attempt in range(3):
        try:
            response = await client.get("http://" + host + "/dev_hdd0/home/", timeout=5.0)
            response.raise_for_status()
            text = response.text
            break
        except (httpx.HTTPError, OSError):
            if attempt < 2:
                await asyncio.sleep(1.0)
    if not text:
        return []
    profiles = []
    for profile_id in sorted(set(PROFILE_DIR_RE.findall(text))):
        profiles.append((profile_id, await resolve_username(host, client, profile_id)))
    return profiles


async def profile_id_for(host, client, account):
    """Reverse lookup: username -> local profile id (for trophy detail/icons)."""
    for profile_id, name in await list_profiles(host, client):
        if name == account:
            return profile_id
    return None


# PS3 caches a profile's avatar on the HDD. The PSN online avatar lands at
# friendim/avatar/me.png; some firmwares/setups also keep a generic avatar.png.
# We try a few known spots and take the first that returns a PNG.
AVATAR_PATHS = (
    "friendim/avatar/me.png",
    "friendim/avatar/avatar.png",
    "avatar.png",
)


async def fetch_avatar(host, client, profile_id):
    """Fetch a local profile's cached avatar PNG, or None if the console has none.

    Reads it straight off the HDD via webMAN (same mechanism as localusername and
    trophy icons), so it works while the console is reachable and is then cached to
    disk by the caller to survive the console being off / lent out."""
    if not profile_id:
        return None
    base = "http://" + host + "/dev_hdd0/home/" + profile_id + "/"
    for rel in AVATAR_PATHS:
        try:
            response = await client.get(base + rel, timeout=5.0)
            response.raise_for_status()
        except (httpx.HTTPError, OSError):
            continue
        png = response.content
        if png[:8] == b"\x89PNG\r\n\x1a\n":  # ignore webMAN 404 HTML served as 200
            return png
    return None


async def resolve_username(host, client, profile_id):
    """Resolve a local profile id (e.g. 00000003) to its PS3 username
    (e.g. Ashe-raddo) by reading dev_hdd0/home/<id>/localusername. Cached."""
    if not profile_id:
        return None
    if profile_id in username_cache:
        return username_cache[profile_id]
    url = "http://" + host + "/dev_hdd0/home/" + profile_id + "/localusername"
    for _ in range(3):  # name resolution gates the ignore-list, so retry transients
        try:
            response = await client.get(url, timeout=5.0)
            response.raise_for_status()
            name = response.text.strip() or None
        except (httpx.HTTPError, OSError):
            name = None
        if name:
            username_cache[profile_id] = name
            return name
    return None
