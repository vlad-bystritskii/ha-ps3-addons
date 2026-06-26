"""PLAYTRACE web dashboard (server-rendered shell + vanilla JS, wired to LIVE data).

The server embeds one live-data bootstrap payload as JSON (no token in the page,
one request); the browser renders the whole PLAYTRACE design from it and uses the
addon's own JSON endpoints for the interactive bits:

  * period tabs        -> GET /chart?period=&person=        (falls back to deriving
                          buckets from the embedded /sessions data)
  * account switcher   -> embedded per-person /stats payload (+platformDistribution)
  * game detail modal  -> GET /games/{platform}/{title_id}  (falls back to embedded)
  * history timeline   -> embedded merged /sessions + trophy unlocks

No mock data is ever shipped — every value comes from the addon's database via the
same shapes the JSON API exposes. Design source: design/Dashboard.dc.html.
"""
import json

from . import config, db


def _account_payload(acct_id, name, pairs, person_id, earned_by_game, open_keys):
    """Build one switcher 'account' (a person, or a raw platform account) with its
    games + platform distribution, all scoped to that account's (platform, account)
    pairs — mirrors GET /stats?person=<id>."""
    tuples = [tuple(p) for p in pairs]
    rows = db.totals(None, None, None, tuples) if tuples else []
    games, dist, total = [], {}, 0
    for r in rows:
        if r["title_id"] == "PTVIEW001":   # internal view-counter pseudo title
            continue
        sec = r["total_seconds"] or 0
        total += sec
        games.append({
            "title": r["title"] or r["title_id"], "titleId": r["title_id"],
            "platform": r["platform"], "account": r["account"],
            "totalSeconds": sec, "sessions": r["sessions"],
            "lastPlayed": r["last_played"], "firstPlayed": r["first_played"],
            "trophies": earned_by_game.get((r["account"], r["title"]), 0),
            "playing": (r["platform"], r["account"], r["title_id"]) in open_keys,
        })
    for g in games:
        d = dist.setdefault(g["platform"], {"seconds": 0, "sessions": 0})
        d["seconds"] += g["totalSeconds"]
        d["sessions"] += g["sessions"]
    platforms = [p for p, _ in sorted(dist.items(), key=lambda kv: -kv[1]["seconds"])]
    platform_distribution = [
        {"platform": p, "seconds": v["seconds"], "sessions": v["sessions"],
         "pct": (v["seconds"] * 100 / total) if total else 0}
        for p, v in sorted(dist.items(), key=lambda kv: -kv[1]["seconds"])
    ]
    games.sort(key=lambda g: g["totalSeconds"], reverse=True)
    return {
        "id": acct_id, "personId": person_id, "name": name, "pairs": pairs,
        "platforms": platforms, "totalSeconds": total,
        "platformDistribution": platform_distribution, "games": games,
    }


def _trophy_icon_url(account, npcommid, trophy_id):
    """Build the relative trophy-icon route (ingress-safe). The image route 404s when
    no real icon exists; the dashboard's <img onerror> then reveals the diamond
    placeholder, so it's always safe to emit a path here."""
    if account and npcommid and trophy_id is not None and trophy_id != "":
        return "trophy-icon/%s/%s/%s" % (account, npcommid, trophy_id)
    return None


def build_data():
    troph_sets = db.query_trophies(None, None)
    earned_by_game = {(t["account"], t["title"]): t.get("earnedCount", 0) for t in troph_sets}
    open_keys = {(r["platform"], r["account"], r["title_id"]) for r in db.open_sessions(None)}

    persons = db.list_persons()
    accounts = []
    if persons:
        for p in persons:
            pairs = [[l["platform"], l["account"]] for l in p["links"]]
            accounts.append(_account_payload(
                "p%d" % p["id"], p["name"], pairs, p["id"], earned_by_game, open_keys))
    if not accounts:
        # No people configured (or none have data) — derive switcher entries from
        # the distinct raw accounts that actually have sessions, so the dashboard
        # still works against live data out of the box.
        seen = []
        for r in db.totals(None, None, None):
            if r["title_id"] == "PTVIEW001":
                continue
            key = (r["platform"], r["account"])
            if key not in seen:
                seen.append(key)
        for plat, acct in seen:
            accounts.append(_account_payload(
                "%s:%s" % (plat, acct), acct, [[plat, acct]], None, earned_by_game, open_keys))

    sessions = [{
        "account": s["account"], "titleId": s["title_id"],
        "title": s["title"] or s["title_id"], "platform": s["platform"],
        "started": s["started_at"], "seconds": s["seconds"],
    } for s in db.list_sessions(None, None, None, 3000) if s["title_id"] != "PTVIEW001"]

    feed = [{
        "account": r["account"], "game": r["game"], "npcommid": r["npcommid"],
        "trophyId": r["trophy_id"], "name": r["name"], "detail": r["detail"],
        "grade": r["grade"], "earnedAt": r["earned_at"], "rate": r["earned_rate"],
        "iconUrl": _trophy_icon_url(r["account"], r["npcommid"], r["trophy_id"]),
    } for r in db.recent_trophy_unlocks(config.PLATFORM, 200)]

    trophies = [{
        "account": t["account"], "title": t["title"], "platform": t["platform"],
        "earnedCount": t["earnedCount"], "totalCount": t["totalCount"],
    } for t in troph_sets]

    return {
        "meta": {"lastPoll": db.get_meta("last_poll_at"),
                 "trackedSince": db.get_meta("tracked_since")},
        "accounts": accounts, "sessions": sessions, "feed": feed, "trophies": trophies,
    }


def render():
    return _PAGE.replace("/*DATA*/0", json.dumps(build_data()))


_PAGE = r"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>PLAYTRACE</title>
<link rel="icon" href="icon">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;700&display=swap" rel="stylesheet">
<script>
// Apply theme + accent before first paint to avoid a flash.
(function(){var t='dark';try{t=localStorage.getItem('pt-theme')||'dark';}catch(e){}
 document.documentElement.dataset.theme=t;document.documentElement.style.setProperty('--accent','#6c5cff');})();
</script>
<style>
  *{box-sizing:border-box;}
  html,body{margin:0;}
  ::selection{background:var(--accent);color:#fff;}
  [data-theme="dark"]{--bg:#0b0d12;--surface:#14161d;--surface2:#1b1e27;--surfaceHover:rgba(255,255,255,.035);--border:rgba(255,255,255,.07);--border2:rgba(255,255,255,.14);--text:#e9ebf0;--dim:#9aa0ad;--faint:#5b6070;}
  [data-theme="light"]{--bg:#eef1f5;--surface:#ffffff;--surface2:#f4f6f9;--surfaceHover:rgba(15,20,35,.03);--border:rgba(15,20,35,.09);--border2:rgba(15,20,35,.16);--text:#161922;--dim:#5b6473;--faint:#9aa1b0;}
  body{background:var(--bg,#0b0d12);color:var(--text,#e9ebf0);font-family:'Space Grotesk',system-ui,sans-serif;}
  ::-webkit-scrollbar{width:9px;height:9px;}
  ::-webkit-scrollbar-thumb{background:var(--border2);border-radius:6px;}
  ::-webkit-scrollbar-track{background:transparent;}
  @keyframes blip{0%,100%{opacity:1;transform:scale(1);}50%{opacity:.35;transform:scale(.82);}}
  @keyframes ptPop{from{transform:scale(.965) translateY(8px);}to{transform:scale(1) translateY(0);}}
  button{font-family:inherit;}
</style></head>
<body><div id="root"></div>
<noscript><p style="padding:24px">This dashboard needs JavaScript. Raw data: <a href="stats">stats</a>.</p></noscript>
<script>
const D = /*DATA*/0;
const ACCENT='#6c5cff';
const $=id=>document.getElementById(id);
const esc=s=>String(s==null?'':s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const PALETTE=['#6c5cff','#ff7a3d','#16c3b0','#b06bff','#ff5d6c','#3fbf7f','#4a9eff','#f0883e','#ec5350','#2fd4a8'];
function palColor(name){let h=0;const s=String(name||'');for(let i=0;i<s.length;i++)h=(h*31+s.charCodeAt(i))>>>0;return PALETTE[h%PALETTE.length];}
function initials(name){const c=String(name||'').replace(/[^A-Za-z0-9]/g,'');return (c.slice(0,2)||'??').toUpperCase();}
function plural(n,w){return n+' '+w+(n===1?'':'s');}
const PLATS={ps3:{label:'PS3',color:'#5a7bff'},psvita:{label:'VITA',color:'#16c3b0'},vita:{label:'VITA',color:'#16c3b0'},
 ps4:{label:'PS4',color:'#4a9eff'},ps5:{label:'PS5',color:'#b06bff'},psp:{label:'PSP',color:'#3fbf7f'},
 n3ds:{label:'3DS',color:'#ff5d6c'},swi:{label:'SWITCH',color:'#ff7a3d'}};
function plat(p){return PLATS[p]||{label:String(p||'').toUpperCase(),color:'#8a8f9c'};}
function formatH(sec){sec=Math.max(0,Math.round(sec||0));const H=Math.floor(sec/3600),M=Math.round((sec%3600)/60);
 if(H>=1000)return H.toLocaleString()+'h';if(H===0)return (M||0)+'m';if(M===0)return H+'h';return H+'h '+(M<10?'0':'')+M+'m';}
function ago(iso){if(!iso)return '—';const d=new Date(iso),s=(Date.now()-d.getTime())/1000;
 if(s<60)return 'just now';if(s<3600)return Math.floor(s/60)+'m ago';if(s<86400)return Math.floor(s/3600)+'h ago';
 if(s<604800)return Math.floor(s/86400)+'d ago';if(s<2592000)return Math.floor(s/604800)+'w ago';return d.toLocaleDateString();}
function rarity(p){if(p==null)return {label:'Tracked',color:'#8a8f9c'};
 if(p<2)return {label:'Legendary',color:'#ffb648'};if(p<8)return {label:'Epic',color:'#b06bff'};
 if(p<20)return {label:'Rare',color:'#4a9eff'};return {label:'Common',color:'#8a8f9c'};}
function dkey(d){return d.getFullYear()+'-'+String(d.getMonth()+1).padStart(2,'0')+'-'+String(d.getDate()).padStart(2,'0')}
function mkey(d){return d.getFullYear()+'-'+String(d.getMonth()+1).padStart(2,'0')}
async function fetchJSON(url){const r=await fetch(url,{headers:{Accept:'application/json'}});if(!r.ok)throw new Error('HTTP '+r.status);return r.json();}

/* ---- state ---- */
const state={theme:document.documentElement.dataset.theme||'dark',period:'week',accountIdx:0,
 accountMenuOpen:false,histFilter:'all',histProfile:'all',histMenuOpen:false,
 view:'dashboard',prevView:'dashboard',activeGame:null,gameDetail:null,activeTrophy:null};
let currentChart=null;
let POP=[];   // trophy payloads referenced by index from inline onclick (avoids attr escaping)

const curAcc=()=>D.accounts[state.accountIdx]||null;
function accMeta(a){return {name:a.name,initials:initials(a.name),color:palColor(a.name),
 account:(a.pairs&&a.pairs[0]&&a.pairs[0][1])||'',
 platLabel:a.platforms&&a.platforms.length?a.platforms.map(p=>plat(p).label).join('/'):'—',
 totalLabel:formatH(a.totalSeconds)};}

/* owner lookup: which switcher account owns a (platform,account) / account name */
const OWN={};
D.accounts.forEach((a,i)=>{(a.pairs||[]).forEach(pr=>{OWN[pr[0]+'|'+pr[1]]=i;OWN['n|'+pr[1]]=i;});});
function ownerIdx(platform,account){let k=OWN[platform+'|'+account];if(k==null)k=OWN['n|'+account];return k==null?-1:k;}

/* ---- chart (derived locally from /sessions; refreshed live from /chart) ---- */
function computeChart(a,period){
 const set=new Set((a&&a.pairs||[]).map(p=>p[0]+'|'+p[1]));
 const sess=D.sessions.filter(s=>set.has(s.platform+'|'+s.account));
 const now=new Date();const order=[];let keyFn;
 const MO=['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
 const WD=['Sun','Mon','Tue','Wed','Thu','Fri','Sat'];
 if(period==='today'){const td=dkey(now);
   for(let h=0;h<24;h++)order.push({key:'h'+h,label:String(h).padStart(2,'0'),show:h%4===0});
   keyFn=s=>{const d=new Date(s.started);return dkey(d)===td?'h'+d.getHours():null};}
 else if(period==='week'){for(let i=6;i>=0;i--){const d=new Date(now);d.setDate(now.getDate()-i);
     order.push({key:dkey(d),label:WD[d.getDay()],show:true});}keyFn=s=>dkey(new Date(s.started));}
 else if(period==='month'){for(let i=29;i>=0;i--){const d=new Date(now);d.setDate(now.getDate()-i);
     order.push({key:dkey(d),label:String(d.getDate()),show:(29-i)%5===0});}keyFn=s=>dkey(new Date(s.started));}
 else if(period==='year'){for(let i=11;i>=0;i--){const d=new Date(now.getFullYear(),now.getMonth()-i,1);
     order.push({key:mkey(d),label:MO[d.getMonth()],show:true});}keyFn=s=>mkey(new Date(s.started));}
 else{let min=now.getFullYear();sess.forEach(s=>{const y=new Date(s.started).getFullYear();if(y<min)min=y;});
   for(let y=min;y<=now.getFullYear();y++)order.push({key:String(y),label:String(y),show:true});
   keyFn=s=>String(new Date(s.started).getFullYear());}
 const map={};order.forEach(o=>map[o.key]=0);
 sess.forEach(s=>{const k=keyFn(s);if(k!=null&&k in map)map[k]+=s.seconds||0;});
 const vals=order.map(o=>map[o.key]);const max=Math.max(1,...vals);const total=vals.reduce((x,y)=>x+y,0);
 let pi=0;vals.forEach((v,i)=>{if(v>vals[pi])pi=i;});
 const bars=order.map((o,i)=>({pct:Math.max(4,Math.round(vals[i]/max*100)),label:o.show?o.label:'',tip:o.label+' · '+formatH(vals[i])}));
 return {bars,totalLabel:formatH(total),peakLabel:order.length?(order[pi].label+' · '+formatH(vals[pi])):'—'};
}
function thinLabel(i,n){if(n>=24)return i%4===0;if(n>=15)return i%5===0;return true;}
function mapLiveChart(r){const sv=(r.bars||[]).map(b=>b.value_seconds||0);const max=Math.max(1,...sv);
 return {bars:(r.bars||[]).map((b,i)=>({pct:Math.max(4,Math.round((b.value_seconds||0)/max*100)),
   label:thinLabel(i,r.bars.length)?b.label:'',tip:b.label+' · '+formatH(b.value_seconds)})),
   totalLabel:formatH(r.total_seconds),peakLabel:r.peak?(r.peak.label+' · '+formatH(r.peak.value_seconds)):'—'};}
async function refreshChartLive(){
 const a=curAcc();if(!a||a.personId==null)return;     // need a person id for /chart
 const period=state.period,want=state.accountIdx;
 try{const r=await fetchJSON('chart?period='+encodeURIComponent(period)+'&person='+a.personId);
   if(state.accountIdx===want&&state.period===period){currentChart=mapLiveChart(r);render();}}catch(e){}
}

/* ---- history (merged sessions + trophy unlocks, derived from embedded live data) ---- */
function buildHistory(){
 const items=[];
 D.sessions.forEach(s=>{const oi=ownerIdx(s.platform,s.account);const pn=oi>=0?D.accounts[oi].name:s.account;
   items.push({kind:'session',dt:s.started,platform:s.platform,title:s.title,titleId:s.titleId,
     ownerIdx:oi,playerName:pn,playerColor:palColor(pn),account:s.account,seconds:s.seconds});});
 D.feed.forEach(f=>{const oi=ownerIdx('ps3',f.account);const pn=oi>=0?D.accounts[oi].name:f.account;
   items.push({kind:'trophy',dt:f.earnedAt,platform:'ps3',game:f.game,ownerIdx:oi,
     playerName:pn,playerColor:palColor(pn),name:f.name,desc:f.detail,rate:f.rate,
     npcommid:f.npcommid,trophyId:f.trophyId,account:f.account,iconUrl:f.iconUrl});});
 let f=items.filter(it=>state.histFilter==='all'||it.kind===state.histFilter);
 if(state.histProfile!=='all')f=f.filter(it=>it.ownerIdx===+state.histProfile);
 f.sort((a,b)=>String(b.dt||'').localeCompare(String(a.dt||'')));
 return f.slice(0,250);
}
function dateLabel(k){const t=new Date(),y=new Date();y.setDate(t.getDate()-1);
 if(k===dkey(t))return 'Today';if(k===dkey(y))return 'Yesterday';
 return new Date(k+'T12:00').toLocaleDateString(undefined,{month:'short',day:'numeric'});}

/* ====================== render ====================== */
function render(){
 POP=[];
 if(!D.accounts.length){$('root').innerHTML=emptyShell();return;}
 if(state.accountIdx>=D.accounts.length)state.accountIdx=0;
 const a=curAcc();
 if(!currentChart)currentChart=computeChart(a,state.period);
 let h='';
 h+='<div style="--accent:'+ACCENT+';min-height:100vh;background:var(--bg,#0b0d12);color:var(--text,#e9ebf0);font-family:\'Space Grotesk\',system-ui,sans-serif;position:relative;overflow-x:hidden;">';
 h+='<div style="position:absolute;inset:0 0 auto 0;height:420px;background:radial-gradient(130% 90% at 28% -25%, color-mix(in oklab, var(--accent) 15%, transparent), transparent 60%);pointer-events:none;"></div>';
 h+=headerHTML(a);
 h+='<main style="position:relative;max-width:1280px;margin:0 auto;padding:26px 28px 90px;display:flex;flex-direction:column;gap:30px;">';
 h+='<div style="display:grid;grid-template-columns:minmax(0,1.45fr) minmax(310px,1fr);gap:22px;align-items:stretch;">';
 h+=playtimeHTML(a);
 h+=recentGamesHTML(a);
 h+='</div>';
 h+=historyHTML();
 if(state.view==='games')h+=gamesModalHTML(a);
 if(state.view==='game')h+=gameModalHTML();
 if(state.activeTrophy)h+=trophyPopupHTML(state.activeTrophy);
 h+='</main></div>';
 $('root').innerHTML=h;
}

function headerHTML(a){
 const m=accMeta(a);
 let h='<header style="position:sticky;top:0;z-index:30;backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px);background:color-mix(in oklab, var(--bg,#0b0d12) 80%, transparent);border-bottom:1px solid var(--border,rgba(255,255,255,.07));">';
 h+='<div style="max-width:1280px;margin:0 auto;padding:14px 28px;display:flex;align-items:center;gap:18px;flex-wrap:wrap;">';
 h+='<div style="display:flex;align-items:center;gap:11px;">'
  +'<div style="width:28px;height:28px;background:linear-gradient(135deg, var(--accent), color-mix(in oklab, var(--accent) 55%, #fff));transform:rotate(45deg);border-radius:8px;box-shadow:0 4px 16px color-mix(in oklab, var(--accent) 45%, transparent);"></div>'
  +'<div style="display:flex;flex-direction:column;line-height:1.05;"><span style="font-weight:700;font-size:16px;letter-spacing:-.02em;">PLAYTRACE</span>'
  +'<span style="font-size:9.5px;color:var(--faint);letter-spacing:.2em;text-transform:uppercase;">console activity</span></div></div>';
 h+='<div style="flex:1;"></div>';
 h+='<div style="display:flex;align-items:center;gap:8px;padding:6px 12px;border:1px solid var(--border);border-radius:10px;background:var(--surface);">'
  +'<span style="width:8px;height:8px;border-radius:50%;background:#3fbf7f;box-shadow:0 0 0 3px color-mix(in oklab,#3fbf7f 22%,transparent);animation:blip 2.4s ease-in-out infinite;"></span>'
  +'<span style="font-size:9px;color:var(--faint);letter-spacing:.14em;text-transform:uppercase;white-space:nowrap;">Synced</span>'
  +'<span style="font:600 12px \'JetBrains Mono\';color:var(--dim);white-space:nowrap;">'+esc(ago(D.meta.lastPoll))+'</span></div>';
 // nav (kept for the addon; not in the mock) — styled like the theme button
 const navBtn='border:1px solid var(--border);background:var(--surface);color:var(--dim);padding:9px 14px;border-radius:10px;font:600 12px \'Space Grotesk\';cursor:pointer;text-decoration:none;display:inline-block;';
 h+='<a href="./people" style="'+navBtn+'">People</a>';
 h+='<a href="./config" style="'+navBtn+'">Settings</a>';
 h+='<button onclick="toggleTheme()" style="'+navBtn+'">'+(state.theme==='dark'?'Light':'Dark')+'</button>';
 // account switcher
 h+='<div style="position:relative;">';
 h+='<button onclick="event.stopPropagation();toggleAccountMenu()" style="display:flex;align-items:center;gap:9px;border:1px solid var(--border2);background:var(--surface);padding:5px 11px 5px 6px;border-radius:12px;cursor:pointer;">'
  +avatarBox(m.name,m.account,m.color,30,9,12)
  +'<div style="display:flex;flex-direction:column;align-items:flex-start;line-height:1.1;">'
  +'<span style="font:600 13px \'Space Grotesk\';color:var(--text);">'+esc(m.name)+'</span>'
  +'<span style="font-size:10px;color:var(--faint);">'+esc(m.platLabel)+'</span></div>'
  +'<span style="color:var(--faint);font-size:11px;margin-left:2px;">▾</span></button>';
 if(state.accountMenuOpen){
   h+='<div onclick="closeAccountMenu()" style="position:fixed;inset:0;z-index:35;"></div>';
   h+='<div style="position:absolute;right:0;top:calc(100% + 8px);z-index:40;width:230px;background:var(--surface);border:1px solid var(--border2);border-radius:14px;box-shadow:0 16px 40px rgba(0,0,0,.4);padding:6px;">';
   h+='<div style="font-size:9.5px;color:var(--faint);letter-spacing:.16em;text-transform:uppercase;padding:8px 10px 6px;">Switch account</div>';
   D.accounts.forEach((o,i)=>{const om=accMeta(o);const active=i===state.accountIdx;
     h+='<button onclick="selectAccount('+i+')" style="display:flex;align-items:center;gap:11px;width:100%;border:none;background:'+(active?'var(--surfaceHover)':'transparent')+';padding:9px 10px;border-radius:10px;cursor:pointer;text-align:left;">'
      +avatarBox(om.name,om.account,om.color,34,10,13)
      +'<div style="flex:1;min-width:0;"><div style="font:600 13px \'Space Grotesk\';color:var(--text);">'+esc(om.name)+'</div>'
      +'<div style="font-size:11px;color:var(--dim);">'+esc(om.platLabel)+' · '+esc(om.totalLabel)+'</div></div>'
      +(active?'<span style="color:var(--accent);font-size:13px;font-weight:700;">●</span>':'')+'</button>';
   });
   h+='</div>';
 }
 h+='</div></div></header>';
 return h;
}

function playtimeHTML(a){
 const periods=[['today','Day'],['week','Week'],['month','Month'],['year','Year'],['all','All']];
 let h='<section style="min-width:0;display:flex;flex-direction:column;">';
 h+='<div style="display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:14px;flex-wrap:wrap;">';
 h+='<span style="font:600 11px \'JetBrains Mono\';letter-spacing:.2em;text-transform:uppercase;color:#2fd4a8;">Playtime</span>';
 h+='<div style="display:flex;gap:3px;background:var(--surface2,#1b1e27);border:1px solid var(--border);border-radius:10px;padding:3px;">';
 periods.forEach(([k,l])=>{const on=state.period===k;
   h+='<button onclick="setPeriod(\''+k+'\')" style="background:'+(on?'var(--surface)':'transparent')+';color:'+(on?'var(--text)':'var(--dim)')+';border:none;padding:6px 12px;border-radius:7px;font:600 11.5px \'Space Grotesk\';cursor:pointer;white-space:nowrap;box-shadow:'+(on?'0 1px 2px rgba(0,0,0,.25)':'none')+';">'+l+'</button>';});
 h+='</div></div>';
 h+='<div style="background:var(--surface,#14161d);border:1px solid var(--border);border-radius:18px;padding:20px 22px;flex:1;">';
 const c=currentChart;
 h+='<div style="display:flex;align-items:baseline;gap:14px;flex-wrap:wrap;margin-bottom:18px;">'
  +'<span style="font:700 34px \'Space Grotesk\';letter-spacing:-.02em;line-height:1;">'+esc(c.totalLabel)+'</span>'
  +'<span style="font-size:12.5px;color:var(--dim);">Peak <span style="color:var(--text);font-weight:600;">'+esc(c.peakLabel)+'</span></span></div>';
 h+='<div style="display:flex;gap:3px;align-items:flex-end;height:150px;">';
 c.bars.forEach(b=>{h+='<div title="'+esc(b.tip)+'" style="flex:1;height:'+b.pct+'%;background:linear-gradient(to top, #3ecf6b 0%, #bcd63f 36%, #f0913c 68%, #ec5350 100%);background-size:100% 150px;background-position:bottom;background-repeat:no-repeat;border-radius:3px 3px 1px 1px;min-height:4px;"></div>';});
 h+='</div><div style="display:flex;gap:3px;margin-top:8px;">';
 c.bars.forEach(b=>{h+='<span style="flex:1;text-align:center;font:500 9.5px \'JetBrains Mono\';color:var(--faint);white-space:nowrap;overflow:hidden;">'+esc(b.label)+'</span>';});
 h+='</div>';
 // donut + legend
 const dist=a.platformDistribution||[];let accp=0;
 const segs=dist.map(d=>{const col=plat(d.platform).color;const s=accp;accp+=d.pct;return col+' '+s.toFixed(2)+'% '+accp.toFixed(2)+'%';}).join(', ');
 const donut=dist.length?('conic-gradient('+segs+')'):'var(--surface2)';
 h+='<div style="display:flex;align-items:center;gap:22px;margin-top:22px;padding-top:20px;border-top:1px solid var(--border);flex-wrap:wrap;">';
 h+='<div style="position:relative;width:96px;height:96px;border-radius:50%;background:'+donut+';flex:none;">'
  +'<div style="position:absolute;inset:18px;border-radius:50%;background:var(--surface,#14161d);display:flex;flex-direction:column;align-items:center;justify-content:center;line-height:1;">'
  +'<span style="font-size:9px;color:var(--faint);text-transform:uppercase;letter-spacing:.1em;">Plat</span></div></div>';
 h+='<div style="flex:1;min-width:160px;display:flex;flex-direction:column;gap:9px;">';
 if(dist.length)dist.forEach(d=>{const pm=plat(d.platform);
   h+='<div style="display:flex;align-items:center;gap:10px;">'
    +'<span style="width:10px;height:10px;border-radius:3px;background:'+pm.color+';flex:none;"></span>'
    +'<span style="font:600 12.5px \'Space Grotesk\';color:'+pm.color+';width:54px;flex:none;">'+esc(pm.label)+'</span>'
    +'<span style="font:500 12px \'JetBrains Mono\';color:var(--dim);flex:1;">'+esc(formatH(d.seconds))+'</span>'
    +'<span style="font:600 12.5px \'JetBrains Mono\';color:var(--text);">'+Math.round(d.pct)+'%</span></div>';});
 else h+='<span style="font-size:12px;color:var(--faint);">No playtime yet</span>';
 h+='</div></div></div></section>';
 return h;
}

/* Game cover icon with graceful fallback: the striped platform-tinted initials box
   is the base layer; a real cover <img src="game-icon/{titleId}"> (relative for HA
   ingress) is overlaid on top and hides itself onerror (missing/404 icon), revealing
   the initials box underneath — so it never shows a broken-image glyph.
   The backend now serves portrait box-art, so the cover is laid out with
   object-fit:contain (whole cover, never squished/awkwardly cropped) over its own
   platform-tinted backing that fills the letterbox gaps so the initials never peek. */
function gameIconHTML(titleId,title,color,size,radius,fontSize,s1,s2){
 const box='<div style="position:absolute;inset:0;background:'+color+'1f;background-image:repeating-linear-gradient(135deg, '+color+'1a 0 '+s1+'px, transparent '+s1+'px '+s2+'px);display:flex;align-items:center;justify-content:center;font:700 '+fontSize+'px \'JetBrains Mono\';color:'+color+';">'+esc(initials(title))+'</div>';
 const img=titleId?('<img src="game-icon/'+encodeURIComponent(titleId)+'" alt="" loading="lazy" onerror="this.style.display=\'none\'" style="position:absolute;inset:0;width:100%;height:100%;object-fit:contain;object-position:center;background:'+color+'1f;display:block;">'):'';
 return '<div style="position:relative;width:'+size+'px;height:'+size+'px;border-radius:'+radius+'px;overflow:hidden;flex:none;border:1px solid '+color+'55;">'+box+img+'</div>';
}
/* Avatar overlay: a real PS3 avatar <img src="avatar/{account}"> sits over a colored
   initials box; onerror hides the img so the initials show through (never a broken
   glyph). Returned as an inline-flex <span> so it works both as a flex child (header
   switcher, dropdown, top-players) and inline (history player). */
function avatarImg(account){return account?('<img src="avatar/'+encodeURIComponent(account)+'" alt="" loading="lazy" onerror="this.style.display=\'none\'" style="position:absolute;inset:0;width:100%;height:100%;object-fit:cover;display:block;">'):'';}
function avatarBox(name,account,color,size,radius,fontSize){
 return '<span style="position:relative;display:inline-flex;flex:none;vertical-align:middle;overflow:hidden;width:'+size+'px;height:'+size+'px;border-radius:'+radius+'px;background:'+color+';align-items:center;justify-content:center;font:600 '+fontSize+'px \'Space Grotesk\';color:#fff;">'+esc(initials(name))+avatarImg(account)+'</span>';
}
/* Real trophy icon <img src="{iconUrl}"> overlaid on the rarity-tinted diamond frame;
   onerror hides the img so the diamond placeholder shows through. */
function trophyIconImg(url){return url?('<img src="'+esc(url)+'" alt="" loading="lazy" onerror="this.style.display=\'none\'" style="position:absolute;inset:0;width:100%;height:100%;object-fit:cover;display:block;">'):'';}
function gameRowHTML(g,i,withDivider,total){
 const pm=plat(g.platform);const rankColor=i<3?'var(--accent)':'var(--faint,#5b6070)';
 const divider=(withDivider&&i===total-1)?'1px solid transparent':'1px solid var(--border)';
 return '<div onclick="openGame(\''+esc(g.platform)+'\',\''+esc(g.titleId)+'\')" style="display:flex;align-items:center;gap:12px;padding:12px 6px;margin:0 -6px;border-bottom:'+divider+';cursor:pointer;border-radius:10px;">'
  +'<span style="width:18px;font:600 12px \'JetBrains Mono\';color:'+rankColor+';flex:none;">'+String(i+1).padStart(2,'0')+'</span>'
  +gameIconHTML(g.titleId,g.title,pm.color,42,10,12,6,13)
  +'<div style="flex:1;min-width:0;">'
  +'<div style="font:600 13.5px/1.2 \'Space Grotesk\';white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">'+esc(g.title)+'</div>'
  +'<div style="display:flex;align-items:center;gap:8px;margin-top:5px;">'
  +'<span style="background:'+pm.color+'1f;color:'+pm.color+';padding:2px 7px;border-radius:6px;font:600 9.5px \'JetBrains Mono\';flex:none;">'+esc(pm.label)+'</span>'
  +'<span style="font-size:11.5px;color:var(--dim);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">Last played '+esc(ago(g.lastPlayed))+'</span></div>'
  +'<div style="display:flex;align-items:center;gap:12px;margin-top:6px;font:600 11px \'JetBrains Mono\';">'
  +'<span style="color:#ffb648;white-space:nowrap;">◆ '+(g.trophies||0)+' trophies</span>'
  +'<span style="color:var(--dim);white-space:nowrap;">'+esc(plural(g.sessions,'session'))+'</span></div></div>'
  +'<span style="background:'+ACCENT+'24;color:'+ACCENT+';padding:5px 10px;border-radius:8px;font:600 11.5px \'JetBrains Mono\';white-space:nowrap;flex:none;">'+esc(formatH(g.totalSeconds))+'</span></div>';
}
function recentGamesHTML(a){
 const recent=a.games.slice(0,5);
 let h='<section style="min-width:0;display:flex;flex-direction:column;">';
 h+='<div style="display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:14px;">';
 h+='<span style="font:600 11px \'JetBrains Mono\';letter-spacing:.2em;text-transform:uppercase;color:#2fd4a8;">Recent Games</span>';
 h+='<button onclick="openGames()" style="border:1px solid var(--border);background:var(--surface);color:var(--dim);padding:6px 11px;border-radius:9px;font:600 11px \'Space Grotesk\';cursor:pointer;display:flex;align-items:center;gap:6px;">All games <span style="font-size:12px;">→</span></button></div>';
 h+='<div style="background:var(--surface,#14161d);border:1px solid var(--border);border-radius:18px;padding:8px 18px;flex:1;display:flex;flex-direction:column;">';
 h+='<div style="flex:1;display:flex;flex-direction:column;justify-content:space-between;">';
 if(recent.length)recent.forEach((g,i)=>{h+=gameRowHTML(g,i,true,recent.length);});
 else h+='<div style="padding:24px 4px;font-size:13px;color:var(--faint);">No games tracked yet.</div>';
 h+='</div></div></section>';
 return h;
}

function historyHTML(){
 const items=buildHistory();
 const filters=[['all','All'],['session','Sessions'],['trophy','Trophies']];
 let h='<section><div style="display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:14px;flex-wrap:wrap;">';
 h+='<div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap;">';
 h+='<span style="font:600 11px \'JetBrains Mono\';letter-spacing:.2em;text-transform:uppercase;color:#2fd4a8;">History</span>';
 // profile dropdown
 const profLabel=state.histProfile==='all'?'All profiles':(D.accounts[+state.histProfile]?D.accounts[+state.histProfile].name:'All profiles');
 h+='<div style="position:relative;">';
 h+='<button onclick="event.stopPropagation();toggleProfileMenu()" style="display:flex;align-items:center;gap:7px;border:1px solid var(--border2);background:var(--surface);color:var(--text);padding:6px 11px;border-radius:9px;font:600 11.5px \'Space Grotesk\';cursor:pointer;">'+esc(profLabel)+' <span style="color:var(--faint);font-size:10px;">▾</span></button>';
 if(state.histMenuOpen){
   h+='<div onclick="closeProfileMenu()" style="position:fixed;inset:0;z-index:35;"></div>';
   h+='<div style="position:absolute;left:0;top:calc(100% + 8px);z-index:40;width:190px;background:var(--surface);border:1px solid var(--border2);border-radius:12px;box-shadow:0 16px 40px rgba(0,0,0,.4);padding:6px;">';
   const opts=[['all','All profiles']].concat(D.accounts.map((a,i)=>[String(i),a.name]));
   opts.forEach(([v,l])=>{const active=String(state.histProfile)===v;
     h+='<button onclick="selectProfile(\''+v+'\')" style="display:flex;align-items:center;justify-content:space-between;width:100%;border:none;background:'+(active?'var(--surfaceHover)':'transparent')+';padding:9px 11px;border-radius:9px;cursor:pointer;text-align:left;font:600 12.5px \'Space Grotesk\';color:var(--text);">'+esc(l)+(active?'<span style="color:var(--accent);font-size:11px;">●</span>':'')+'</button>';});
   h+='</div>';
 }
 h+='</div></div>';
 h+='<div style="display:flex;gap:7px;flex-wrap:wrap;">';
 filters.forEach(([k,l])=>{const on=state.histFilter===k;
   h+='<button onclick="setHistFilter(\''+k+'\')" style="background:'+(on?'var(--surface2)':'transparent')+';color:'+(on?'var(--text)':'var(--dim)')+';border:1px solid '+(on?'var(--border2)':'var(--border)')+';padding:6px 12px;border-radius:9px;font:600 11.5px \'Space Grotesk\';cursor:pointer;white-space:nowrap;">'+l+'</button>';});
 h+='</div></div>';
 h+='<div style="background:var(--surface,#14161d);border:1px solid var(--border);border-radius:18px;padding:6px 22px 14px;">';
 if(!items.length){h+='<div style="padding:26px 4px;text-align:center;font-size:13px;color:var(--faint);">No activity in this view.</div>';}
 else{
   let lastDate='';let group=[];
   const flush=()=>{if(!group.length)return;const t=group.filter(i=>i.kind==='trophy').length,s=group.length-t;
     const parts=[];if(s)parts.push(plural(s,'session'));if(t)parts.push(t+' '+(t===1?'trophy':'trophies'));
     h+='<div style="display:flex;align-items:center;gap:12px;padding:18px 0 10px;">'
      +'<span style="font:600 11px \'JetBrains Mono\';letter-spacing:.12em;text-transform:uppercase;color:var(--dim);">'+esc(dateLabel(lastDate))+'</span>'
      +'<span style="flex:1;height:1px;background:var(--border);"></span>'
      +'<span style="font-size:11px;color:var(--faint);">'+esc(parts.join(' · '))+'</span></div>';
     group.forEach(it=>{h+=historyItemHTML(it);});group=[];};
   items.forEach(it=>{const d=String(it.dt||'').slice(0,10);if(d!==lastDate){flush();lastDate=d;}group.push(it);});
   flush();
 }
 h+='</div></section>';
 return h;
}
function historyItemHTML(it){
 const pm=plat(it.platform);const time=String(it.dt||'').slice(11,16);
 let icon,title,titleColor,subRest,rightMain,rightColor,rightSub,onclick,cursor='pointer';
 if(it.kind==='trophy'){const rr=rarity(it.rate);
   icon='<div style="position:relative;overflow:hidden;width:44px;height:44px;border-radius:11px;background:'+rr.color+'1a;border:1px solid '+rr.color+'40;display:flex;align-items:center;justify-content:center;flex:none;"><div style="width:14px;height:14px;background:'+rr.color+';transform:rotate(45deg);border-radius:3px;"></div>'+trophyIconImg(it.iconUrl)+'</div>';
   title=esc(it.name);titleColor='var(--accent)';subRest=' · '+esc(it.game||'')+' — '+esc(it.desc||'');
   rightMain=it.rate!=null?(+it.rate).toFixed(1)+'%':'—';rightColor=rr.color;rightSub=rr.label;
   const idx=POP.push({name:it.name,desc:it.desc,pctLabel:rightMain,rarityColor:rr.color,rarityLabel:rr.label,
     game:it.game,platLabel:pm.label,platColor:pm.color,player:it.playerName,playerColor:it.playerColor,iconUrl:it.iconUrl})-1;
   onclick='openTrophyPopup('+idx+')';
 }else{
   icon='<div style="width:44px;height:44px;border-radius:11px;background:color-mix(in oklab, var(--accent) 13%, transparent);border:1px solid color-mix(in oklab, var(--accent) 30%, transparent);display:flex;align-items:center;justify-content:center;flex:none;"><div style="width:0;height:0;border-left:11px solid var(--accent);border-top:7px solid transparent;border-bottom:7px solid transparent;margin-left:3px;"></div></div>';
   title='Played '+esc(it.title);titleColor='var(--text)';subRest=' · Session';
   rightMain=formatH(it.seconds);rightColor='var(--accent)';rightSub='play time';
   onclick='openGame(\''+esc(it.platform)+'\',\''+esc(it.titleId)+'\')';
 }
 return '<div onclick="'+onclick+'" style="display:flex;align-items:center;gap:15px;padding:11px 6px;margin:0 -6px;border-bottom:1px solid var(--border,rgba(255,255,255,.05));cursor:'+cursor+';border-radius:10px;">'
  +'<span style="font:500 12px \'JetBrains Mono\';color:var(--faint);width:42px;flex:none;">'+esc(time)+'</span>'
  +icon
  +'<div style="flex:1;min-width:0;"><div style="display:flex;align-items:center;gap:9px;flex-wrap:wrap;">'
  +'<span style="font:600 14px \'Space Grotesk\';color:'+titleColor+';">'+title+'</span>'
  +'<span style="background:'+pm.color+'1f;color:'+pm.color+';padding:2px 8px;border-radius:6px;font:600 10px \'JetBrains Mono\';">'+esc(pm.label)+'</span></div>'
  +'<div style="font-size:12.5px;color:var(--dim);margin-top:3px;">'+avatarBox(it.playerName,it.account,it.playerColor,16,5,8)+' <span style="color:'+it.playerColor+';font-weight:600;">'+esc(it.playerName)+'</span>'+subRest+'</div></div>'
  +'<div style="display:flex;flex-direction:column;align-items:flex-end;flex:none;line-height:1.25;">'
  +'<span style="font:700 13px \'JetBrains Mono\';color:'+rightColor+';">'+esc(rightMain)+'</span>'
  +'<span style="font-size:9.5px;color:var(--faint);text-transform:uppercase;letter-spacing:.08em;">'+esc(rightSub)+'</span></div></div>';
}

/* ---- modals ---- */
function gameCardHTML(g,i){
 const pm=plat(g.platform);const rankColor=i<3?'var(--accent)':'var(--faint,#5b6070)';
 return '<div onclick="openGame(\''+esc(g.platform)+'\',\''+esc(g.titleId)+'\')" style="display:flex;align-items:center;gap:14px;background:var(--surface2,#1b1e27);border:1px solid var(--border);border-radius:14px;padding:14px 16px;cursor:pointer;">'
  +'<span style="width:20px;font:600 12.5px \'JetBrains Mono\';color:'+rankColor+';flex:none;">'+String(i+1).padStart(2,'0')+'</span>'
  +gameIconHTML(g.titleId,g.title,pm.color,46,11,13,6,13)
  +'<div style="flex:1;min-width:0;"><div style="font:600 14px/1.2 \'Space Grotesk\';white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">'+esc(g.title)+'</div>'
  +'<div style="display:flex;align-items:center;gap:10px;margin-top:6px;font:600 11px \'JetBrains Mono\';">'
  +'<span style="color:#ffb648;white-space:nowrap;">◆ '+(g.trophies||0)+' trophies</span>'
  +'<span style="color:var(--dim);white-space:nowrap;">'+esc(plural(g.sessions,'session'))+'</span></div></div>'
  +'<div style="display:flex;flex-direction:column;align-items:flex-end;gap:5px;flex:none;">'
  +'<span style="background:'+ACCENT+'24;color:'+ACCENT+';padding:5px 10px;border-radius:8px;font:600 11.5px \'JetBrains Mono\';white-space:nowrap;">'+esc(formatH(g.totalSeconds))+'</span>'
  +'<span style="font-size:10.5px;color:var(--faint);">'+esc(ago(g.lastPlayed))+'</span></div></div>';
}
function gamesModalHTML(a){
 const m=accMeta(a);
 let h='<div onclick="back()" style="position:fixed;inset:0;z-index:50;background:color-mix(in oklab, var(--bg,#0b0d12) 58%, transparent);backdrop-filter:blur(8px);-webkit-backdrop-filter:blur(8px);display:flex;align-items:flex-start;justify-content:center;padding:48px 24px;overflow-y:auto;">';
 h+='<div onclick="event.stopPropagation()" style="width:100%;max-width:920px;background:var(--surface,#14161d);border:1px solid var(--border2);border-radius:20px;box-shadow:0 30px 90px rgba(0,0,0,.55);padding:24px 26px;animation:ptPop .24s cubic-bezier(.2,.85,.3,1) forwards;">';
 h+='<div style="display:flex;align-items:center;gap:12px;margin-bottom:20px;">'
  +'<span style="font:700 22px \'Space Grotesk\';letter-spacing:-.02em;">All Games</span>'
  +'<span style="font-size:13px;color:var(--dim);">'+esc(m.name)+' · '+esc(m.platLabel)+'</span>'
  +'<div style="flex:1;"></div>'
  +'<button onclick="back()" style="width:34px;height:34px;border-radius:10px;border:1px solid var(--border);background:var(--surface2);color:var(--dim);font-size:16px;cursor:pointer;display:flex;align-items:center;justify-content:center;">✕</button></div>';
 h+='<div style="display:grid;grid-template-columns:repeat(2,1fr);gap:14px;">';
 if(a.games.length)a.games.forEach((g,i)=>{h+=gameCardHTML(g,i);});
 else h+='<div style="color:var(--faint);font-size:13px;">No games tracked yet.</div>';
 h+='</div></div></div>';
 return h;
}

function computeGameDetailLocal(platform,titleId){
 const sess=D.sessions.filter(s=>s.titleId===titleId&&(!platform||s.platform===platform));
 const title=(sess[0]&&sess[0].title)||titleId;
 const plt=(sess[0]&&sess[0].platform)||platform||'';
 const total=sess.reduce((x,s)=>x+s.seconds,0);
 const pl={};sess.forEach(s=>{(pl[s.account]||(pl[s.account]={sec:0,n:0}));pl[s.account].sec+=s.seconds;pl[s.account].n++;});
 const troMap={};D.trophies.forEach(t=>{if(t.title===title)troMap[t.account]=t.earnedCount;});
 const players=Object.entries(pl).map(([acc,v])=>{const oi=ownerIdx(plt,acc);const nm=oi>=0?D.accounts[oi].name:acc;
   return {name:nm,color:palColor(nm),initials:initials(nm),account:acc,sec:v.sec,sessions:v.n,trophies:troMap[acc]||0};})
   .sort((x,y)=>y.sec-x.sec).slice(0,4);
 const last=sess.reduce((m,s)=>(!m||s.started>m)?s.started:m,null);
 const troCount=Object.values(troMap).reduce((x,y)=>x+y,0);
 return {title,platform:plt,init:initials(title),totalSeconds:total,sessions:sess.length,
   avgSeconds:sess.length?total/sess.length:0,players,trophies:[],trophyCount:troCount,lastPlayed:last};
}
async function openGame(platform,titleId){
 state.prevView=state.view==='game'?state.prevView:state.view;
 state.activeGame={platform,titleId};
 state.gameDetail=computeGameDetailLocal(platform,titleId);
 state.view='game';render();
 // enrich with live per-game players + full trophy list
 try{const r=await fetchJSON('games/'+encodeURIComponent(platform)+'/'+encodeURIComponent(titleId));
   if(state.view!=='game'||!state.activeGame||state.activeGame.titleId!==titleId)return;
   const players=(r.players||[]).map(p=>{const nm=p.person||p.account;
     return {name:nm,color:palColor(nm),initials:initials(nm),account:p.account,sec:p.seconds,sessions:p.sessions,trophies:p.trophies||0};})
     .sort((x,y)=>y.sec-x.sec).slice(0,4);
   const tro=(r.trophies||[]).map(t=>({id:t.id,name:t.name,desc:t.desc,grade:t.grade,
     unlocked:t.unlocked,rate:t.rarityPct,earnedAt:t.earnedAt,iconUrl:t.iconUrl}));
   state.gameDetail={title:r.title||state.gameDetail.title,platform:r.platform||platform,
     init:initials(r.title||state.gameDetail.title),totalSeconds:r.totalSeconds,sessions:r.sessions,
     avgSeconds:r.avgSession,players,trophies:tro,trophyCount:tro.filter(t=>t.unlocked!==false).length,
     lastPlayed:r.lastPlayed};
   render();
 }catch(e){/* keep local fallback */}
}
function gameModalHTML(){
 const g=state.gameDetail;if(!g)return '';
 const pm=plat(g.platform);
 const tiles=[['Total time',formatH(g.totalSeconds)],['Sessions',String(g.sessions)],
   ['Trophies',String(g.trophyCount!=null?g.trophyCount:0)],['Avg session',formatH(g.avgSeconds)],
   ['Players',String(g.players.length)],['Last played',ago(g.lastPlayed)]];
 let h='<div onclick="back()" style="position:fixed;inset:0;z-index:52;background:color-mix(in oklab, var(--bg,#0b0d12) 58%, transparent);backdrop-filter:blur(8px);-webkit-backdrop-filter:blur(8px);display:flex;align-items:flex-start;justify-content:center;padding:42px 24px;overflow-y:auto;">';
 h+='<div onclick="event.stopPropagation()" style="width:100%;max-width:880px;background:var(--surface,#14161d);border:1px solid var(--border2);border-radius:20px;box-shadow:0 30px 90px rgba(0,0,0,.55);padding:26px 28px;animation:ptPop .24s cubic-bezier(.2,.85,.3,1) forwards;">';
 h+='<div style="display:flex;align-items:center;gap:16px;margin-bottom:22px;">'
  +gameIconHTML(state.activeGame?state.activeGame.titleId:'',g.title,pm.color,58,14,17,7,15)
  +'<div style="flex:1;min-width:0;"><div style="font:700 24px \'Space Grotesk\';letter-spacing:-.02em;">'+esc(g.title)+'</div>'
  +'<div style="margin-top:6px;"><span style="background:'+pm.color+'1f;color:'+pm.color+';padding:3px 9px;border-radius:7px;font:600 11px \'JetBrains Mono\';">'+esc(pm.label)+'</span></div></div>'
  +'<button onclick="back()" style="width:34px;height:34px;border-radius:10px;border:1px solid var(--border);background:var(--surface2);color:var(--dim);font-size:16px;cursor:pointer;display:flex;align-items:center;justify-content:center;flex:none;">✕</button></div>';
 h+='<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:24px;">';
 tiles.forEach(([l,v])=>{h+='<div style="background:var(--surface2,#1b1e27);border:1px solid var(--border);border-radius:14px;padding:15px 17px;">'
   +'<div style="font-size:10px;color:var(--faint);text-transform:uppercase;letter-spacing:.12em;">'+esc(l)+'</div>'
   +'<div style="font:700 22px \'Space Grotesk\';margin-top:7px;letter-spacing:-.01em;">'+esc(v)+'</div></div>';});
 h+='</div>';
 h+='<div style="display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1.2fr);gap:20px;align-items:start;">';
 // top players
 h+='<div><span style="display:block;font:600 11px \'JetBrains Mono\';letter-spacing:.2em;text-transform:uppercase;color:#2fd4a8;margin-bottom:13px;">Top Players</span><div style="display:flex;flex-direction:column;gap:2px;">';
 if(g.players.length)g.players.forEach((p,i)=>{h+='<div style="display:flex;align-items:center;gap:12px;padding:11px 2px;border-bottom:1px solid var(--border,rgba(255,255,255,.06));">'
   +'<span style="width:18px;font:600 12px \'JetBrains Mono\';color:var(--faint);flex:none;">'+String(i+1).padStart(2,'0')+'</span>'
   +avatarBox(p.name,p.account,p.color,36,11,12.5)
   +'<div style="flex:1;min-width:0;"><div style="font:600 13px \'Space Grotesk\';white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">'+esc(p.name)+'</div>'
   +'<div style="font-size:11px;color:var(--dim);margin-top:2px;">'+esc(plural(p.sessions,'session'))+' · <span style="color:#ffb648;">◆ '+(p.trophies||0)+'</span></div></div>'
   +'<span style="background:'+ACCENT+'24;color:'+ACCENT+';padding:4px 9px;border-radius:8px;font:600 11px \'JetBrains Mono\';white-space:nowrap;flex:none;">'+esc(formatH(p.sec))+'</span></div>';});
 else h+='<div style="color:var(--faint);font-size:12.5px;padding:8px 2px;">No sessions yet.</div>';
 h+='</div></div>';
 // trophies
 h+='<div><span style="display:block;font:600 11px \'JetBrains Mono\';letter-spacing:.2em;text-transform:uppercase;color:#2fd4a8;margin-bottom:13px;">Trophies</span>';
 const tro=(g.trophies||[]).filter(t=>t.unlocked!==false);
 if(tro.length){h+='<div style="display:flex;flex-direction:column;gap:2px;">';
   tro.forEach(t=>{const rr=rarity(t.rate);
     const idx=POP.push({name:t.name,desc:t.desc,pctLabel:t.rate!=null?(+t.rate).toFixed(1)+'%':'—',
       rarityColor:rr.color,rarityLabel:rr.label,game:g.title,platLabel:pm.label,platColor:pm.color,
       player:'',playerColor:'var(--dim)',iconUrl:t.iconUrl})-1;
     h+='<div onclick="openTrophyPopup('+idx+')" style="display:flex;align-items:center;gap:13px;padding:11px 6px;margin:0 -6px;border-bottom:1px solid var(--border,rgba(255,255,255,.06));cursor:pointer;border-radius:10px;">'
      +'<div style="position:relative;overflow:hidden;width:42px;height:42px;border-radius:11px;background:'+rr.color+'1a;border:1px solid '+rr.color+'40;display:flex;align-items:center;justify-content:center;flex:none;"><div style="width:13px;height:13px;background:'+rr.color+';transform:rotate(45deg);border-radius:3px;"></div>'+trophyIconImg(t.iconUrl)+'</div>'
      +'<div style="flex:1;min-width:0;"><div style="font:600 13.5px \'Space Grotesk\';color:var(--accent);">'+esc(t.name)+'</div>'
      +'<div style="font-size:11.5px;color:var(--dim);margin-top:2px;">'+esc(t.desc||'')+'</div></div>'
      +'<div style="display:flex;flex-direction:column;align-items:flex-end;flex:none;line-height:1.25;">'
      +'<span style="font:700 12.5px \'JetBrains Mono\';color:'+rr.color+';">'+(t.rate!=null?(+t.rate).toFixed(1)+'%':'—')+'</span>'
      +'<span style="font-size:9px;color:var(--faint);text-transform:uppercase;letter-spacing:.08em;">'+esc(rr.label)+'</span></div></div>';});
   h+='</div>';
 }else{
   h+='<div style="background:var(--surface2,#1b1e27);border:1px dashed var(--border2);border-radius:14px;padding:24px;text-align:center;font-size:12.5px;color:var(--faint);">No tracked trophies for this game yet</div>';
 }
 h+='</div></div></div></div>';
 return h;
}

function trophyPopupHTML(t){
 return '<div onclick="closeTrophy()" style="position:fixed;inset:0;z-index:60;background:color-mix(in oklab, var(--bg,#0b0d12) 55%, transparent);backdrop-filter:blur(9px);-webkit-backdrop-filter:blur(9px);display:flex;align-items:center;justify-content:center;padding:24px;">'
  +'<div onclick="event.stopPropagation()" style="width:100%;max-width:420px;background:var(--surface,#14161d);border:1px solid var(--border2);border-radius:20px;box-shadow:0 30px 90px rgba(0,0,0,.55);padding:26px;text-align:center;animation:ptPop .24s cubic-bezier(.2,.85,.3,1) forwards;">'
  +'<div style="position:relative;overflow:hidden;width:78px;height:78px;margin:4px auto 0;border-radius:20px;background:'+t.rarityColor+'1a;border:1px solid '+t.rarityColor+'55;display:flex;align-items:center;justify-content:center;"><div style="width:26px;height:26px;background:'+t.rarityColor+';transform:rotate(45deg);border-radius:5px;"></div>'+trophyIconImg(t.iconUrl)+'</div>'
  +'<div style="font:700 19px \'Space Grotesk\';margin-top:16px;letter-spacing:-.01em;">'+esc(t.name)+'</div>'
  +'<div style="display:inline-flex;align-items:center;gap:8px;margin-top:9px;">'
  +'<span style="background:'+t.rarityColor+'22;color:'+t.rarityColor+';padding:3px 10px;border-radius:7px;font:600 11px \'JetBrains Mono\';text-transform:uppercase;letter-spacing:.06em;">'+esc(t.rarityLabel)+'</span>'
  +'<span style="font:700 13px \'JetBrains Mono\';color:'+t.rarityColor+';">'+esc(t.pctLabel)+'</span></div>'
  +'<div style="font-size:13px;color:var(--dim);margin-top:14px;line-height:1.5;">'+esc(t.desc||'')+'</div>'
  +'<div style="display:flex;align-items:center;justify-content:center;gap:8px;margin-top:18px;padding-top:16px;border-top:1px solid var(--border);font-size:12px;color:var(--dim);flex-wrap:wrap;">'
  +'<span style="font-weight:600;color:var(--text);">'+esc(t.game||'')+'</span>'
  +'<span style="background:'+t.platColor+'1f;color:'+t.platColor+';padding:2px 8px;border-radius:6px;font:600 10px \'JetBrains Mono\';">'+esc(t.platLabel)+'</span>'
  +(t.player?'<span style="color:var(--faint);">·</span><span style="color:'+t.playerColor+';font-weight:600;">'+esc(t.player)+'</span>':'')+'</div></div></div>';
}

function emptyShell(){
 return '<div style="--accent:'+ACCENT+';min-height:100vh;background:var(--bg);color:var(--text);font-family:\'Space Grotesk\',system-ui,sans-serif;display:flex;align-items:center;justify-content:center;text-align:center;padding:40px;">'
  +'<div><div style="width:40px;height:40px;margin:0 auto 16px;background:linear-gradient(135deg,var(--accent),color-mix(in oklab,var(--accent) 55%,#fff));transform:rotate(45deg);border-radius:10px;"></div>'
  +'<div style="font:700 22px \'Space Grotesk\';">PLAYTRACE</div>'
  +'<div style="color:var(--dim);margin-top:8px;font-size:14px;">No tracked playtime yet — play a game with the tracker loaded.</div>'
  +'<div style="margin-top:18px;display:flex;gap:8px;justify-content:center;">'
  +'<a href="./people" style="border:1px solid var(--border);background:var(--surface);color:var(--dim);padding:9px 14px;border-radius:10px;font:600 12px \'Space Grotesk\';text-decoration:none;">People</a>'
  +'<a href="./config" style="border:1px solid var(--border);background:var(--surface);color:var(--dim);padding:9px 14px;border-radius:10px;font:600 12px \'Space Grotesk\';text-decoration:none;">Settings</a></div></div></div>';
}

/* ---- interactivity ---- */
function toggleTheme(){const t=state.theme==='dark'?'light':'dark';state.theme=t;
 document.documentElement.dataset.theme=t;try{localStorage.setItem('pt-theme',t);}catch(e){}render();}
function toggleAccountMenu(){state.accountMenuOpen=!state.accountMenuOpen;render();}
function closeAccountMenu(){state.accountMenuOpen=false;render();}
function selectAccount(i){state.accountIdx=i;state.accountMenuOpen=false;currentChart=computeChart(curAcc(),state.period);render();refreshChartLive();}
function setPeriod(p){state.period=p;currentChart=computeChart(curAcc(),p);render();refreshChartLive();}
function openGames(){state.prevView=state.view||'dashboard';state.view='games';render();}
function back(){state.view=(state.view==='game')?(state.prevView||'dashboard'):'dashboard';state.activeGame=null;state.gameDetail=null;render();}
function setHistFilter(k){state.histFilter=k;render();}
function toggleProfileMenu(){state.histMenuOpen=!state.histMenuOpen;render();}
function closeProfileMenu(){state.histMenuOpen=false;render();}
function selectProfile(v){state.histProfile=v;state.histMenuOpen=false;render();}
function openTrophyPopup(i){state.activeTrophy=POP[i];render();}
function closeTrophy(){state.activeTrophy=null;render();}
document.addEventListener('keydown',e=>{if(e.key==='Escape'){if(state.activeTrophy){closeTrophy();}else if(state.view!=='dashboard'){back();}}});

/* init */
render();
refreshChartLive();
</script></body></html>"""
