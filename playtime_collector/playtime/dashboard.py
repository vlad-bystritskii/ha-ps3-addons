"""Self-contained web dashboard (server embeds data as JSON; the browser renders
everything + opens player/game detail modals from that one payload — no token in
the page, one request)."""
import json

from . import config, db


def build_data():
    open_rows = db.open_sessions(None)
    open_keys = {(r["platform"], r["account"], r["title_id"]) for r in open_rows}
    games = [{
        "titleId": r["title_id"], "title": r["title"], "account": r["account"],
        "totalSeconds": r["total_seconds"], "sessions": r["sessions"],
        "playing": (r["platform"], r["account"], r["title_id"]) in open_keys,
    } for r in db.totals(None, None, None) if r["title_id"] != "PTVIEW001"]
    sess = [{
        "account": s["account"], "titleId": s["title_id"], "title": s["title"],
        "started": s["started_at"], "seconds": s["seconds"],
    } for s in db.list_sessions(None, None, None, 4000) if s["title_id"] != "PTVIEW001"]
    troph = [{
        "account": t["account"], "npcommid": t["npcommid"], "title": t["title"],
        "earned": t["earned"], "total": t["total"],
        "earnedCount": t["earnedCount"], "totalCount": t["totalCount"],
        "lastEarnedAt": t["lastEarnedAt"],
    } for t in db.query_trophies(config.PLATFORM, None)]
    summ = db.summary(None, None, None)
    feed = [{
        "account": r["account"], "game": r["game"], "npcommid": r["npcommid"],
        "trophyId": r["trophy_id"], "name": r["name"], "detail": r["detail"],
        "grade": r["grade"], "earnedAt": r["earned_at"], "rate": r["earned_rate"],
    } for r in db.recent_trophy_unlocks(config.PLATFORM, 60)]
    return {
        "lastPoll": db.get_meta("last_poll_at"),
        "trackedSince": db.get_meta("tracked_since"),
        "now": [{"account": r["account"], "title": r["title"]} for r in open_rows],
        "summary": {"sec": summ["seconds_total"], "sessions": summ["sessions_total"]},
        "games": games, "sessions": sess, "trophies": troph, "feed": feed,
    }


def render():
    return _PAGE.replace("/*DATA*/0", json.dumps(build_data()))


_PAGE = r"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="60">
<title>PS3 Playtime</title>
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'><text y='52' font-size='52'>🎮</text></svg>">
<style>
:root{--bg:#080b14;--panel:#101827;--panel2:#0c1320;--head:#13284a;--line:#1d2b45;
--accent:#29c6e6;--blue:#2a9df4;--white:#eef4ff;--dim:#8499b8;--barbg:#1a2438;
--warm1:#67e08a;--warm2:#e7d96a}
*{box-sizing:border-box}body{margin:0;background:
radial-gradient(1200px 500px at 50% -200px,#13203a,transparent),var(--bg);
color:var(--white);font:15px/1.45 -apple-system,Segoe UI,Roboto,sans-serif}
.wrap{max-width:1040px;margin:0 auto;padding:18px}
.head{display:flex;align-items:center;gap:14px;padding:16px 20px;border-radius:16px;
background:linear-gradient(120deg,#16305a,#0e1c33);border:1px solid var(--line)}
.head .logo{font-size:30px}.head h1{margin:0;font-size:24px;letter-spacing:.5px;flex:1}
.head .since{color:var(--dim);font-size:12px;font-weight:400;display:block;margin-top:2px}
.head .box{text-align:center;background:#0c1830;border:1px solid var(--line);border-radius:12px;padding:8px 16px}
.head .box b{display:block;color:var(--accent);font-size:15px}.head .box span{color:var(--dim);font-size:10px;text-transform:uppercase;letter-spacing:.5px}
.head .box.on b{color:#37e08a}
.chips{display:flex;gap:12px;flex-wrap:wrap;margin:16px 0}
.chip{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:14px 16px;flex:1;min-width:120px}
.chip b{display:block;font-size:26px;color:var(--accent);font-weight:700}
.chip span{color:var(--dim);font-size:11px;text-transform:uppercase;letter-spacing:.6px}
.cols{display:flex;gap:16px;flex-wrap:wrap}.col{flex:1;min-width:320px}
h2{font-size:12px;color:var(--dim);text-transform:uppercase;letter-spacing:.8px;margin:24px 0 12px;font-weight:700}
.card{background:var(--panel);border:1px solid var(--line);border-radius:14px;overflow:hidden}
.row{display:flex;flex-wrap:wrap;align-items:center;gap:12px;padding:12px 14px;cursor:pointer;border-bottom:1px solid var(--panel2);transition:background .15s,transform .1s}
.row:last-child{border-bottom:0}.row:hover{background:#16223b}
.rank{color:#56688a;font-weight:800;font-size:13px;width:20px;text-align:center;flex:none}
.av{width:42px;height:42px;border-radius:50%;flex:none;display:flex;align-items:center;justify-content:center;
font-weight:700;font-size:18px;color:#fff;box-shadow:inset 0 0 0 1px rgba(255,255,255,.08)}
.av.sq{border-radius:11px}
img.av{object-fit:cover;background:#1a1a22}
.row .mid{flex:1;min-width:0}.row .name{font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.row .who{color:var(--dim);font-size:12px;margin-top:2px}
.row .time{color:var(--accent);font-weight:700;white-space:nowrap;font-size:15px}
.row .barwrap{flex-basis:100%;height:6px;background:var(--barbg);border-radius:4px;margin-top:8px;overflow:hidden;order:9}
.row .barwrap i{display:block;height:100%;background:linear-gradient(90deg,var(--blue),var(--accent))}
.now{display:flex;align-items:center;gap:12px;background:linear-gradient(90deg,#14402b,#101827);
border:1px solid #2f8a57;border-radius:14px;padding:12px 16px;margin-bottom:8px}
.now .dot{width:9px;height:9px;border-radius:50%;background:#37e08a;box-shadow:0 0 8px #37e08a}
.days{display:flex;gap:6px;align-items:flex-end;height:170px;background:var(--panel);
border:1px solid var(--line);border-radius:14px;padding:14px 12px 10px;overflow-x:auto}
.day{flex:1;min-width:30px;display:flex;flex-direction:column;align-items:center;justify-content:flex-end;height:100%}
.day .b{width:100%;max-width:34px;background:linear-gradient(180deg,var(--warm2),var(--warm1));
border-radius:5px 5px 0 0;min-height:3px;box-shadow:0 0 12px rgba(120,220,140,.15)}
.day .v{font-size:10px;color:#b9c6dd;margin-bottom:4px;white-space:nowrap;font-weight:600}
.day .d{font-size:10px;color:var(--dim);margin-top:5px}
.tp{display:flex;align-items:center;gap:10px;padding:9px 14px;border-bottom:1px solid var(--panel2)}
.tp:last-child{border-bottom:0}.tp .name{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.tp .med{color:var(--dim);font-size:12px;white-space:nowrap}.tp .pct{color:var(--accent);font-weight:700;width:46px;text-align:right}
.tp .pbar{width:70px;height:6px;background:var(--barbg);border-radius:4px;overflow:hidden;flex:none}
.tp .pbar i{display:block;height:100%;background:linear-gradient(90deg,#9b6,#5ad17a)}
.acct{display:flex;align-items:center;gap:10px;margin:16px 0 8px;font-weight:700}
.fh{display:flex;align-items:center;gap:10px;margin:18px 0 8px;color:var(--dim);font-size:13px}
.fh b{color:var(--white)}.fh .fd{font-size:11px;color:#5a6c8a}
.fi{display:flex;gap:13px;align-items:center;background:var(--panel);border:1px solid var(--line);
border-left:3px solid #7a869c;border-radius:13px;padding:11px 14px;margin-bottom:8px}
.fi.g-bronze{border-left-color:#cd7f32}.fi.g-silver{border-left-color:#c4ccd8}
.fi.g-gold{border-left-color:#e8c34a}.fi.g-platinum{border-left-color:#7fd0ff}
.ticon{width:56px;height:56px;border-radius:11px;flex:none;background:#0c1320;object-fit:cover;
box-shadow:inset 0 0 0 1px rgba(255,255,255,.06)}
.ftext{flex:1;min-width:0}.tname{font-weight:600}
.trate{color:var(--accent);font-size:12px;font-weight:700;margin-left:6px}
.tdetail{color:var(--dim);font-size:12px;margin-top:2px}
.ftime{color:#5a6c8a;font-size:11px;margin-top:3px}
.foot{color:var(--dim);font-size:11px;text-align:center;margin:26px 0 10px}
.ov{position:fixed;inset:0;background:rgba(3,6,12,.82);backdrop-filter:blur(3px);display:none;
align-items:flex-start;justify-content:center;padding:30px 14px;overflow:auto;z-index:9}.ov.on{display:flex}
.modal{background:#0c1626;border:1px solid #26406a;border-radius:18px;max-width:900px;width:100%;padding:22px;
box-shadow:0 30px 80px rgba(0,0,0,.6)}
.modal .mh{display:flex;align-items:center;gap:14px}.modal .x{margin-left:auto;cursor:pointer;color:var(--dim);font-size:24px;line-height:1}
.modal h3{margin:0;font-size:24px}
.mstats{display:grid;grid-template-columns:repeat(auto-fit,minmax(110px,1fr));gap:10px;margin:16px 0}
.mstats .s{background:var(--panel);border:1px solid var(--line);border-radius:11px;padding:10px 12px}
.mstats .s b{display:block;color:var(--accent);font-size:18px;font-weight:700}.mstats .s span{color:var(--dim);font-size:11px}
.mcols{display:flex;gap:16px;flex-wrap:wrap}.mcol{flex:1;min-width:270px}
.jr{display:flex;justify-content:space-between;font-size:12px;padding:6px 0;border-bottom:1px solid #15203a;color:var(--dim)}
.jr b{color:var(--white);font-weight:500}
a{color:var(--accent);text-decoration:none}
</style></head><body><div class="wrap" id="app"></div>
<div class="ov" id="ov" onclick="if(event.target==this)closeM()"><div class="modal" id="modal"></div></div>
<script>
const D = /*DATA*/0;
const ICONBASE="",TOKEN="";   /* prod: same-origin, open icon route */
const esc=s=>String(s==null?'':s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const fmt=s=>{s=Math.round(s||0);const h=s/3600|0,m=(s%3600)/60|0;return h?h+'h '+String(m).padStart(2,'0')+'m':(m?m+'m':s+'s')};
const DOW=['Sun','Mon','Tue','Wed','Thu','Fri','Sat'];
const hue=s=>{let h=0;for(const c of String(s))h=c.charCodeAt(0)+((h<<5)-h);return Math.abs(h)%360};
const av=(s,sq)=>`<div class="av${sq?' sq':''}" style="background:linear-gradient(135deg,hsl(${hue(s)},55%,42%),hsl(${(hue(s)+40)%360},55%,30%))">${esc(String(s||'?')[0].toUpperCase())}</div>`;
// player avatar: real PS3 face when cached, else fall back to the initials circle
const pav=(s)=>`<img class="av" loading="lazy" src="${ICONBASE}/avatar/${encodeURIComponent(s||'?')}.png${TOKEN?('?token='+TOKEN):''}" data-s="${esc(s||'?')}" onerror="this.outerHTML=av(this.dataset.s)">`;

function players(){
  const m={};
  D.sessions.forEach(s=>{const a=m[s.account]||(m[s.account]={account:s.account,sec:0,n:0,games:{}});a.sec+=s.seconds;a.n++;a.games[s.titleId]=1});
  D.trophies.forEach(t=>{if(!m[t.account])m[t.account]={account:t.account,sec:0,n:0,games:{}}});
  return Object.values(m).map(a=>({...a,games:Object.keys(a.games).length,
    tro:D.trophies.filter(t=>t.account===a.account).reduce((x,t)=>x+t.earnedCount,0)})).sort((a,b)=>b.sec-a.sec);
}
function dailyBars(ss,days){const t=new Date(),out=[];for(let i=days-1;i>=0;i--){const dt=new Date(t);dt.setDate(t.getDate()-i);
  const k=dt.toISOString().slice(0,10);const sec=ss.filter(s=>(s.started||'').slice(0,10)===k).reduce((x,s)=>x+s.seconds,0);
  out.push({sec,label:String(dt.getDate()).padStart(2,'0')+'.'+String(dt.getMonth()+1).padStart(2,'0')})}return out}
function chart(bars,h){const mx=Math.max(...bars.map(b=>b.sec),1);return `<div class="days" style="height:${h}px">`+bars.map(b=>`<div class="day"><div class="v">${b.sec?fmt(b.sec):''}</div><div class="b" style="height:${b.sec?Math.max(4,b.sec*100/mx):0}%"></div><div class="d">${b.label}</div></div>`).join('')+'</div>'}
function dow(ss){const a=[0,0,0,0,0,0,0];ss.forEach(s=>{const d=new Date(s.started);if(!isNaN(d))a[d.getDay()]+=s.seconds});
  return chart(a.map((v,i)=>({sec:v,label:DOW[i]})),110)}
function medals(e){return `🥉${e.bronze||0} 🥈${e.silver||0} 🥇${e.gold||0} 🏆${e.platinum||0}`}
function tIcon(t){return `${ICONBASE}/trophy-icon/${encodeURIComponent(t.account)}/${encodeURIComponent(t.npcommid)}/${t.trophyId}`+(TOKEN?('?token='+TOKEN):'')}
function renderFeed(){
  const f=D.feed||[];if(!f.length)return '';
  let h='<h2>Trophy feed</h2>',last='';
  f.forEach(t=>{const date=(t.earnedAt||'').slice(0,10),key=t.account+'|'+(t.game||'')+'|'+date;
    if(key!==last){last=key;h+=`<div class="fh">${pav(t.account)}<div><b>${esc(t.account)}</b> · ${esc(t.game||'')}<div class="fd">${esc(date)}</div></div></div>`}
    const rate=(t.rate!=null)?`<span class="trate">${(+t.rate).toFixed(1)}%</span>`:'';
    h+=`<div class="fi g-${esc((t.grade||'').toLowerCase())}"><img class="ticon" loading="lazy" src="${tIcon(t)}" onerror="this.style.visibility='hidden'"><div class="ftext"><div class="tname">${esc(t.name)}${rate}</div><div class="tdetail">${esc(t.detail||'')}</div><div class="ftime">${esc((t.earnedAt||'').slice(11,16))}</div></div></div>`});
  return h;
}

function render(){
  const p=players().filter(x=>x.sec>0),g=[...D.games].sort((a,b)=>b.totalSeconds-a.totalSeconds);
  const maxg=g.length?g[0].totalSeconds:1,maxp=p.length?p[0].sec:1;
  const since=D.trackedSince?new Date(D.trackedSince).toLocaleDateString():'';
  let h=`<div class="head"><div class="logo">🎮</div><div style="flex:1"><h1>PS3 PLAYTIME</h1><span class="since">tracking since ${esc(since)}</span></div>
    <div class="box"><b>${D.lastPoll?esc(D.lastPoll.slice(11,16)):'—'}</b><span>last poll</span></div>
    <div class="box${D.now.length?' on':''}"><b>${D.now.length}</b><span>online</span></div></div>`;
  h+=`<div class="chips"><div class="chip"><b>${fmt(D.summary.sec)}</b><span>total played</span></div>
    <div class="chip"><b>${D.summary.sessions}</b><span>sessions</span></div>
    <div class="chip"><b>${g.length}</b><span>games</span></div>
    <div class="chip"><b>${p.length}</b><span>players</span></div></div>`;
  if(D.now.length)h+='<h2>Now playing</h2>'+D.now.map(n=>`<div class="now"><span class="dot"></span>${pav(n.account)}<div class="mid"><div class="name">${esc(n.title)}</div><div class="who">${esc(n.account)} · live</div></div></div>`).join('');
  h+='<div class="cols">';
  h+='<div class="col"><h2>Top players</h2><div class="card">'+(p.length?p.map((x,i)=>`<div class="row" onclick="openPlayer('${esc(x.account)}')"><span class="rank">${i+1}</span>${pav(x.account)}<div class="mid"><div class="name">${esc(x.account)}</div><div class="who">${x.n} sess · ${x.games} games · 🏆${x.tro}</div></div><div class="time">${fmt(x.sec)}</div><div class="barwrap"><i style="width:${x.sec*100/maxp}%"></i></div></div>`).join(''):'<div class="row">—</div>')+'</div></div>';
  h+='<div class="col"><h2>Top games</h2><div class="card">'+(g.length?g.map((x,i)=>`<div class="row" onclick="openGame('${esc(x.titleId)}')"><span class="rank">${i+1}</span>${av(x.title,1)}<div class="mid"><div class="name">${esc(x.title)}</div><div class="who">${esc(x.account)} · ${x.sessions} sess</div></div><div class="time">${fmt(x.totalSeconds)}</div><div class="barwrap"><i style="width:${x.totalSeconds*100/maxg}%"></i></div></div>`).join(''):'<div class="row">No sessions yet</div>')+'</div></div>';
  h+='</div>';
  h+='<h2>By day</h2>'+chart(dailyBars(D.sessions,14),170);
  h+=renderFeed();
  h+='<div class="foot">PS3 Playtime · auto-refresh 60s · <a href="/stats">/stats</a></div>';
  document.getElementById('app').innerHTML=h;
}
function openM(html){document.getElementById('modal').innerHTML=html;document.getElementById('ov').classList.add('on')}
function closeM(){document.getElementById('ov').classList.remove('on')}
function topMonth(ss){const m={};ss.forEach(s=>{const k=(s.started||'').slice(0,7);m[k]=(m[k]||0)+s.seconds});
  const e=Object.entries(m).sort((a,b)=>b[1]-a[1])[0];return e?e[0]:'—'}
function peakDay(ss){const m={};ss.forEach(s=>{const k=(s.started||'').slice(0,10);m[k]=(m[k]||0)+s.seconds});
  const e=Object.entries(m).sort((a,b)=>b[1]-a[1])[0];return e?(e[0].slice(5)+' '+fmt(e[1])):'—'}
function bestDow(ss){const a=[0,0,0,0,0,0,0];ss.forEach(s=>{const d=new Date(s.started);if(!isNaN(d))a[d.getDay()]+=s.seconds});
  let mi=0;a.forEach((v,i)=>{if(v>a[mi])mi=i});return a[mi]?DOW[mi]:'—'}

function openPlayer(acc){
  const ss=D.sessions.filter(s=>s.account===acc);
  const tot=ss.reduce((x,s)=>x+s.seconds,0),n=ss.length;
  const gm={};ss.forEach(s=>{(gm[s.titleId]||(gm[s.titleId]={title:s.title,sec:0,n:0}));gm[s.titleId].sec+=s.seconds;gm[s.titleId].n++});
  const topg=Object.values(gm).sort((a,b)=>b.sec-a.sec);
  const avg=n?tot/n:0,rec=ss.reduce((m,s)=>Math.max(m,s.seconds),0);
  const tro=D.trophies.filter(t=>t.account===acc);
  let h=`<div class="mh">${pav(acc)}<h3>${esc(acc)}</h3><span class="x" onclick="closeM()">✕</span></div>`;
  h+=`<div class="mstats"><div class="s"><b>${fmt(tot)}</b><span>total</span></div><div class="s"><b>${n}</b><span>sessions</span></div><div class="s"><b>${topg.length}</b><span>games</span></div><div class="s"><b>${fmt(avg)}</b><span>avg session</span></div><div class="s"><b>${fmt(rec)}</b><span>longest</span></div><div class="s"><b>${esc(bestDow(ss))}</b><span>best weekday</span></div><div class="s"><b>${esc(peakDay(ss))}</b><span>peak day</span></div><div class="s"><b>${tro.reduce((x,t)=>x+t.earnedCount,0)}</b><span>trophies</span></div></div>`;
  h+='<div class="mcols"><div class="mcol"><h2>Top games</h2><div class="card">'+(topg.length?topg.slice(0,12).map(x=>`<div class="tp">${av(x.title,1)}<span class="name">${esc(x.title)}</span><span class="med">${x.n} sess</span><span class="pct">${fmt(x.sec)}</span></div>`).join(''):'<div class="tp">—</div>')+'</div></div>';
  h+='<div class="mcol"><h2>Sessions log</h2><div class="card" style="padding:4px 14px">'+(ss.length?ss.slice(0,22).map(s=>`<div class="jr"><span>${esc((s.started||'').slice(0,16).replace('T',' '))} · <b>${esc(s.title)}</b></span><span>${fmt(s.seconds)}</span></div>`).join(''):'—')+'</div></div></div>';
  h+='<h2>By weekday</h2>'+dow(ss);
  openM(h);
}
function openGame(tid){
  const ss=D.sessions.filter(s=>s.titleId===tid);
  const title=(ss[0]&&ss[0].title)||(D.games.find(g=>g.titleId===tid)||{}).title||tid;
  const tot=ss.reduce((x,s)=>x+s.seconds,0);
  const pl={};ss.forEach(s=>{(pl[s.account]||(pl[s.account]={sec:0,n:0}));pl[s.account].sec+=s.seconds;pl[s.account].n++});
  const tops=Object.entries(pl).map(([a,v])=>({a,...v})).sort((x,y)=>y.sec-x.sec);
  const tr=D.trophies.filter(t=>t.title===title);
  let h=`<div class="mh">${av(title,1)}<h3>${esc(title)}</h3><span class="x" onclick="closeM()">✕</span></div>`;
  h+=`<div class="mstats"><div class="s"><b>${fmt(tot)}</b><span>total</span></div><div class="s"><b>${ss.length}</b><span>sessions</span></div><div class="s"><b>${tops.length}</b><span>players</span></div><div class="s"><b>${esc(peakDay(ss))}</b><span>peak day</span></div></div>`;
  h+='<div class="mcols"><div class="mcol"><h2>Top players</h2><div class="card">'+tops.map(x=>`<div class="tp">${pav(x.a)}<span class="name">${esc(x.a)}</span><span class="med">${x.n} sess</span><span class="pct">${fmt(x.sec)}</span></div>`).join('')+'</div></div>';
  h+='<div class="mcol"><h2>Sessions log</h2><div class="card" style="padding:4px 14px">'+(ss.length?ss.slice(0,22).map(s=>`<div class="jr"><span>${esc((s.started||'').slice(0,16).replace('T',' '))} · <b>${esc(s.account)}</b></span><span>${fmt(s.seconds)}</span></div>`).join(''):'—')+'</div></div></div>';
  if(tr.length){h+='<h2>Trophies</h2><div class="card">'+tr.map(t=>{const pc=t.totalCount?Math.round(t.earnedCount*100/t.totalCount):0;return `<div class="tp">${pav(t.account)}<span class="name">${esc(t.account)}</span><span class="med">${medals(t.earned)}</span><div class="pbar"><i style="width:${pc}%"></i></div><span class="pct">${t.earnedCount}/${t.totalCount}</span></div>`}).join('')+'</div>'}
  openM(h);
}
render();
</script></body></html>"""
