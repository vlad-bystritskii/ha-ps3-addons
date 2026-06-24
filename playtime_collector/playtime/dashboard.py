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
    return {
        "lastPoll": db.get_meta("last_poll_at"),
        "trackedSince": db.get_meta("tracked_since"),
        "now": [{"account": r["account"], "title": r["title"]} for r in open_rows],
        "summary": {"sec": summ["seconds_total"], "sessions": summ["sessions_total"]},
        "games": games, "sessions": sess, "trophies": troph,
    }


def render():
    return _PAGE.replace("/*DATA*/0", json.dumps(build_data()))


_PAGE = r"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="60">
<title>PS3 Playtime</title>
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'><text y='52' font-size='52'>🎮</text></svg>">
<style>
:root{--bg:#0a0e1a;--panel:#121a2c;--panel2:#0d1422;--head:#142a4e;--accent:#29c6e6;
--blue:#2a9df4;--white:#e9f1ff;--dim:#8aa0c0;--barbg:#1c2740}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--white);
font:15px/1.4 -apple-system,Segoe UI,Roboto,sans-serif}
.wrap{max-width:1000px;margin:0 auto;padding:16px}
.head{display:flex;align-items:center;gap:14px;border-left:6px solid var(--accent);
padding:12px 18px;background:var(--head);border-radius:12px}
.head h1{margin:0;font-size:23px;letter-spacing:.5px;flex:1}
.head .meta{text-align:right;color:var(--dim);font-size:12px}
.head .meta b{color:var(--accent);font-size:15px}
.live{display:inline-block;color:#37e08a;font-weight:600}
.chips{display:flex;gap:10px;flex-wrap:wrap;margin:14px 0}
.chip{background:var(--panel);border-radius:10px;padding:10px 14px;flex:1;min-width:110px}
.chip b{display:block;font-size:22px;color:var(--accent)}
.chip span{color:var(--dim);font-size:11px;text-transform:uppercase;letter-spacing:.5px}
.cols{display:flex;gap:14px;flex-wrap:wrap}.col{flex:1;min-width:300px}
h2{font-size:13px;color:var(--dim);text-transform:uppercase;letter-spacing:.6px;margin:22px 0 10px}
.now{background:linear-gradient(90deg,#163a2a,#121a2c);border:1px solid #2e7d52;
border-radius:10px;padding:12px 16px;margin-bottom:8px}
.row{background:var(--panel);border-radius:10px;padding:10px 14px;margin-bottom:8px;cursor:pointer;
transition:background .15s}.row:hover{background:#1a2742}
.row .top{display:flex;justify-content:space-between;align-items:baseline;gap:10px}
.row .rank{color:#6f86a8;font-weight:700;margin-right:8px}
.row .name{font-weight:600}.row .who{color:var(--dim);font-size:12px}
.row .time{color:var(--accent);font-weight:600;white-space:nowrap}
.bar{height:7px;background:var(--barbg);border-radius:5px;margin-top:8px;overflow:hidden}
.bar i{display:block;height:100%;background:linear-gradient(90deg,var(--blue),var(--accent))}
.days{display:flex;gap:5px;align-items:flex-end;height:120px;background:var(--panel);
border-radius:10px;padding:12px 10px;overflow-x:auto}
.day{flex:1;min-width:26px;display:flex;flex-direction:column;align-items:center;justify-content:flex-end;height:100%}
.day .b{width:100%;background:linear-gradient(180deg,var(--accent),var(--blue));border-radius:4px 4px 0 0;min-height:2px}
.day .v{font-size:9px;color:var(--dim);margin-bottom:3px;white-space:nowrap}
.day .d{font-size:9px;color:var(--dim);margin-top:4px}
.tp{display:flex;align-items:center;gap:10px;background:var(--panel);border-radius:9px;padding:8px 14px;margin-bottom:6px}
.tp .name{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.tp .med{color:var(--dim);font-size:12px;white-space:nowrap}.tp .pct{color:var(--accent);font-weight:600;width:46px;text-align:right}
.acct{margin:14px 0 6px;font-weight:600}
.foot{color:var(--dim);font-size:11px;text-align:center;margin:24px 0 8px}
.ov{position:fixed;inset:0;background:rgba(4,7,14,.8);display:none;align-items:flex-start;
justify-content:center;padding:30px 14px;overflow:auto;z-index:9}
.ov.on{display:flex}
.modal{background:#0e1626;border:1px solid #243a5e;border-radius:14px;max-width:880px;width:100%;padding:20px}
.modal .x{float:right;cursor:pointer;color:var(--dim);font-size:22px;line-height:1}
.modal h3{margin:0 0 4px;font-size:22px}
.mstats{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:8px;margin:14px 0}
.mstats .s{background:var(--panel);border-radius:9px;padding:9px 12px}
.mstats .s b{display:block;color:var(--accent);font-size:17px}.mstats .s span{color:var(--dim);font-size:11px}
.mcols{display:flex;gap:14px;flex-wrap:wrap}.mcol{flex:1;min-width:260px}
.jr{display:flex;justify-content:space-between;font-size:12px;padding:4px 0;border-bottom:1px solid #18233a;color:var(--dim)}
.jr b{color:var(--white);font-weight:500}
a{color:var(--accent);text-decoration:none}
</style></head><body><div class="wrap" id="app"></div>
<div class="ov" id="ov" onclick="if(event.target==this)closeM()"><div class="modal" id="modal"></div></div>
<script>
const D = /*DATA*/0;
const $=h=>{const d=document.createElement('div');d.innerHTML=h;return d.firstChild};
const esc=s=>String(s==null?'':s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const fmt=s=>{s=Math.round(s||0);const h=s/3600|0,m=(s%3600)/60|0;return h?h+'h '+String(m).padStart(2,'0')+'m':(m?m+'m':s+'s')};
const DOW=['Sun','Mon','Tue','Wed','Thu','Fri','Sat'];

function players(){
  const m={};
  D.sessions.forEach(s=>{const a=m[s.account]||(m[s.account]={account:s.account,sec:0,n:0,games:{}});a.sec+=s.seconds;a.n++;a.games[s.titleId]=1});
  // include trophy-only accounts
  D.trophies.forEach(t=>{if(!m[t.account])m[t.account]={account:t.account,sec:0,n:0,games:{}}});
  return Object.values(m).map(a=>({...a,games:Object.keys(a.games).length,
    tro:D.trophies.filter(t=>t.account===a.account).reduce((x,t)=>x+t.earnedCount,0)}))
    .sort((a,b)=>b.sec-a.sec);
}
function dailyBars(sessions,days){
  const today=new Date();const out=[];
  for(let i=days-1;i>=0;i--){const dt=new Date(today);dt.setDate(today.getDate()-i);
    const key=dt.toISOString().slice(0,10);
    const sec=sessions.filter(s=>(s.started||'').slice(0,10)===key).reduce((x,s)=>x+s.seconds,0);
    out.push({key,sec,label:String(dt.getDate()).padStart(2,'0')+'.'+String(dt.getMonth()+1).padStart(2,'0')})}
  return out;
}
function daysChart(sessions,days){
  const bars=dailyBars(sessions,days);const mx=Math.max(...bars.map(b=>b.sec),1);
  return '<div class="days">'+bars.map(b=>`<div class="day"><div class="v">${b.sec?fmt(b.sec):''}</div><div class="b" style="height:${b.sec?Math.max(4,b.sec*100/mx):0}%"></div><div class="d">${b.label}</div></div>`).join('')+'</div>';
}
function dowBars(sessions){
  const a=[0,0,0,0,0,0,0];sessions.forEach(s=>{const d=new Date(s.started);if(!isNaN(d))a[d.getDay()]+=s.seconds});
  const mx=Math.max(...a,1);
  return '<div class="days" style="height:90px">'+a.map((v,i)=>`<div class="day"><div class="v">${v?fmt(v):''}</div><div class="b" style="height:${v?Math.max(4,v*100/mx):0}%"></div><div class="d">${DOW[i]}</div></div>`).join('')+'</div>';
}
function medals(e){return `🥉${e.bronze||0} 🥈${e.silver||0} 🥇${e.gold||0} 🏆${e.platinum||0}`}

function render(){
  const p=players().filter(x=>x.sec>0),g=[...D.games].sort((a,b)=>b.totalSeconds-a.totalSeconds);
  const maxg=g.length?g[0].totalSeconds:1,maxp=p.length?p[0].sec:1;
  let h=`<div class="head"><h1>🎮 PS3 PLAYTIME</h1><div class="meta">last poll<br><b>${D.lastPoll?esc(D.lastPoll.slice(0,16).replace('T',' ')):'—'}</b></div></div>`;
  h+=`<div class="chips"><div class="chip"><b>${fmt(D.summary.sec)}</b><span>total played</span></div>
    <div class="chip"><b>${D.summary.sessions}</b><span>sessions</span></div>
    <div class="chip"><b>${g.length}</b><span>games</span></div>
    <div class="chip"><b>${D.now.length}</b><span>online now</span></div></div>`;
  if(D.now.length)h+='<h2>Now playing</h2>'+D.now.map(n=>`<div class="now"><span class="live">● LIVE</span> <b>${esc(n.title)}</b> · ${esc(n.account)}</div>`).join('');
  h+='<div class="cols">';
  h+='<div class="col"><h2>Top players</h2>'+(p.length?p.map((x,i)=>`<div class="row" onclick="openPlayer('${esc(x.account)}')"><div class="top"><div><span class="rank">${i+1}</span><span class="name">${esc(x.account)}</span> <span class="who">· ${x.n} sess · ${x.games} games · 🏆${x.tro}</span></div><div class="time">${fmt(x.sec)}</div></div><div class="bar"><i style="width:${x.sec*100/maxp}%"></i></div></div>`).join(''):'<div class="row">—</div>')+'</div>';
  h+='<div class="col"><h2>Top games</h2>'+(g.length?g.map((x,i)=>`<div class="row" onclick="openGame('${esc(x.titleId)}')"><div class="top"><div><span class="rank">${i+1}</span><span class="name">${esc(x.title)}</span> <span class="who">· ${esc(x.account)} · ${x.sessions} sess</span></div><div class="time">${fmt(x.totalSeconds)}</div></div><div class="bar"><i style="width:${x.totalSeconds*100/maxg}%"></i></div></div>`).join(''):'<div class="row">No sessions yet</div>')+'</div>';
  h+='</div>';
  h+='<h2>By day</h2>'+daysChart(D.sessions,14);
  // trophies grouped
  const ta={};D.trophies.forEach(t=>(ta[t.account]||(ta[t.account]=[])).push(t));
  if(D.trophies.length){h+='<h2>Trophies</h2>';
    Object.keys(ta).forEach(a=>{h+=`<div class="acct">👤 ${esc(a)}</div>`;
      ta[a].sort((x,y)=>y.earnedCount-x.earnedCount).forEach(t=>{const pc=t.totalCount?Math.round(t.earnedCount*100/t.totalCount):0;
        h+=`<div class="tp"><span class="name">${esc(t.title)}</span><span class="med">${medals(t.earned)}</span><span class="pct">${t.earnedCount}/${t.totalCount}</span><span class="pct">${pc}%</span></div>`})})}
  h+='<div class="foot">PS3 Playtime · auto-refresh 60s · <a href="/stats">/stats</a></div>';
  document.getElementById('app').innerHTML=h;
}

function openM(html){document.getElementById('modal').innerHTML='<span class="x" onclick="closeM()">✕</span>'+html;document.getElementById('ov').classList.add('on')}
function closeM(){document.getElementById('ov').classList.remove('on')}

function openPlayer(acc){
  const ss=D.sessions.filter(s=>s.account===acc);
  const tot=ss.reduce((x,s)=>x+s.seconds,0),n=ss.length;
  const gm={};ss.forEach(s=>{const k=s.titleId;(gm[k]||(gm[k]={title:s.title,sec:0,n:0}));gm[k].sec+=s.seconds;gm[k].n++});
  const topg=Object.values(gm).sort((a,b)=>b.sec-a.sec);
  const avg=n?tot/n:0,rec=ss.reduce((m,s)=>Math.max(m,s.seconds),0);
  const tro=D.trophies.filter(t=>t.account===acc);
  let h=`<h3>${esc(acc)}</h3>`;
  h+=`<div class="mstats"><div class="s"><b>${fmt(tot)}</b><span>total</span></div><div class="s"><b>${n}</b><span>sessions</span></div><div class="s"><b>${topg.length}</b><span>games</span></div><div class="s"><b>${fmt(avg)}</b><span>avg session</span></div><div class="s"><b>${fmt(rec)}</b><span>longest</span></div><div class="s"><b>${tro.reduce((x,t)=>x+t.earnedCount,0)}</b><span>trophies</span></div></div>`;
  h+='<div class="mcols"><div class="mcol"><h2>Top games</h2>'+(topg.length?topg.slice(0,12).map(x=>`<div class="tp"><span class="name">${esc(x.title)}</span><span class="med">${x.n} sess</span><span class="pct">${fmt(x.sec)}</span></div>`).join(''):'<div class="tp">—</div>')+'</div>';
  h+='<div class="mcol"><h2>Sessions log</h2>'+(ss.length?ss.slice(0,20).map(s=>`<div class="jr"><span>${esc((s.started||'').slice(0,16).replace('T',' '))} · <b>${esc(s.title)}</b></span><span>${fmt(s.seconds)}</span></div>`).join(''):'—')+'</div></div>';
  h+='<h2>By weekday</h2>'+dowBars(ss);
  openM(h);
}
function openGame(tid){
  const ss=D.sessions.filter(s=>s.titleId===tid);
  const title=(ss[0]&&ss[0].title)||(D.games.find(g=>g.titleId===tid)||{}).title||tid;
  const tot=ss.reduce((x,s)=>x+s.seconds,0);
  const pl={};ss.forEach(s=>{(pl[s.account]||(pl[s.account]={sec:0,n:0}));pl[s.account].sec+=s.seconds;pl[s.account].n++});
  const tops=Object.entries(pl).map(([a,v])=>({a,...v})).sort((x,y)=>y.sec-x.sec);
  const tr=D.trophies.filter(t=>t.title===title);
  let h=`<h3>${esc(title)}</h3>`;
  h+=`<div class="mstats"><div class="s"><b>${fmt(tot)}</b><span>total</span></div><div class="s"><b>${ss.length}</b><span>sessions</span></div><div class="s"><b>${tops.length}</b><span>players</span></div></div>`;
  h+='<div class="mcols"><div class="mcol"><h2>Top players</h2>'+tops.map(x=>`<div class="tp"><span class="name">${esc(x.a)}</span><span class="med">${x.n} sess</span><span class="pct">${fmt(x.sec)}</span></div>`).join('')+'</div>';
  h+='<div class="mcol"><h2>Sessions log</h2>'+(ss.length?ss.slice(0,20).map(s=>`<div class="jr"><span>${esc((s.started||'').slice(0,16).replace('T',' '))} · <b>${esc(s.account)}</b></span><span>${fmt(s.seconds)}</span></div>`).join(''):'—')+'</div></div>';
  if(tr.length){h+='<h2>Trophies</h2>'+tr.map(t=>{const pc=t.totalCount?Math.round(t.earnedCount*100/t.totalCount):0;return `<div class="tp"><span class="name">${esc(t.account)}</span><span class="med">${medals(t.earned)}</span><span class="pct">${t.earnedCount}/${t.totalCount}</span><span class="pct">${pc}%</span></div>`}).join('')}
  openM(h);
}
render();
</script></body></html>"""
