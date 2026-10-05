"""Edgebook engine: CSV parsing, SQLite storage, FIFO trade rebuild and analytics.

Standard library only. All times shown to the user are America/Los_Angeles.
"""
import collections
import csv
import io
import json
import re
import sqlite3
import statistics
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

PT = ZoneInfo("America/Los_Angeles")

DEFAULT_POINT_VALUES = {
    "ES": 50, "MES": 5, "NQ": 20, "MNQ": 2, "YM": 5, "MYM": 0.5, "RTY": 50,
    "M2K": 5, "CL": 1000, "MCL": 100, "GC": 100, "MGC": 10,
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS imports(
  id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, kind TEXT, rows INTEGER, new_rows INTEGER, at TEXT);
CREATE TABLE IF NOT EXISTS fills(
  fill_id INTEGER PRIMARY KEY, order_id INTEGER, account TEXT, contract TEXT, product TEXT,
  side TEXT, qty INTEGER, price REAL, commission REAL, utc TEXT, pt TEXT, trade_date TEXT, import_id INTEGER);
CREATE TABLE IF NOT EXISTS perf_pairs(
  id INTEGER PRIMARY KEY AUTOINCREMENT, buy_fill INTEGER, sell_fill INTEGER, qty INTEGER, pnl REAL,
  import_id INTEGER, UNIQUE(buy_fill, sell_fill, qty, pnl));
CREATE TABLE IF NOT EXISTS trade_notes(
  key TEXT PRIMARY KEY, setup TEXT DEFAULT '', mistake TEXT DEFAULT '', risk REAL, notes TEXT DEFAULT '',
  rating INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS day_notes(date TEXT PRIMARY KEY, notes TEXT DEFAULT '', mood INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
"""


def connect(path):
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.executescript(SCHEMA)
    return db


# ---------------------------------------------------------------- settings
def get_point_values(db):
    pv = dict(DEFAULT_POINT_VALUES)
    row = db.execute("SELECT value FROM settings WHERE key='point_values'").fetchone()
    if row:
        pv.update({k: float(v) for k, v in json.loads(row["value"]).items()})
    return pv


# ---------------------------------------------------------------- import
def _rows(text):
    text = text.lstrip("﻿")
    rdr = csv.DictReader(io.StringIO(text))
    out = []
    for r in rdr:
        out.append({(k or "").strip(): (v or "").strip() for k, v in r.items()})
    return rdr.fieldnames or [], out


def detect_kind(headers):
    h = {x.strip() for x in headers}
    if {"Fill ID", "commission", "Price"} <= h:
        return "fills"
    if "buyFillId" in h and "sellFillId" in h:
        return "performance"
    if "orderId" in h and "Status" in h:
        return "orders"
    return None


def _num(s):
    return float(s.replace(",", "").replace("$", "").replace("(", "-").replace(")", ""))


def import_text(db, name, text, pv):
    headers, rows = _rows(text)
    kind = detect_kind(headers)
    if kind is None:
        raise ValueError(
            "Unrecognised file. Expected a Tradovate Fills export (needs Fill ID, Price, commission), "
            "a Performance export (buyFillId/sellFillId) or an Orders export.")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cur = db.execute("INSERT INTO imports(name,kind,rows,new_rows,at) VALUES(?,?,?,0,?)", (name, kind, len(rows), now))
    imp = cur.lastrowid
    new, skipped, warnings = 0, 0, []
    if kind == "fills":
        unknown = set()
        for r in rows:
            try:
                fid = int(r["Fill ID"]); qty = int(float(r["Quantity"])); price = float(r["Price"])
                side = r["B/S"].strip().capitalize()
                if side not in ("Buy", "Sell") or qty <= 0:
                    raise ValueError("bad side/qty")
                utc = datetime.fromisoformat(r["_timestamp"].replace("Z", "")).replace(tzinfo=timezone.utc)
            except (KeyError, ValueError):
                skipped += 1
                continue
            product = r.get("Product", "") or re.sub(r"[FGHJKMNQUVXZ]\d+$", "", r["Contract"])
            if product not in pv:
                unknown.add(product)
            pt = utc.astimezone(PT)
            c = db.execute(
                "INSERT OR IGNORE INTO fills VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (fid, int(r.get("Order ID") or 0), r.get("Account", ""), r["Contract"], product, side, qty, price,
                 _num(r.get("commission") or "0"), utc.strftime("%Y-%m-%d %H:%M:%S.%f"),
                 pt.strftime("%Y-%m-%d %H:%M:%S.%f"), r.get("_tradeDate") or pt.strftime("%Y-%m-%d"), imp))
            new += c.rowcount
        if unknown:
            warnings.append("No point value for: %s. Add it in Settings, otherwise P&L for those is wrong." % ", ".join(sorted(unknown)))
    elif kind == "performance":
        for r in rows:
            try:
                c = db.execute(
                    "INSERT OR IGNORE INTO perf_pairs(buy_fill,sell_fill,qty,pnl,import_id) VALUES(?,?,?,?,?)",
                    (int(r["buyFillId"]), int(r["sellFillId"]), int(float(r["qty"])), _num(r["pnl"]), imp))
                new += c.rowcount
            except (KeyError, ValueError):
                skipped += 1
    else:
        warnings.append("Orders files are not needed: the Fills file already has every execution with exact "
                        "prices, times and commissions. Nothing was stored.")
    db.execute("UPDATE imports SET new_rows=? WHERE id=?", (new, imp))
    db.commit()
    return dict(kind=kind, rows=len(rows), new=new, duplicates=len(rows) - new - skipped if kind != "orders" else 0,
                skipped=skipped, warnings=warnings, import_id=imp)


# ---------------------------------------------------------------- trades
def build_trades(db, pv):
    fills = [dict(r) for r in db.execute("SELECT * FROM fills ORDER BY utc, fill_id")]
    groups = collections.defaultdict(list)
    for f in fills:
        groups[(f["account"], f["contract"])].append(f)
    trades, open_pos = [], []
    for (acct, contract), fs in groups.items():
        product = fs[0]["product"]
        mult = pv.get(product, 0)
        lots = collections.deque()
        pos, cur = 0, None
        for f in fs:
            sgn = 1 if f["side"] == "Buy" else -1
            q, px = f["qty"], f["price"]
            cpc = f["commission"] / f["qty"]
            while q > 0:
                if cur is None:
                    cur = dict(key=str(f["fill_id"]), contract=contract, product=product, account=acct,
                               dir="Long" if sgn > 0 else "Short", open=f["pt"], open_utc=f["utc"],
                               open_date=f["trade_date"], fills=[], max_q=0, ein=0.0, eq=0, xout=0.0, xq=0,
                               gross=0.0, fees=0.0)
                d = 1 if cur["dir"] == "Long" else -1
                if sgn == d:
                    lots.append([px, q]); pos += q
                    cur["ein"] += px * q; cur["eq"] += q; cur["fees"] += cpc * q
                    cur["max_q"] = max(cur["max_q"], pos)
                    if f["fill_id"] not in cur["fills"]: cur["fills"].append(f["fill_id"])
                    q = 0
                else:
                    take = min(q, lots[0][1]); epx = lots[0][0]
                    cur["gross"] += (px - epx) * take * d * mult
                    cur["xout"] += px * take; cur["xq"] += take; cur["fees"] += cpc * take
                    if f["fill_id"] not in cur["fills"]: cur["fills"].append(f["fill_id"])
                    lots[0][1] -= take; q -= take; pos -= take
                    if lots[0][1] == 0: lots.popleft()
                    if pos == 0:
                        cur.update(close=f["pt"], close_utc=f["utc"], trade_date=f["trade_date"])
                        trades.append(cur); cur = None
        if cur is not None:
            open_pos.append(dict(contract=contract, direction=cur["dir"], qty=pos, since=cur["open"]))
    out = []
    for t in sorted(trades, key=lambda t: (t["close_utc"], t["key"])):
        o = datetime.fromisoformat(t["open_utc"]); c = datetime.fromisoformat(t["close_utc"])
        t["hold_s"] = (c - o).total_seconds()
        t["avg_in"] = t.pop("ein") / t["eq"]; t["avg_out"] = t.pop("xout") / t.pop("xq")
        t["points"] = (t["avg_out"] - t["avg_in"]) * (1 if t["dir"] == "Long" else -1)
        t["net"] = t["gross"] - t["fees"]
        t["qty"] = t.pop("eq")
        out.append(t)
    return out, open_pos


def merge_notes(db, trades):
    notes = {r["key"]: dict(r) for r in db.execute("SELECT * FROM trade_notes")}
    for t in trades:
        n = notes.get(t["key"], {})
        t["setup"] = n.get("setup", ""); t["mistake"] = n.get("mistake", "")
        t["risk"] = n.get("risk"); t["notes"] = n.get("notes", ""); t["rating"] = n.get("rating", 0)
        t["r"] = round(t["net"] / t["risk"], 2) if t["risk"] else None
    return trades


# ---------------------------------------------------------------- analytics
def _session(pt):
    m = int(pt[11:13]) * 60 + int(pt[14:16])
    if m < 390: return "Pre-market (before 6:30)"
    if m < 450: return "First hour RTH (6:30-7:30)"
    if m < 720: return "Midday (7:30-12:00)"
    if m < 780: return "Last hour RTH (12:00-13:00)"
    return "After hours (13:00+)"


def _group(trades, keyf, order=None):
    g = collections.OrderedDict()
    for t in trades:
        g.setdefault(keyf(t), []).append(t)
    rows = []
    for k, ts in g.items():
        wins = [t["net"] for t in ts if t["net"] > 0]; loss = [-t["net"] for t in ts if t["net"] < 0]
        rows.append(dict(k=k, trades=len(ts), net=round(sum(t["net"] for t in ts), 2),
                         wins=len(wins), wr=round(100 * len(wins) / len(ts), 1),
                         pf=round(sum(wins) / sum(loss), 2) if loss else None,
                         avg=round(sum(t["net"] for t in ts) / len(ts), 2), qty=sum(t["qty"] for t in ts)))
    if order: rows.sort(key=lambda r: order(r["k"]))
    return rows


def _streak(flags):
    best = cur = 0
    for x in flags:
        cur = cur + 1 if x else 0
        best = max(best, cur)
    return best


def analyze(trades):
    n = len(trades)
    if n == 0:
        return dict(empty=True)
    trades = sorted(trades, key=lambda t: (t["close_utc"], t["key"]))
    nets = [t["net"] for t in trades]
    wins = [x for x in nets if x > 0]; losses = [x for x in nets if x < 0]
    gw = sum(x for x in nets if x > 0)
    gl = -sum(x for x in nets if x < 0)
    cum, eq, peak, maxdd, dd_pk, dd_tr = 0.0, [], 0.0, 0.0, 0.0, 0.0
    for t in trades:
        cum += t["net"]; t["cum"] = round(cum, 2); eq.append(cum)
        peak = max(peak, cum)
        if peak - cum > maxdd: maxdd, dd_pk, dd_tr = peak - cum, peak, cum
    days = collections.OrderedDict()
    for t in trades:
        d = days.setdefault(t["trade_date"], dict(date=t["trade_date"], net=0.0, gross=0.0, fees=0.0, n=0, wins=0, qty=0))
        d["net"] += t["net"]; d["gross"] += t["gross"]; d["fees"] += t["fees"]; d["n"] += 1; d["qty"] += t["qty"]
        d["wins"] += t["net"] > 0
    days = [dict(d, net=round(d["net"], 2), gross=round(d["gross"], 2), fees=round(d["fees"], 2)) for d in days.values()]
    dn = [d["net"] for d in days]
    green = [x for x in dn if x > 0]; red = [x for x in dn if x < 0]
    hold = lambda ts: statistics.mean(t["hold_s"] for t in ts) if ts else 0
    avg_win = statistics.mean(wins) if wins else 0
    avg_loss = statistics.mean(losses) if losses else 0
    pf = (gw / gl) if gl else None
    wl = (avg_win / -avg_loss) if avg_loss else None
    wr = 100 * len(wins) / n
    # Zella-style score
    comp = {}
    comp["Win rate"] = min(100, wr / 60 * 100)
    comp["Profit factor"] = min(100, (pf or 3) / 2 * 100)
    comp["Avg win / loss"] = min(100, (wl or 3) / 2 * 100)
    comp["Drawdown"] = 100 * (1 - min(1, maxdd / gw)) if gw else 0
    # Consistency: 60% share of green days (70% green = full marks) + 40% evenness of daily P&L
    # (coefficient of variation; 0 = perfectly even, 2+ = erratic).
    dwr = 100 * len(green) / len(days)
    cv = statistics.stdev(dn) / abs(statistics.mean(dn)) if len(dn) > 1 and statistics.mean(dn) != 0 else 2
    comp["Consistency"] = 0.6 * min(100, dwr / 70 * 100) + 0.4 * 100 * (1 - min(1, cv / 2))
    weights = {"Win rate": .15, "Profit factor": .25, "Avg win / loss": .20, "Drawdown": .20, "Consistency": .20}
    score = sum(comp[k] * weights[k] for k in comp)
    M = dict(trades=n, net=sum(nets), gross=sum(t["gross"] for t in trades), fees=sum(t["fees"] for t in trades),
             wins=len(wins), losses=len(losses), win_rate=wr, pf=pf, avg_win=avg_win, avg_loss=avg_loss, wl=wl,
             expectancy=sum(nets) / n, best=max(nets), worst=min(nets), maxdd=maxdd, dd_peak=dd_pk, dd_trough=dd_tr,
             streak_w=_streak([x > 0 for x in nets]), streak_l=_streak([x < 0 for x in nets]),
             hold_w=hold([t for t in trades if t["net"] > 0]), hold_l=hold([t for t in trades if t["net"] < 0]),
             days=len(days), green=len(green), red=len(red), day_wr=100 * len(green) / len(days),
             best_day=max(dn), worst_day=min(dn),
             avg_green=statistics.mean(green) if green else 0, avg_red=statistics.mean(red) if red else 0,
             contracts=sum(t["qty"] for t in trades), score=score, score_parts=comp,
             score_weights=weights)
    # R multiples
    rt = [t for t in trades if t.get("r") is not None]
    if rt:
        M["r_count"] = len(rt); M["r_total"] = round(sum(t["r"] for t in rt), 2)
        M["r_avg"] = round(statistics.mean(t["r"] for t in rt), 2)
    # behaviour flags
    prev = None
    for t in trades:
        t["revenge"] = bool(prev and prev["net"] < 0 and 0 <= (datetime.fromisoformat(t["open_utc"]) - datetime.fromisoformat(prev["close_utc"])).total_seconds() <= 120)
        t["size_up"] = bool(prev and prev["net"] < 0 and t["max_q"] > prev["max_q"])
        prev = t
    byday = collections.defaultdict(int)
    for t in trades: byday[t["trade_date"]] += 1
    avg_n = statistics.mean(byday.values())
    over = sorted(d for d, c in byday.items() if c > 1.3 * avg_n and len(byday) > 1)
    behavior = dict(
        revenge=_summ([t for t in trades if t["revenge"]]), size_up=_summ([t for t in trades if t["size_up"]]),
        overtrading_days=over, avg_trades_per_day=avg_n,
        hold_loser_gt_winner=M["hold_l"] > 1.5 * M["hold_w"] if M["hold_w"] else False)
    hours = _group(trades, lambda t: int(t["open"][11:13]), lambda k: k)
    dow = _group(trades, lambda t: datetime.strptime(t["trade_date"], "%Y-%m-%d").strftime("%a"),
                 lambda k: ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].index(k))
    sessions = _group(trades, lambda t: _session(t["open"]),
                      lambda k: ["Pre-market (before 6:30)", "First hour RTH (6:30-7:30)", "Midday (7:30-12:00)",
                                 "Last hour RTH (12:00-13:00)", "After hours (13:00+)"].index(k))
    out = dict(empty=False, metrics=M, equity=[dict(i=i + 1, key=t["key"], cum=t["cum"], net=round(t["net"], 2), date=t["trade_date"]) for i, t in enumerate(trades)],
               daily=days, hours=hours, dow=dow, sessions=sessions,
               direction=_group(trades, lambda t: t["dir"]), instruments=_group(trades, lambda t: t["contract"]),
               setups=_group([t for t in trades if t["setup"]], lambda t: t["setup"]),
               mistakes=_group([t for t in trades if t["mistake"]], lambda t: t["mistake"]),
               size=_group(trades, lambda t: "1-2 lots" if t["max_q"] <= 2 else "3-5 lots" if t["max_q"] <= 5 else "6+ lots",
                           lambda k: ["1-2 lots", "3-5 lots", "6+ lots"].index(k)),
               behavior=behavior, hist=_hist(nets))
    out["insights"] = insights(trades, M, out)
    return out


def _summ(ts):
    return dict(n=len(ts), net=round(sum(t["net"] for t in ts), 2), wins=sum(t["net"] > 0 for t in ts))


def _hist(nets):
    lo, hi = min(nets), max(nets)
    span = max(hi - lo, 1)
    step = next(s for s in (5, 10, 20, 25, 40, 50, 100, 200, 250, 500, 1000, 2500, 5000, 10000, 50000) if span / s <= 14)
    start = int(lo // step) * step
    bins = collections.Counter(int((x - start) // step) for x in nets)
    return [dict(lo=start + i * step, hi=start + (i + 1) * step, n=bins.get(i, 0)) for i in range(int((hi - start) // step) + 1)]


def _after(trades, pred):
    sel = [t for p, t in zip([None] + trades[:-1], trades) if pred(p, t)]
    return len(sel), round(sum(t["net"] for t in sel), 2)


def insights(trades, M, A):
    I = []
    money = lambda v: ("-$" if v < 0 else "+$") + format(abs(v), ",.2f")
    I.append(dict(kind="info", title="Costs vs edge",
                  body="Gross %s, fees $%s, net %s." % (money(M["gross"]), format(M["fees"], ",.2f"), money(M["net"])) +
                       (" Fees turned a gross profit into a net loss." if M["gross"] > 0 > M["net"] else
                        " Fees are %.0f%% of gross profit." % (100 * M["fees"] / M["gross"]) if M["gross"] > 0 else "")))
    # time cutoff
    hrs = sorted({int(t["open"][11:13]) for t in trades})
    best = None
    for h in hrs:
        late = [t for t in trades if int(t["open"][11:13]) >= h]
        early = [t for t in trades if int(t["open"][11:13]) < h]
        if len(late) >= 5 and early:
            v = sum(t["net"] for t in late); ev = sum(t["net"] for t in early)
            if v < 0 and (best is None or ev - v > best[4] - best[1]):
                best = (h, v, len(late), sum(t["net"] > 0 for t in late), ev, len(early))
    if best:
        h, v, c, w, ev, ec = best
        I.append(dict(kind="leak", title="Late entries drain you",
                      body="Entries at or after %02d:00 PT: %d trades, %d wins, %s. Earlier entries: %d trades, %s." % (h, c, w, money(v), ec, money(ev)),
                      rule="Test: no new entries after %02d:00 PT for a week." % h))
    # consecutive losses
    for k in (3, 2):
        ls = 0; cnt = 0; tot = 0.0
        for t in trades:
            if ls >= k: cnt += 1; tot += t["net"]
            ls = ls + 1 if t["net"] < 0 else 0
        if cnt >= 5 and tot < 0:
            I.append(dict(kind="leak", title="Trading through losing streaks",
                          body="After %d consecutive losses you took %d more trades: %s." % (k, cnt, money(tot)),
                          rule="Test: after %d losses in a row, stop for 30 minutes or for the day." % k))
            break
    # daily loss limit
    avg_loss = -M["avg_loss"] if M["avg_loss"] else 0
    if avg_loss:
        lim = max(50, round(3 * avg_loss / 50) * 50)
        cnt = 0; tot = 0.0; day = None; cum = 0.0
        for t in trades:
            if t["trade_date"] != day: day, cum = t["trade_date"], 0.0
            if cum <= -lim: cnt += 1; tot += t["net"]
            cum += t["net"]
        if cnt >= 3 and tot < 0:
            I.append(dict(kind="leak", title="Trading past a daily loss of $%d" % lim,
                          body="%d trades were taken after the day was already down $%d or more: %s." % (cnt, lim, money(tot)),
                          rule="Test: hard daily stop at -$%d." % lim))
    # direction
    d = {r["k"]: r for r in A["direction"]}
    if len(d) == 2:
        a, b = sorted(d.values(), key=lambda r: r["net"])
        if a["net"] < 0 < b["net"] and a["trades"] >= 5:
            I.append(dict(kind="leak", title="%s side loses money" % a["k"],
                          body="%s: %d trades, %s (PF %s). %s: %d trades, %s." % (a["k"], a["trades"], money(a["net"]), a["pf"] or "n/a", b["k"], b["trades"], money(b["net"])),
                          rule="Test: halve %s size for a week." % a["k"].lower()))
            I.append(dict(kind="strength", title="%s side works" % b["k"], body="%d trades, %s, win rate %.0f%%." % (b["trades"], money(b["net"]), b["wr"])))
    # best day
    bd = max(A["daily"], key=lambda x: x["net"])
    if bd["net"] > 0:
        I.append(dict(kind="strength", title="Best day: %s" % bd["date"], body="%s on %d trades (%d wins)." % (money(bd["net"]), bd["n"], bd["wins"])))
    wd = min(A["daily"], key=lambda x: x["net"])
    if wd["net"] < 0:
        I.append(dict(kind="leak", title="Worst day: %s" % wd["date"], body="%s on %d trades (%d wins)." % (money(wd["net"]), wd["n"], wd["wins"])))
    # best hour
    hb = [r for r in A["hours"] if r["trades"] >= 3]
    if hb:
        b = max(hb, key=lambda r: r["net"])
        if b["net"] > 0:
            I.append(dict(kind="strength", title="Best hour: %02d:00 PT" % b["k"], body="%d trades, %s, win rate %.0f%%." % (b["trades"], money(b["net"]), b["wr"])))
    # quick scalps
    q = [t for t in trades if t["hold_s"] < 60]
    if len(q) >= 3 and sum(t["net"] for t in q) < 0:
        I.append(dict(kind="leak", title="Sub-minute trades", body="%d trades held under 60s: %s." % (len(q), money(sum(t["net"] for t in q))),
                      rule="Test: require a 3-minute minimum plan for each entry."))
    bh = A["behavior"]
    if bh["revenge"]["n"]:
        r = bh["revenge"]
        I.append(dict(kind="leak" if r["net"] < 0 else "info", title="Re-entries within 2 min of a loss",
                      body="%d trades, %d wins, %s." % (r["n"], r["wins"], money(r["net"])) + ("" if r["net"] < 0 else " Not a leak in this sample.")))
    if bh["overtrading_days"]:
        I.append(dict(kind="leak", title="Overtrading days", body="%s: more than 1.3x your %.0f-trade daily average." % (", ".join(bh["overtrading_days"]), bh["avg_trades_per_day"])))
    return I


def reconcile(db, trades):
    """Compare Performance-report gross P&L with the rebuilt trades, per trade date."""
    pairs = db.execute("""SELECT p.pnl, p.qty, MAX(b.trade_date, s.trade_date) AS td
                          FROM perf_pairs p JOIN fills b ON b.fill_id=p.buy_fill JOIN fills s ON s.fill_id=p.sell_fill""").fetchall()
    total_pairs = db.execute("SELECT COUNT(*) FROM perf_pairs").fetchone()[0]
    if not total_pairs:
        return None
    perf = collections.defaultdict(float)
    for p in pairs: perf[p["td"]] += p["pnl"]
    mine = collections.defaultdict(float)
    for t in trades: mine[t["trade_date"]] += t["gross"]
    rows = [dict(date=d, perf=round(perf.get(d, 0), 2), mine=round(mine.get(d, 0), 2), diff=round(mine.get(d, 0) - perf.get(d, 0), 2)) for d in sorted(set(perf) | set(mine)) if d in perf]
    return dict(pairs=total_pairs, unmatched=total_pairs - len(pairs), rows=rows, ok=all(abs(r["diff"]) <= 1 for r in rows))
