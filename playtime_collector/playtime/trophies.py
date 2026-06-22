"""PS3 trophy reader.

Trophies live on the console under home/<profile>/trophy/<NPWR...>/, keyed by
the PSN trophy communication id (NPWR...), the same id PSN uses — so the data
maps 1:1 onto a PSN trophy set.

Two files per set, both served by webMAN over HTTP:
- TROPCONF.SFM  : signed container; after the binary header it is plain XML with
  <npcommid>, <title-name> and <trophy id=".." ttype="P|G|S|B"> definitions.
- TROPUSR.DAT   : binary container holding per-trophy unlock state + timestamps.

TROPUSR.DAT / TROPCONF.SFM container layout (reverse-engineered, big-endian):
- 0x00: 4-byte tag, 0x04: version, 0x08: u32 number of table entries.
- 0x30: table of contents, each entry 0x20 bytes:
    [0]=type [1]=record size [3]=record count [5]=block offset.
- A block's records are (record size + 0x10) bytes apart.
- type 6 = trophy state records: id @0x08, unlocked flag @0x14 (1=earned),
  earned timestamp @0x20 (u64 microseconds since 0001-01-01 UTC).
"""
import re
import struct
from datetime import datetime, timedelta, timezone

import httpx

PS3_EPOCH = datetime(1, 1, 1, tzinfo=timezone.utc)
GRADE_NAMES = {"P": "platinum", "G": "gold", "S": "silver", "B": "bronze"}
EMPTY = {"bronze": 0, "silver": 0, "gold": 0, "platinum": 0}

SET_RE = re.compile(r'href="(NPWR[0-9_]+)"')
NPCOMMID_RE = re.compile(r"<npcommid>(.*?)</npcommid>")
TITLE_RE = re.compile(r"<title-name>(.*?)</title-name>", re.DOTALL)
TROPHY_BLOCK_RE = re.compile(r'<trophy id="(\d+)"([^>]*)>(.*?)</trophy>', re.DOTALL)
TTYPE_RE = re.compile(r'ttype="([PGSB])"')
HIDDEN_RE = re.compile(r'hidden="(yes|no)"')
NAME_RE = re.compile(r"<name>(.*?)</name>", re.DOTALL)
DETAIL_RE = re.compile(r"<detail>(.*?)</detail>", re.DOTALL)


def parse_tropconf(data):
    """Return (npcommid, title, {trophy_id: {grade, name, detail, hidden}})."""
    start = data.find(b"<trophyconf")
    xml = data[start:].decode("utf-8", "ignore") if start >= 0 else ""
    npcommid = NPCOMMID_RE.search(xml)
    title = TITLE_RE.search(xml)
    defs = {}
    for trophy_id, attrs, body in TROPHY_BLOCK_RE.findall(xml):
        grade = TTYPE_RE.search(attrs)
        if not grade:
            continue
        name = NAME_RE.search(body)
        detail = DETAIL_RE.search(body)
        hidden = HIDDEN_RE.search(attrs)
        defs[int(trophy_id)] = {
            "grade": GRADE_NAMES[grade.group(1)],
            "name": name.group(1).strip() if name else None,
            "detail": detail.group(1).strip() if detail else None,
            "hidden": bool(hidden) and hidden.group(1) == "yes",
        }
    return (
        npcommid.group(1) if npcommid else None,
        title.group(1).strip() if title else None,
        defs,
    )


def parse_toc(data):
    count = struct.unpack(">I", data[8:12])[0]
    toc = {}
    off = 0x30
    for _ in range(count):
        fields = struct.unpack(">8I", data[off:off + 0x20])
        off += 0x20
        toc[fields[0]] = {"size": fields[1], "count": fields[3], "offset": fields[5]}
    return toc


def parse_tropusr(data):
    """Return {trophy_id: {"unlocked": bool, "earned_at": iso|None}}."""
    block = parse_toc(data).get(6)
    if not block:
        return {}
    stride = block["size"] + 0x10
    state = {}
    for i in range(block["count"]):
        start = block["offset"] + i * stride
        rec = data[start:start + stride]
        if len(rec) < 0x28:
            break
        trophy_id = struct.unpack(">I", rec[0x08:0x0C])[0]
        unlocked = struct.unpack(">I", rec[0x14:0x18])[0] == 1
        earned_at = None
        if unlocked:
            ts = struct.unpack(">Q", rec[0x20:0x28])[0]
            if ts:
                earned_at = (PS3_EPOCH + timedelta(microseconds=ts)).isoformat()
        state[trophy_id] = {"unlocked": unlocked, "earned_at": earned_at}
    return state


def summary_dict(npcommid, title, defs, state):
    earned = dict(EMPTY)
    total = dict(EMPTY)
    last = None
    for trophy_id, definition in defs.items():
        grade = definition["grade"]
        total[grade] += 1
        info = state.get(trophy_id)
        if info and info["unlocked"]:
            earned[grade] += 1
            if info["earned_at"] and (last is None or info["earned_at"] > last):
                last = info["earned_at"]
    return {
        "npcommid": npcommid,
        "title": title,
        "earned": earned,
        "total": total,
        "earnedCount": sum(earned.values()),
        "totalCount": sum(total.values()),
        "lastEarnedAt": last,
    }


def detail_items(defs, state):
    items = []
    for trophy_id in sorted(defs):
        d = defs[trophy_id]
        s = state.get(trophy_id, {})
        unlocked = bool(s.get("unlocked"))
        # Hidden, not-yet-earned trophies expose no name/detail on the console.
        items.append({
            "id": trophy_id,
            "name": d["name"] if (unlocked or not d["hidden"]) else None,
            "detail": d["detail"] if (unlocked or not d["hidden"]) else None,
            "grade": d["grade"],
            "hidden": d["hidden"],
            "unlocked": unlocked,
            "earnedAt": s.get("earned_at"),
        })
    return items


async def list_sets(host, client, profile_id):
    url = "http://" + host + "/dev_hdd0/home/" + profile_id + "/trophy/"
    response = await client.get(url, timeout=8.0)
    response.raise_for_status()
    return SET_RE.findall(response.text)


async def fetch_set_full(host, client, profile_id, npcommid_dir):
    """Download a set once; return (summary, per-trophy items)."""
    base = "http://" + host + "/dev_hdd0/home/" + profile_id + "/trophy/" + npcommid_dir
    conf = await client.get(base + "/TROPCONF.SFM", timeout=8.0)
    conf.raise_for_status()
    usr = await client.get(base + "/TROPUSR.DAT", timeout=8.0)
    usr.raise_for_status()
    npcommid, title, defs = parse_tropconf(conf.content)
    state = parse_tropusr(usr.content)
    npcommid = npcommid or npcommid_dir
    return summary_dict(npcommid, title, defs, state), detail_items(defs, state)


async def fetch_icon(host, client, profile_id, npcommid_dir, trophy_id):
    url = ("http://" + host + "/dev_hdd0/home/" + profile_id + "/trophy/"
           + npcommid_dir + "/TROP%03d.PNG" % int(trophy_id))
    response = await client.get(url, timeout=8.0)
    response.raise_for_status()
    return response.content
