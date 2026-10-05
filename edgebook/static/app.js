/* Edgebook front-end (no dependencies, works offline) */
const $ = (s, r = document) => r.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const num = (v, d = 2) => Number(v).toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d });
const fm = (v, d = 2) => (v < 0 ? "-$" : "+$") + num(Math.abs(v), d);
const fmp = (v, d = 2) => (v < 0 ? "-$" : "$") + num(Math.abs(v), d);
const sg = v => (v > 0 ? "pos" : v < 0 ? "neg" : "mut");
const dur = s => s >= 3600 ? `${Math.floor(s / 3600)}h ${Math.round(s % 3600 / 60)}m` : s >= 60 ? `${Math.floor(s / 60)}m ${Math.round(s % 60)}s` : `${Math.round(s)}s`;
const ICON = {
  dash: '<path d="M3 13h8V3H3zM13 21h8V11h-8zM13 3v6h8V3zM3 21h8v-6H3z"/>',
  list: '<path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"/>',
  cal: '<rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/>',
  bulb: '<path d="M9 18h6M10 22h4M12 2a7 7 0 0 0-4 12.7c.6.5 1 1.2 1 2V17h6v-.3c0-.8.4-1.5 1-2A7 7 0 0 0 12 2z"/>',
  up: '<path d="M12 16V4M6 10l6-6 6 6M4 20h16"/>',
  gear: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>',
};
const ROUTES = [
  ["dashboard", "Dashboard", "dash"], ["trades", "Trades", "list"], ["calendar", "Calendar", "cal"],
  ["insights", "Insights", "bulb"], ["import", "Import", "up"], ["settings", "Settings", "gear"],
];
const S = { st: null, A: null, f: { preset: "all", from: "", to: "", inst: "", dir: "" }, cal: null, eqTab: "equity", sort: ["close", -1], q: "" };
const pref = {
  get(k, d) { try { return localStorage.getItem("eb." + k) || d; } catch { return d; } },
  set(k, v) { try { localStorage.setItem("eb." + k, v); } catch { } },
};

/* ---------- api ---------- */
async function api(path, body) {
  const r = await fetch(path, body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.error || r.statusText);
  return j;
}
function toast(msg) { const t = $("#toast"); t.textContent = msg; t.classList.add("on"); clearTimeout(toast.h); toast.h = setTimeout(() => t.classList.remove("on"), 2200); }
function applyTheme() {
  const t = pref.get("theme", "auto");
  document.documentElement.dataset.theme = t === "auto" ? (matchMedia("(prefers-color-scheme:dark)").matches ? "dark" : "light") : t;
  document.documentElement.dataset.colors = pref.get("colors", "gr");
}
matchMedia("(prefers-color-scheme:dark)").addEventListener?.("change", applyTheme);

/* ---------- data ---------- */
function qs() {
  const f = S.f, p = new URLSearchParams();
  let from = f.from, to = f.to;
  const last = S.st?.last;
  if (f.preset !== "all" && f.preset !== "custom" && last) {
    const d = new Date(last + "T12:00:00"), iso = x => x.toISOString().slice(0, 10);
    to = last;
    if (f.preset === "7") { d.setDate(d.getDate() - 6); from = iso(d); }
    if (f.preset === "30") { d.setDate(d.getDate() - 29); from = iso(d); }
    if (f.preset === "month") from = last.slice(0, 8) + "01";
    if (f.preset === "last") from = last;
  }
  if (from) p.set("from", from); if (to) p.set("to", to);
  if (f.inst) p.set("inst", f.inst); if (f.dir) p.set("dir", f.dir);
  return p.toString();
}
async function load() {
  S.st = await api("/api/state");
  S.A = await api("/api/analysis?" + qs());
  $("#dir").textContent = S.st.data_dir;
}
async function reload() { await load(); render(); }

/* ---------- tooltips ---------- */
document.addEventListener("mousemove", e => {
  const el = e.target.closest?.("[data-tip]"), tip = $("#tip");
  if (!el) { tip.style.display = "none"; return; }
  tip.textContent = el.dataset.tip; tip.style.display = "block";
  tip.style.left = Math.min(e.clientX + 14, innerWidth - tip.offsetWidth - 10) + "px";
  tip.style.top = Math.min(e.clientY + 16, innerHeight - tip.offsetHeight - 10) + "px";
});

/* ---------- chart builders (SVG strings) ---------- */
function equityChart(eq, mode) {
  const W = 760, H = 290, L = 54, R = 14, T = 22, B = 26;
  let pts = eq.map(p => ({ ...p })), vals;
  if (mode === "drawdown") { let pk = 0; pts.forEach(p => { pk = Math.max(pk, p.cum); p.v = p.cum - pk; }); }
  else pts.forEach(p => p.v = p.cum);
  const series = [{ v: 0, i: 0 }, ...pts];
  vals = series.map(p => p.v);
  let mx = Math.max(...vals), mn = Math.min(...vals);
  if (mx === mn) { mx += 1; mn -= 1; }
  const pad = (mx - mn) * .08; mx += pad; mn -= pad;
  const x = i => L + i / Math.max(1, series.length - 1) * (W - L - R), y = v => T + (mx - v) / (mx - mn) * (H - T - B);
  const step = niceStep((mx - mn) / 4), ticks = [];
  for (let t = Math.ceil(mn / step) * step; t <= mx; t += step) ticks.push(t);
  const line = series.map((p, i) => (i ? "L" : "M") + x(i).toFixed(1) + "," + y(p.v).toFixed(1)).join("");
  const area = line + `L${x(series.length - 1)},${y(0)}L${x(0)},${y(0)}Z`;
  let s = `<svg class="chart" viewBox="0 0 ${W} ${H}"><defs>
    <linearGradient id="gp" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="var(--pos)" stop-opacity=".35"/><stop offset="1" stop-color="var(--pos)" stop-opacity="0"/></linearGradient>
    <linearGradient id="gn" x1="0" y1="1" x2="0" y2="0"><stop offset="0" stop-color="var(--neg)" stop-opacity=".35"/><stop offset="1" stop-color="var(--neg)" stop-opacity="0"/></linearGradient>
    <clipPath id="cu"><rect x="0" y="0" width="${W}" height="${y(0)}"/></clipPath><clipPath id="cd"><rect x="0" y="${y(0)}" width="${W}" height="${H}"/></clipPath></defs>`;
  ticks.forEach(t => s += `<line class="gl" x1="${L}" x2="${W - R}" y1="${y(t)}" y2="${y(t)}"/><text x="${L - 8}" y="${y(t) + 4}" text-anchor="end">${t < 0 ? "-" : ""}$${compact(Math.abs(t))}</text>`);
  s += `<line class="zero" x1="${L}" x2="${W - R}" y1="${y(0)}" y2="${y(0)}"/>`;
  s += `<path d="${area}" fill="url(#gp)" clip-path="url(#cu)"/><path d="${area}" fill="url(#gn)" clip-path="url(#cd)"/>`;
  s += `<path d="${line}" fill="none" stroke="var(--accent)" stroke-width="2.2" stroke-linejoin="round" stroke-linecap="round"/>`;
  let prev = null, shown = 0;
  const days = new Set(pts.map(p => p.date)).size, every = Math.ceil(days / 8);
  pts.forEach((p, i) => {
    const px = x(i + 1);
    if (p.date !== prev) {
      if (prev !== null) s += `<line x1="${(x(i) + px) / 2}" x2="${(x(i) + px) / 2}" y1="${T - 6}" y2="${H - B}" stroke="var(--line)" stroke-dasharray="4 4"/>`;
      if (shown++ % every === 0) s += `<text x="${px - 4}" y="${H - 6}">${p.date.slice(5).replace("-", "/")}</text>`;
      prev = p.date;
    }
    const w = (W - L - R) / Math.max(1, series.length - 1);
    s += `<rect class="col" x="${px - w / 2}" y="${T - 6}" width="${w}" height="${H - T - B + 6}" data-tip="Trade #${p.i} · ${p.date}\nResult ${fm(p.net)}\n${mode === "drawdown" ? "Drawdown " + fmp(p.v) : "Equity " + fmp(p.cum)}"/>`;
    if (pts.length <= 90) s += `<circle cx="${px}" cy="${y(p.v)}" r="3.4" fill="${p.net >= 0 ? "var(--pos)" : "var(--neg)"}" stroke="var(--surface)" stroke-width="1.6" pointer-events="none"/>`;
  });
  return s + "</svg>";
}
function niceStep(raw) { const p = Math.pow(10, Math.floor(Math.log10(raw || 1))), r = raw / p; return (r < 1.5 ? 1 : r < 3.5 ? 2 : r < 7.5 ? 5 : 10) * p; }
function compact(v) { return v >= 1e6 ? (v / 1e6).toFixed(1) + "M" : v >= 1e4 ? (v / 1e3).toFixed(0) + "k" : v >= 1e3 ? (v / 1e3).toFixed(1) + "k" : String(Math.round(v)); }

function barChart(rows, label, tipf) {
  const W = 440, H = 230, L = 44, B = 26, T = 18;
  if (!rows.length) return `<div class="mut">No data</div>`;
  let mx = Math.max(0, ...rows.map(r => r.net)), mn = Math.min(0, ...rows.map(r => r.net));
  if (mx === mn) mx = 1;
  const dmx = mx, dmn = mn, span = mx - mn; if (mx > 0) mx += span * .12; if (mn < 0) mn -= span * .14;
  const y = v => T + (mx - v) / (mx - mn) * (H - T - B), cw = (W - L) / rows.length, bw = Math.min(40, cw * .62);
  let s = `<svg class="chart" viewBox="0 0 ${W} ${H}">`;
  [dmn, 0, dmx].forEach(v => s += `<line class="${v === 0 ? "zero" : "gl"}" x1="${L}" x2="${W}" y1="${y(v)}" y2="${y(v)}"/><text x="${L - 6}" y="${y(v) + 4}" text-anchor="end">${v < 0 ? "-" : ""}$${compact(Math.abs(v))}</text>`);
  rows.forEach((r, i) => {
    const cx = L + (i + .5) * cw, y0 = y(0), y1 = y(r.net), top = Math.min(y0, y1), h = Math.max(2, Math.abs(y1 - y0));
    s += `<g class="bg"><rect class="col" x="${cx - cw / 2}" y="${T - 8}" width="${cw}" height="${H - T - B + 8}" data-tip="${esc(tipf(r))}"/>
      <rect class="bar" x="${cx - bw / 2}" y="${top}" width="${bw}" height="${h}" rx="5" fill="${r.net >= 0 ? "var(--pos)" : "var(--neg)"}" pointer-events="none"/></g>
      <text x="${cx}" y="${H - 8}" text-anchor="middle">${esc(label(r))}</text>`;
    if (cw > 34) s += `<text x="${cx}" y="${r.net >= 0 ? top - 5 : top + h + 12}" text-anchor="middle" style="fill:var(--ink2);font-weight:600">${r.net < 0 ? "-" : ""}${compact(Math.abs(r.net))}</text>`;
  });
  return s + "</svg>";
}
function histChart(bins) {
  const W = 440, H = 230, L = 30, B = 28, T = 18;
  const mx = Math.max(...bins.map(b => b.n), 1), cw = (W - L) / bins.length;
  let s = `<svg class="chart" viewBox="0 0 ${W} ${H}"><line class="zero" x1="${L}" x2="${W}" y1="${H - B}" y2="${H - B}"/>`;
  bins.forEach((b, i) => {
    const h = b.n / mx * (H - B - T), x = L + i * cw, mid = (b.lo + b.hi) / 2;
    s += `<g class="bg"><rect class="col" x="${x}" y="${T - 6}" width="${cw}" height="${H - T - B + 6}" data-tip="${fm(b.lo, 0)} to ${fm(b.hi, 0)}\n${b.n} trade${b.n === 1 ? "" : "s"}"/>
      <rect class="bar" x="${x + 2}" y="${H - B - h}" width="${cw - 4}" height="${h}" rx="4" fill="${mid >= 0 ? "var(--pos)" : "var(--neg)"}" pointer-events="none"/></g>`;
    if (b.n) s += `<text x="${x + cw / 2}" y="${H - B - h - 5}" text-anchor="middle" style="fill:var(--ink2);font-weight:600">${b.n}</text>`;
    if (i % Math.ceil(bins.length / 7) === 0) s += `<text x="${x}" y="${H - 10}" text-anchor="middle">${b.lo < 0 ? "-" : ""}${compact(Math.abs(b.lo))}</text>`;
  });
  return s + "</svg>";
}
function hbars(rows, name, sub) {
  if (!rows.length) return `<div class="mut">Nothing yet. Tag trades with a setup or mistake in the Trades tab.</div>`;
  const mx = Math.max(0, ...rows.map(r => r.net)), mn = Math.min(0, ...rows.map(r => r.net)), span = (mx - mn) || 1, z = (-mn / span) * 100;
  return rows.map(r => {
    const w = Math.abs(r.net) / span * 100, left = r.net >= 0 ? z : z - w;
    return `<div class="hb" data-tip="${esc(name(r))}\n${r.trades} trades · win rate ${r.wr}%\nProfit factor ${r.pf ?? "n/a"} · avg ${fm(r.avg)}">
      <div class="n">${esc(name(r))}${sub ? `<small>${esc(sub(r))}</small>` : ""}</div>
      <div class="tr" style="--z:${z}%"><div class="bar" style="left:${left}%;width:${Math.max(w, .8)}%;background:${r.net >= 0 ? "var(--pos)" : "var(--neg)"}"></div></div>
      <div class="vv ${sg(r.net)}">${fm(r.net, 0)}</div></div>`;
  }).join("");
}
function ring(score) {
  const r = 54, c = 2 * Math.PI * r, col = score >= 70 ? "var(--pos)" : score >= 45 ? "var(--warn)" : "var(--neg)";
  return `<div class="ring"><svg viewBox="0 0 132 132" width="132" height="132"><circle cx="66" cy="66" r="${r}" fill="none" stroke="var(--surface2)" stroke-width="11"/>
    <circle cx="66" cy="66" r="${r}" fill="none" stroke="${col}" stroke-width="11" stroke-linecap="round" stroke-dasharray="${c * score / 100} ${c}" transform="rotate(-90 66 66)"/></svg>
    <b>${Math.round(score)}</b></div>`;
}
function donut(w, l) {
  const t = w + l || 1, r = 38, c = 2 * Math.PI * r;
  return `<svg viewBox="0 0 100 100" width="104" height="104"><circle cx="50" cy="50" r="${r}" fill="none" stroke="var(--neg)" stroke-width="12"/>
    <circle cx="50" cy="50" r="${r}" fill="none" stroke="var(--pos)" stroke-width="12" stroke-dasharray="${c * w / t} ${c}" transform="rotate(-90 50 50)" stroke-linecap="butt"/></svg>`;
}

/* ---------- calendar ---------- */
function calendarHTML(daily, nav = true) {
  if (!daily.length) return `<div class="mut">No trading days in this range.</div>`;
  if (!S.cal) S.cal = daily[daily.length - 1].date.slice(0, 7);
  const [Y, M] = S.cal.split("-").map(Number), map = Object.fromEntries(daily.map(d => [d.date, d]));
  const first = new Date(Y, M - 1, 1), start = new Date(Y, M - 1, 1 - first.getDay()), mx = Math.max(...daily.map(d => Math.abs(d.net)), 1);
  const iso = d => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  let h = `<div class="cal">` + ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"].map(d => `<div class="dh">${d}</div>`).join("") + `<div class="dh">Week</div>`;
  const weeks = Math.ceil((first.getDay() + new Date(Y, M, 0).getDate()) / 7);
  let monthTotal = 0, monthDays = 0;
  for (let w = 0; w < weeks; w++) {
    let wt = 0, wn = 0;
    for (let d = 0; d < 7; d++) {
      const dt = new Date(start.getFullYear(), start.getMonth(), start.getDate() + w * 7 + d), k = iso(dt), r = map[k], out = dt.getMonth() !== M - 1;
      if (r && !out) { wt += r.net; wn += r.n; monthTotal += r.net; monthDays++; }
      const a = r ? (.18 + .5 * Math.abs(r.net) / mx).toFixed(2) : 0;
      const bg = r ? `background:color-mix(in srgb, var(${r.net >= 0 ? "--pos" : "--neg"}) ${a * 100}%, var(--surface2))` : "";
      h += `<div class="d ${r ? "has" : ""} ${out ? "out" : ""}" style="${bg}" ${r ? `data-day="${k}" data-tip="${k}\n${fm(r.net)} net · ${r.n} trades\n${r.wins} wins · fees $${num(r.fees)}"` : ""}>
        <span class="dn">${dt.getDate()}</span>${r ? `<span class="dv ${sg(r.net)}">${fm(r.net, 0)}</span><span class="dt">${r.n} trades</span>` : ""}</div>`;
    }
    h += `<div class="wk"><span class="dn">Week ${w + 1}</span><span class="dv ${sg(wt)}">${wn ? fm(wt, 0) : "–"}</span></div>`;
  }
  h += `</div>`;
  const nm = new Date(Y, M - 1, 1).toLocaleString(undefined, { month: "long", year: "numeric" });
  const head = `<div class="calnav"><button class="iconbtn" data-cal="-1">‹</button><b>${nm}</b><button class="iconbtn" data-cal="1">›</button></div>`;
  return { head, body: h, month: monthTotal, days: monthDays };
}

/* ---------- views ---------- */
function kpi(l, v, s, tint) { return `<div class="card kpi c3 ${tint ? "tint-" + tint : ""}"><div class="l">${l}</div><div class="v ${tint || ""}">${v}</div><div class="s">${s}</div></div>`; }
function empty() {
  if (S.st.trades) return `<div class="card empty"><h2>No trades match these filters</h2><p>Try “All time” and clear the contract/side filters.</p></div>`;
  return `<div class="card empty"><h2>No trades yet</h2><p>Drop your Tradovate <b>Fills</b> export on the Import page and everything below fills in.<br>Your data is stored in <b>${esc(S.st.data_dir)}</b>.</p><p><a class="btn primary" href="#/import">Import files</a></p></div>`;
}
function metricRows(M) {
  const R = [["Net P&L", fm(M.net)], ["Gross P&L", fm(M.gross)], ["Fees", "$" + num(M.fees)], ["Trades / contracts", `${M.trades} / ${M.contracts}`],
  ["Win rate", M.win_rate.toFixed(1) + "%"], ["Profit factor", M.pf == null ? "n/a" : M.pf.toFixed(2)], ["Average win", fm(M.avg_win)], ["Average loss", fm(M.avg_loss)],
  ["Avg win / avg loss", M.wl == null ? "n/a" : M.wl.toFixed(2)], ["Expectancy per trade", fm(M.expectancy)], ["Largest win", fm(M.best)], ["Largest loss", fm(M.worst)],
  ["Max drawdown (closed)", `$${num(M.maxdd)} (${fmp(M.dd_peak)} → ${fmp(M.dd_trough)})`], ["Max consecutive W / L", `${M.streak_w} / ${M.streak_l}`],
  ["Avg hold winners / losers", `${dur(M.hold_w)} / ${dur(M.hold_l)}`], ["Green / red days", `${M.green} / ${M.red} (${M.day_wr.toFixed(0)}%)`],
  ["Best / worst day", `${fm(M.best_day)} / ${fm(M.worst_day)}`], ["Avg green / red day", `${fm(M.avg_green)} / ${fm(M.avg_red)}`]];
  if (M.r_count) R.push(["Total R / avg R", `${M.r_total}R / ${M.r_avg}R (${M.r_count} trades with risk set)`]);
  return `<div class="mlist">` + R.map(r => `<div><span>${r[0]}</span><span>${r[1]}</span></div>`).join("") + `</div>`;
}
function insightsList(list, limit) {
  const ic = { leak: "!", strength: "✓", info: "i" };
  return list.slice(0, limit || 99).map(i => `<div class="ins"><div class="dot ${i.kind}">${ic[i.kind]}</div><div><b>${esc(i.title)}</b><p>${esc(i.body)}</p>${i.rule ? `<span class="rule">${esc(i.rule)}</span>` : ""}</div></div>`).join("");
}

function viewDashboard() {
  const A = S.A; if (A.empty) return empty();
  const M = A.metrics, cal = calendarHTML(A.daily);
  const parts = Object.entries(M.score_parts).map(([k, v]) => `<div><span>${k} · ${(M.score_weights[k] * 100).toFixed(0)}%</span><em>${v.toFixed(0)}</em><i style="--w:${v}%"></i></div>`).join("");
  return `<div class="grid">
    ${kpi("Net P&L", fm(M.net), `Gross ${fm(M.gross)} · fees $${num(M.fees)}`, M.net >= 0 ? "pos" : "neg")}
    ${kpi("Win rate", M.win_rate.toFixed(1) + "%", `${M.wins} wins · ${M.losses} losses`)}
    ${kpi("Profit factor", M.pf == null ? "n/a" : M.pf.toFixed(2), `Avg win/loss ${M.wl == null ? "n/a" : M.wl.toFixed(2)}`, M.pf != null && M.pf >= 1 ? "pos" : "neg")}
    ${kpi("Expectancy", fm(M.expectancy), `per trade · ${M.trades} trades in ${M.days} days`, M.expectancy >= 0 ? "pos" : "neg")}
  </div><div class="grid">
    <div class="card c8"><h2>Equity curve <span class="tabs" id="eqtabs"><button data-eq="equity" class="${S.eqTab === "equity" ? "on" : ""}">Equity</button><button data-eq="drawdown" class="${S.eqTab === "drawdown" ? "on" : ""}">Drawdown</button></span></h2>${equityChart(A.equity, S.eqTab)}</div>
    <div class="card c4"><h2>Performance score</h2><div style="display:flex;gap:18px;align-items:center">${ring(M.score)}<div class="parts" style="flex:1">${parts}</div></div>
      <div class="mut" style="font-size:12px;margin-top:10px">Weighted blend of win rate, profit factor, win/loss ratio, drawdown and day-to-day consistency. ${M.days < 10 ? "Fewer than 10 days, so treat it as a rough guide." : ""}</div></div>
  </div><div class="grid">
    <div class="card c7"><h2>P&L calendar <span style="display:flex;gap:12px;align-items:center"><span class="${sg(cal.month)}" style="text-transform:none;letter-spacing:0">${cal.days ? "Month " + fm(cal.month, 0) : ""}</span>${cal.head}</span></h2>${cal.body}</div>
    <div class="card c5"><h2>Result distribution</h2>${histChart(A.hist)}
      <div style="display:flex;align-items:center;gap:14px;margin-top:6px">${donut(M.wins, M.losses)}<div><b>${M.wins} wins / ${M.losses} losses</b><div class="mut">Avg win ${fm(M.avg_win)}<br>Avg loss ${fm(M.avg_loss)}</div></div></div></div>
  </div><div class="grid">
    <div class="card c4"><h2>By entry hour (PT)</h2>${barChart(A.hours, r => String(r.k).padStart(2, "0") + "h", r => `${String(r.k).padStart(2, "0")}:00 PT\n${fm(r.net)} · ${r.trades} trades\nWin rate ${r.wr}%`)}</div>
    <div class="card c4"><h2>By day of week</h2>${barChart(A.dow, r => r.k, r => `${r.k}\n${fm(r.net)} · ${r.trades} trades\nWin rate ${r.wr}%`)}</div>
    <div class="card c4"><h2>Long vs short</h2>${barChart(A.direction, r => r.k, r => `${r.k}\n${fm(r.net)} · ${r.trades} trades\nWin rate ${r.wr}% · PF ${r.pf ?? "n/a"}`)}</div>
  </div><div class="grid">
    <div class="card c6"><h2>By session</h2>${hbars(A.sessions, r => r.k, r => `${r.trades} trades · ${r.wr}% win`)}</div>
    <div class="card c6"><h2>By position size</h2>${hbars(A.size, r => r.k, r => `${r.trades} trades · ${r.wr}% win`)}<h2 style="margin-top:18px">By instrument</h2>${hbars(A.instruments, r => r.k, r => `${r.trades} trades · ${r.qty} contracts`)}</div>
  </div><div class="grid">
    <div class="card c12"><h2>What the data says <a href="#/insights" style="text-transform:none;letter-spacing:0">All insights →</a></h2>${insightsList(A.insights, 5)}</div>
  </div>`;
}

function viewCalendar() {
  const A = S.A; if (A.empty) return empty();
  const cal = calendarHTML(A.daily);
  const wkday = d => new Date(d + "T12:00:00").toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" });
  return `<div class="grid"><div class="card c12"><h2>Trading calendar <span style="display:flex;gap:12px;align-items:center"><span class="${sg(cal.month)}" style="text-transform:none;letter-spacing:0">${cal.days ? "Month " + fm(cal.month) + " · " + cal.days + " days" : ""}</span>${cal.head}</span></h2>${cal.body}</div></div>
  <div class="grid"><div class="card c12"><h2>Days</h2><div class="scroll"><table><thead><tr><th class="l">Date</th><th>Trades</th><th>Wins</th><th>Contracts</th><th>Gross</th><th>Fees</th><th>Net</th><th class="l">Note</th></tr></thead><tbody>
  ${[...A.daily].reverse().map(d => `<tr class="click" data-day="${d.date}"><td>${wkday(d.date)} <span class="mut">${d.date}</span></td><td>${d.n}</td><td>${d.wins}</td><td>${d.qty}</td><td>${fm(d.gross)}</td><td>$${num(d.fees)}</td><td class="${sg(d.net)}"><b>${fm(d.net)}</b></td><td class="l mut">${esc((A.day_notes[d.date]?.notes || "").slice(0, 60))}</td></tr>`).join("")}
  </tbody></table></div></div></div>`;
}

function viewTrades() {
  const A = S.A; if (A.empty) return empty();
  const keyf = { id: t => t._i, date: t => t.trade_date, close: t => t.close, inst: t => t.contract, dir: t => t.dir, qty: t => t.max_q, hold: t => t.hold_s, pts: t => t.points, gross: t => t.gross, fees: t => t.fees, net: t => t.net, r: t => t.r ?? -1e9, setup: t => t.setup };
  let rows = A.trades.map((t, i) => ({ ...t, _i: i + 1 }));
  const q = S.q.trim().toLowerCase();
  if (q) rows = rows.filter(t => [t.setup, t.mistake, t.notes, t.contract, t.dir, t.trade_date].join(" ").toLowerCase().includes(q));
  const [k, d] = S.sort, kf = keyf[k] || keyf.close;
  rows.sort((a, b) => (kf(a) > kf(b) ? 1 : kf(a) < kf(b) ? -1 : 0) * d);
  const th = (key, label, l) => `<th class="sort ${l ? "l" : ""}" data-sort="${key}">${label}${S.sort[0] === key ? (S.sort[1] > 0 ? " ▲" : " ▼") : ""}</th>`;
  return `<div class="card"><h2>${rows.length} trades <span style="display:flex;gap:8px"><input class="field-sm" id="q" placeholder="Search setup, notes…" value="${esc(S.q)}" style="text-transform:none;letter-spacing:0;font-weight:400"><a class="btn sm" href="/api/export/trades.csv?${qs()}">Export CSV</a></span></h2>
  <div class="scroll"><table><thead><tr>${th("id", "#", 1)}${th("close", "Exit (PT)", 1)}${th("inst", "Contract", 1)}${th("dir", "Side", 1)}${th("qty", "Max qty")}${th("hold", "Hold")}${th("pts", "Points")}${th("gross", "Gross")}${th("fees", "Fees")}${th("net", "Net")}${th("r", "R")}${th("setup", "Setup", 1)}</tr></thead><tbody>
  ${rows.map(t => `<tr class="click" data-trade="${t.key}"><td>${t._i}</td><td class="l">${t.close.slice(5, 16).replace("-", "/")}</td><td class="l">${t.contract}</td><td class="l"><span class="chip ${t.dir === "Long" ? "pos" : "neg"}">${t.dir}</span></td><td>${t.max_q}</td><td>${dur(t.hold_s)}</td><td class="${sg(t.points)}">${num(t.points)}</td><td>${fm(t.gross)}</td><td class="mut">$${num(t.fees)}</td><td class="${sg(t.net)}"><b>${fm(t.net)}</b></td><td>${t.r ?? "–"}</td><td class="l">${t.setup ? `<span class="chip">${esc(t.setup)}</span>` : ""}${t.mistake ? ` <span class="chip neg">${esc(t.mistake)}</span>` : ""}${t.notes ? " 📝" : ""}</td></tr>`).join("")}
  </tbody></table></div></div>`;
}

function viewInsights() {
  const A = S.A; if (A.empty) return empty();
  const M = A.metrics, B = A.behavior, rules = A.insights.filter(i => i.rule);
  return `<div class="grid"><div class="card c7"><h2>Strengths &amp; leaks</h2>${insightsList(A.insights)}</div>
    <div class="card c5"><h2>Rules to test next</h2>${rules.length ? rules.map(r => `<div class="ins"><div class="dot info">→</div><div><b>${esc(r.rule)}</b><p>${esc(r.body)}</p></div></div>`).join("") : '<div class="mut">No rules suggested yet. Import more trading days.</div>'}
    <div class="mut" style="font-size:12px;margin-top:10px">Generated from your own numbers. With few trades these are hypotheses; re-check them as data grows.</div></div></div>
  <div class="grid"><div class="card c6"><h2>Behaviour flags</h2><table><tbody>
    <tr><td>Re-entry within 2 min of a loss</td><td>${B.revenge.n} trades</td><td class="${sg(B.revenge.net)}">${fm(B.revenge.net)}</td></tr>
    <tr><td>Bigger size right after a loss</td><td>${B.size_up.n} trades</td><td class="${sg(B.size_up.net)}">${fm(B.size_up.net)}</td></tr>
    <tr><td>Overtrading days (>1.3× avg ${B.avg_trades_per_day.toFixed(0)}/day)</td><td colspan="2">${B.overtrading_days.length ? B.overtrading_days.join(", ") : "None"}</td></tr>
    <tr><td>Losers held much longer than winners</td><td colspan="2">${B.hold_loser_gt_winner ? "Yes" : "No"} (${dur(M.hold_l)} vs ${dur(M.hold_w)})</td></tr></tbody></table></div>
    <div class="card c6"><h2>Your tags</h2><h3 style="font-size:13px;margin-bottom:6px">Setups</h3>${hbars(A.setups, r => r.k, r => `${r.trades} trades`)}<h3 style="font-size:13px;margin:14px 0 6px">Mistakes</h3>${hbars(A.mistakes, r => r.k, r => `${r.trades} trades`)}</div></div>
  <div class="grid"><div class="card c12"><h2>Full metrics</h2>${metricRows(M)}</div></div>`;
}

function viewImport() {
  const st = S.st;
  const recon = S.A.recon;
  return `<div class="grid"><div class="card c12"><div class="drop" id="drop"><div class="big">Drop Tradovate CSV files here</div><p class="mut">or click to choose. Fills (required) and Performance (optional, for cross-checking). Re-importing the same file is safe: duplicates are skipped.</p><input type="file" id="file" accept=".csv,text/csv" multiple hidden></div><div id="results"></div></div></div>
  ${st.open_positions.length ? `<div class="card" style="margin-bottom:16px;border-color:var(--warn)"><b>Open position found:</b> ${st.open_positions.map(p => `${p.direction} ${p.qty} ${p.contract} since ${p.since.slice(0, 16)}`).join(", ")}. It counts as a trade once the closing fills are imported.</div>` : ""}
  <div class="grid"><div class="card c7"><h2>Import history</h2>${st.imports.length ? `<table><thead><tr><th class="l">File</th><th>Type</th><th>Rows</th><th>New</th><th class="l">When</th><th></th></tr></thead><tbody>${st.imports.map(i => `<tr><td class="l">${esc(i.name)}</td><td><span class="chip gray">${i.kind}</span></td><td>${i.rows}</td><td>${i.new_rows}</td><td class="l mut">${i.at}</td><td>${i.new_rows ? `<button class="btn sm danger" data-delimp="${i.id}">Remove</button>` : ""}</td></tr>`).join("")}</tbody></table>` : '<div class="mut">No imports yet.</div>'}</div>
  <div class="card c5"><h2>Cross-check vs Performance report</h2>${recon ? `<table><thead><tr><th class="l">Trade date</th><th>Report</th><th>Rebuilt</th><th>Diff</th></tr></thead><tbody>${recon.rows.map(r => `<tr><td class="l">${r.date}</td><td>${fm(r.perf)}</td><td>${fm(r.mine)}</td><td class="${Math.abs(r.diff) > 1 ? "neg" : "pos"}">${num(r.diff)}</td></tr>`).join("")}</tbody></table><p class="${recon.ok ? "pos" : "neg"}"><b>${recon.ok ? "✓ Matches" : "✗ Differences found"}</b> <span class="mut">(${recon.pairs} report rows${recon.unmatched ? `, ${recon.unmatched} not matched to fills` : ""}; gross P&L, before commissions)</span></p>` : '<div class="mut">Import a Performance CSV to cross-check your gross P&L day by day.</div>'}</div></div>`;
}

function viewSettings() {
  const st = S.st, pv = st.point_values;
  const sel = (id, opts, cur) => `<select id="${id}" class="field">${opts.map(o => `<option value="${o[0]}" ${o[0] === cur ? "selected" : ""}>${o[1]}</option>`).join("")}</select>`;
  return `<div class="grid"><div class="card c6"><h2>Appearance</h2><label class="mut">Theme</label>${sel("theme", [["auto", "Match system"], ["light", "Light"], ["dark", "Dark"]], pref.get("theme", "auto"))}
    <label class="mut" style="display:block;margin-top:12px">Profit / loss colours</label>${sel("colors", [["gr", "Green / red"], ["bo", "Blue / orange (colour-blind friendly)"]], pref.get("colors", "gr"))}</div>
  <div class="card c6"><h2>Where your data lives</h2><p><b>${esc(st.data_dir)}</b></p><ul class="mut" style="padding-left:18px;margin:0"><li><code>journal.db</code> your journal (fills, notes, settings)</li><li><code>trade_log.csv</code> refreshed after every change</li><li><code>backups/</code> automatic copy after each import (last 20 kept)</li></ul>
    <p class="mut">To use another folder start the app with <code>--data /path/to/folder</code>.</p></div></div>
  <div class="grid"><div class="card c6"><h2>Point values ($ per point)</h2><div id="pv">${Object.entries(pv).map(([k, v]) => `<div class="row2" style="margin-bottom:6px"><input class="field" value="${esc(k)}" data-k><input class="field" type="number" step="any" value="${v}" data-v></div>`).join("")}</div>
    <div style="display:flex;gap:8px;margin-top:8px"><button class="btn sm" id="addpv">+ Add contract</button><button class="btn primary sm" id="savepv">Save</button></div></div>
  <div class="card c6"><h2>Backup &amp; export</h2><div style="display:flex;gap:8px;flex-wrap:wrap"><a class="btn" href="/api/backup">Download full backup (.json)</a><a class="btn" href="/api/export/trades.csv">Export trade log (.csv)</a><button class="btn" id="restore">Restore backup…</button><input type="file" id="rfile" accept=".json" hidden></div>
    <h2 style="margin-top:26px">Danger zone</h2><p class="mut">Deletes all fills, notes and imports (a safety copy goes to <code>backups/</code> first).</p><button class="btn danger" id="reset">Erase all data…</button></div></div>`;
}

/* ---------- drawers ---------- */
function openDrawer(html) { $("#drawer").innerHTML = html; $("#drawer").classList.add("on"); $("#scrim").classList.add("on"); }
function closeDrawer() { $("#drawer").classList.remove("on"); $("#scrim").classList.remove("on"); }
$("#scrim").onclick = closeDrawer;
document.addEventListener("keydown", e => { if (e.key === "Escape") closeDrawer(); });

async function openTrade(key) {
  const list = S.A.trades, i = list.findIndex(t => t.key === key), t = list[i];
  if (!t) return;
  const fills = await api(`/api/trade/${key}/fills`);
  const used = f => [...new Set(list.map(x => x[f]).filter(Boolean))].map(v => `<option value="${esc(v)}">`).join("");
  openDrawer(`<header><div><h2 style="font-size:19px">${t.dir} ${t.contract} <span class="${sg(t.net)}">${fm(t.net)}</span></h2><div class="mut">${t.open.slice(0, 16)} → ${t.close.slice(11, 16)} PT · ${dur(t.hold_s)} · trade date ${t.trade_date}</div></div>
    <div style="display:flex;gap:6px"><button class="iconbtn" id="prv" ${i < 1 ? "disabled" : ""}>↑</button><button class="iconbtn" id="nxt" ${i >= list.length - 1 ? "disabled" : ""}>↓</button><button class="iconbtn" id="cls">✕</button></div></header>
  <div class="body"><div class="stat3"><div><small>Max size</small><b>${t.max_q}</b></div><div><small>Avg entry → exit</small><b>${num(t.avg_in)} → ${num(t.avg_out)}</b></div><div><small>Points</small><b class="${sg(t.points)}">${num(t.points)}</b></div>
    <div><small>Gross</small><b>${fm(t.gross)}</b></div><div><small>Fees</small><b>$${num(t.fees)}</b></div><div><small>R multiple</small><b id="rv">${t.r ?? "–"}</b></div></div>
  <label>Setup</label><input class="field" id="f-setup" list="dl-setup" value="${esc(t.setup)}" placeholder="e.g. Opening range break"><datalist id="dl-setup">${used("setup")}</datalist>
  <label>Mistake (if any)</label><input class="field" id="f-mistake" list="dl-mistake" value="${esc(t.mistake)}" placeholder="e.g. Chased entry, Oversized, Revenge"><datalist id="dl-mistake">${used("mistake")}</datalist>
  <div class="row2"><div><label>Planned risk ($)</label><input class="field" id="f-risk" type="number" step="any" value="${t.risk ?? ""}" placeholder="stop distance × size"></div>
  <div><label>Execution rating</label><div class="stars" id="stars">${[1, 2, 3, 4, 5].map(n => `<button data-s="${n}" class="${n <= t.rating ? "on" : ""}">★</button>`).join("")}</div></div></div>
  <label>Notes</label><textarea class="field" id="f-notes" placeholder="Why did you take it? What did you see? What would you change?">${esc(t.notes)}</textarea>
  <div style="margin-top:14px"><button class="btn primary" id="save">Save</button></div>
  <label style="margin-top:26px">Fills</label><table><thead><tr><th class="l">Time (PT)</th><th class="l">Side</th><th>Qty</th><th>Price</th><th>Comm.</th></tr></thead><tbody>${fills.map(f => `<tr><td class="l">${f.pt.slice(0, 19)}</td><td class="l ${f.side === "Buy" ? "pos" : "neg"}">${f.side}</td><td>${f.qty}</td><td>${num(f.price)}</td><td>$${num(f.commission)}</td></tr>`).join("")}</tbody></table></div>`);
  let rating = t.rating;
  $("#cls").onclick = closeDrawer;
  $("#prv").onclick = () => openTrade(list[i - 1].key); $("#nxt").onclick = () => openTrade(list[i + 1].key);
  $("#stars").onclick = e => { const b = e.target.closest("button"); if (!b) return; rating = rating === +b.dataset.s ? 0 : +b.dataset.s; [...$("#stars").children].forEach((c, n) => c.classList.toggle("on", n < rating)); };
  $("#f-risk").oninput = e => { const r = parseFloat(e.target.value); $("#rv").textContent = r > 0 ? (t.net / r).toFixed(2) : "–"; };
  $("#save").onclick = async () => {
    await api("/api/trade/" + key, { setup: $("#f-setup").value, mistake: $("#f-mistake").value, risk: $("#f-risk").value, notes: $("#f-notes").value, rating });
    toast("Saved"); await load(); render(); openTrade(key);
  };
}
async function openDay(date) {
  const A = S.A, d = A.daily.find(x => x.date === date), note = A.day_notes[date] || { notes: "", mood: 0 }, ts = A.trades.filter(t => t.trade_date === date);
  openDrawer(`<header><div><h2 style="font-size:19px">${new Date(date + "T12:00:00").toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric" })}</h2><div class="mut"><span class="${sg(d.net)}"><b>${fm(d.net)}</b></span> · ${d.n} trades · ${d.wins} wins · fees $${num(d.fees)}</div></div><button class="iconbtn" id="cls">✕</button></header>
  <div class="body"><label style="margin-top:0">How did the day go?</label><div class="stars" id="stars">${[1, 2, 3, 4, 5].map(n => `<button data-s="${n}" class="${n <= note.mood ? "on" : ""}">★</button>`).join("")}</div>
  <label>Daily journal</label><textarea class="field" id="f-notes" placeholder="Plan, mindset, what worked, what to fix tomorrow…">${esc(note.notes)}</textarea><div style="margin-top:12px"><button class="btn primary" id="save">Save</button></div>
  <label style="margin-top:26px">Trades</label><table><tbody>${ts.map(t => `<tr class="click" data-trade="${t.key}"><td class="l">${t.open.slice(11, 16)}</td><td class="l">${t.dir} ${t.contract}</td><td>${t.max_q}</td><td class="${sg(t.net)}"><b>${fm(t.net)}</b></td></tr>`).join("")}</tbody></table></div>`);
  let mood = note.mood;
  $("#cls").onclick = closeDrawer;
  $("#stars").onclick = e => { const b = e.target.closest("button"); if (!b) return; mood = mood === +b.dataset.s ? 0 : +b.dataset.s; [...$("#stars").children].forEach((c, n) => c.classList.toggle("on", n < mood)); };
  $("#save").onclick = async () => { await api("/api/day/" + date, { notes: $("#f-notes").value, mood }); toast("Saved"); await load(); render(); };
}

/* ---------- import handling ---------- */
async function importFiles(files) {
  const box = $("#results"); box.innerHTML = "";
  for (const f of files) {
    const row = document.createElement("div"); row.className = "res"; row.textContent = `Importing ${f.name}…`; box.appendChild(row);
    try {
      const res = await api("/api/import", { name: f.name, text: await f.text() });
      row.innerHTML = `<span class="chip pos">✓</span><div><b>${esc(f.name)}</b> <span class="chip gray">${res.kind}</span><div class="mut">${res.kind === "orders" ? "" : `${res.new} new rows added · ${res.duplicates} already in the journal${res.skipped ? " · " + res.skipped + " skipped (unreadable)" : ""}`}</div>${res.warnings.map(w => `<div style="color:var(--warn)">${esc(w)}</div>`).join("")}</div>`;
    } catch (e) { row.classList.add("err"); row.innerHTML = `<span class="chip neg">✗</span><div><b>${esc(f.name)}</b><div class="neg">${esc(e.message)}</div></div>`; }
  }
  await load(); S.cal = null; setTimeout(() => { if (location.hash.includes("import")) { const r = box.innerHTML; render(); $("#results").innerHTML = r; } }, 0);
}

/* ---------- shell ---------- */
function renderNav() {
  const cur = (location.hash.replace("#/", "") || "dashboard");
  $("#nav").innerHTML = ROUTES.map(([id, name, ic]) => `<a href="#/${id}" class="${cur === id ? "on" : ""}"><svg viewBox="0 0 24 24">${ICON[ic]}</svg>${name}</a>`).join("");
}
function renderFilters(route) {
  const f = S.f, show = ["dashboard", "trades", "calendar", "insights"].includes(route) && S.st.trades;
  $("#filters").innerHTML = !show ? "" : `<select id="preset"><option value="all">All time</option><option value="last">Latest day</option><option value="7">Last 7 days</option><option value="30">Last 30 days</option><option value="month">This month</option><option value="custom">Custom…</option></select>
    ${f.preset === "custom" ? `<input type="date" id="from" value="${f.from}"><input type="date" id="to" value="${f.to}">` : ""}
    <select id="inst"><option value="">All contracts</option>${S.st.instruments.map(i => `<option ${f.inst === i ? "selected" : ""}>${i}</option>`).join("")}</select>
    <select id="dirsel"><option value="">Long &amp; short</option><option ${f.dir === "Long" ? "selected" : ""}>Long</option><option ${f.dir === "Short" ? "selected" : ""}>Short</option></select>`;
  if (show) $("#preset").value = f.preset;
}
function render() {
  const route = location.hash.replace("#/", "") || "dashboard";
  renderNav(); renderFilters(route);
  const t = { dashboard: ["Dashboard", viewDashboard], trades: ["Trades", viewTrades], calendar: ["Calendar", viewCalendar], insights: ["Insights", viewInsights], import: ["Import", viewImport], settings: ["Settings", viewSettings] }[route] || ["Dashboard", viewDashboard];
  $("#title").textContent = t[0];
  const A = S.A, st = S.st;
  $("#sub").textContent = st.trades ? `${A.empty ? 0 : A.metrics.trades} trades · ${st.first} to ${st.last} · ${st.fills} fills stored` : "Your personal trading journal";
  $("#view").innerHTML = t[1]();
  wire(route);
}
function wire(route) {
  const v = $("#view");
  v.onclick = async e => {
    const c = e.target.closest("[data-cal]"); if (c) { const [Y, M] = S.cal.split("-").map(Number), d = new Date(Y, M - 1 + +c.dataset.cal, 1); S.cal = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`; return render(); }
    const eq = e.target.closest("[data-eq]"); if (eq) { S.eqTab = eq.dataset.eq; return render(); }
    const day = e.target.closest("[data-day]"); if (day) return openDay(day.dataset.day);
    const tr = e.target.closest("[data-trade]"); if (tr) return openTrade(tr.dataset.trade);
    const so = e.target.closest("[data-sort]"); if (so) { const k = so.dataset.sort; S.sort = [k, S.sort[0] === k ? -S.sort[1] : -1]; return render(); }
    const di = e.target.closest("[data-delimp]"); if (di && confirm("Remove the rows this file added? Notes you wrote are kept.")) { await api("/api/import/delete", { id: +di.dataset.delimp }); toast("Removed"); return reload(); }
  };
  $("#drawer").onclick = e => { const tr = e.target.closest("[data-trade]"); if (tr) openTrade(tr.dataset.trade); };
  if (route === "trades") { const q = $("#q"); if (q) q.oninput = () => { S.q = q.value; const p = q.selectionStart; render(); const n = $("#q"); n.focus(); n.setSelectionRange(p, p); }; }
  if (route === "import") {
    const d = $("#drop"), fi = $("#file");
    d.onclick = () => fi.click(); fi.onchange = () => importFiles(fi.files);
    d.ondragover = e => { e.preventDefault(); d.classList.add("over"); }; d.ondragleave = () => d.classList.remove("over");
    d.ondrop = e => { e.preventDefault(); d.classList.remove("over"); importFiles(e.dataTransfer.files); };
  }
  if (route === "settings") {
    $("#theme").onchange = e => { pref.set("theme", e.target.value); applyTheme(); };
    $("#colors").onchange = e => { pref.set("colors", e.target.value); applyTheme(); };
    $("#addpv").onclick = () => $("#pv").insertAdjacentHTML("beforeend", `<div class="row2" style="margin-bottom:6px"><input class="field" placeholder="Symbol e.g. MGC" data-k><input class="field" type="number" step="any" placeholder="$ per point" data-v></div>`);
    $("#savepv").onclick = async () => {
      const o = {}; [...$("#pv").children].forEach(r => { const k = r.querySelector("[data-k]").value.trim(), val = r.querySelector("[data-v]").value; if (k && val !== "") o[k] = +val; });
      await api("/api/settings", { point_values: o }); toast("Saved. Trades recalculated"); reload();
    };
    $("#restore").onclick = () => $("#rfile").click();
    $("#rfile").onchange = async e => { if (!e.target.files[0] || !confirm("Replace everything with this backup?")) return; await api("/api/restore", JSON.parse(await e.target.files[0].text())); toast("Backup restored"); reload(); };
    $("#reset").onclick = async () => { if (prompt("This erases all journal data. Type DELETE to confirm.") === "DELETE") { await api("/api/reset", { confirm: "DELETE" }); toast("All data erased"); reload(); } };
  }
}
$("#filters").addEventListener("change", e => {
  const f = S.f, id = e.target.id;
  if (id === "preset") f.preset = e.target.value; if (id === "from") f.from = e.target.value; if (id === "to") f.to = e.target.value;
  if (id === "inst") f.inst = e.target.value; if (id === "dirsel") f.dir = e.target.value;
  S.cal = null; reload();
});
addEventListener("hashchange", () => { closeDrawer(); render(); });

(async function init() {
  applyTheme();
  try { await load(); } catch (e) { $("#view").innerHTML = `<div class="card empty"><h2>Can't reach the Edgebook server</h2><p>${esc(e.message)}</p></div>`; return; }
  if (!location.hash) location.hash = S.st.trades ? "#/dashboard" : "#/import"; else render();
})();
