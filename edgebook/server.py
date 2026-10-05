#!/usr/bin/env python3
"""Edgebook server: a local-only HTTP API + static UI over a SQLite journal.

Run:  python3 -m edgebook        (opens http://127.0.0.1:8765)
Data: ~/Edgebook  (override with --data DIR or EDGEBOOK_DIR)
"""
import argparse
import csv
import io
import json
import mimetypes
import os
import shutil
import socket
import sys
import threading
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import engine

HERE = Path(__file__).resolve().parent
STATIC = HERE / "static"
MAX_BODY = 100 * 1024 * 1024
LOCK = threading.Lock()
DATA = Path(os.environ.get("EDGEBOOK_DIR", Path.home() / "Edgebook"))

TRADE_COLS = ["Trade ID", "Trade Date", "Instrument", "Direction", "Entry Time (PT)", "Exit Time (PT)", "Hold (sec)",
              "Max Contracts", "Avg Entry", "Avg Exit", "Points", "Gross P&L", "Fees", "Net P&L", "# Fills",
              "Setup", "Mistake", "Risk $", "R", "Notes"]


def shown(p):
    """Path for display, with the home folder abbreviated to ~."""
    s, h = str(p), str(Path.home())
    return "~" + s[len(h):] if s.startswith(h) else s


def db():
    return engine.connect(DATA / "journal.db")


def trade_rows(trades):
    for i, t in enumerate(trades, 1):
        yield [i, t["trade_date"], t["contract"], t["dir"], t["open"][:19], t["close"][:19], round(t["hold_s"]), t["max_q"],
               round(t["avg_in"], 4), round(t["avg_out"], 4), round(t["points"], 4), round(t["gross"], 2),
               round(t["fees"], 2), round(t["net"], 2), len(t["fills"]), t["setup"], t["mistake"],
               t["risk"] if t["risk"] is not None else "", t["r"] if t["r"] is not None else "", t["notes"]]


def all_trades(conn):
    pv = engine.get_point_values(conn)
    trades, open_pos = engine.build_trades(conn, pv)
    return engine.merge_notes(conn, trades), open_pos


def autosave(conn):
    """Refresh the plain-CSV trade log and keep rolling database backups on disk."""
    trades, _ = all_trades(conn)
    trades.sort(key=lambda t: t["open_utc"])
    with open(DATA / "trade_log.csv", "w", newline="") as fh:
        w = csv.writer(fh); w.writerow(TRADE_COLS); w.writerows(trade_rows(trades))
    bdir = DATA / "backups"; bdir.mkdir(exist_ok=True)
    conn.commit()
    shutil.copy2(DATA / "journal.db", bdir / ("journal-%s.db" % datetime.now().strftime("%Y%m%d-%H%M%S")))
    for old in sorted(bdir.glob("journal-*.db"))[:-20]:
        old.unlink()


def filtered(trades, q):
    f, t, inst, d = (q.get(k, [""])[0] for k in ("from", "to", "inst", "dir"))
    out = []
    for x in trades:
        if f and x["trade_date"] < f: continue
        if t and x["trade_date"] > t: continue
        if inst and x["contract"] != inst: continue
        if d and x["dir"] != d: continue
        out.append(x)
    return out


class H(BaseHTTPRequestHandler):
    server_version = "Edgebook"

    def log_message(self, *a):
        pass

    # -- helpers
    def send(self, code, body, ctype="application/json", extra=None):
        if not isinstance(body, (bytes, bytearray)):
            body = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items(): self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX_BODY: raise ValueError("File too large")
        return json.loads(self.rfile.read(n) or b"{}")

    def host_ok(self):
        return self.headers.get("Host", "").split(":")[0] in ("127.0.0.1", "localhost")

    # -- routes
    def do_GET(self):
        if not self.host_ok(): return self.send(403, {"error": "forbidden"})
        u = urlparse(self.path); q = parse_qs(u.query); p = u.path
        try:
            if p == "/api/state":
                with LOCK, db() as c:
                    imps = [dict(r) for r in c.execute("SELECT * FROM imports ORDER BY id DESC")]
                    trades, open_pos = all_trades(c)
                    return self.send(200, dict(
                        data_dir=shown(DATA), imports=imps, open_positions=open_pos,
                        fills=c.execute("SELECT COUNT(*) FROM fills").fetchone()[0], trades=len(trades),
                        instruments=sorted({t["contract"] for t in trades}),
                        point_values=engine.get_point_values(c),
                        first=min((t["trade_date"] for t in trades), default=None),
                        last=max((t["trade_date"] for t in trades), default=None)))
            if p == "/api/analysis":
                with LOCK, db() as c:
                    trades, open_pos = all_trades(c)
                    sel = filtered(trades, q)
                    A = engine.analyze(sel)
                    A["trades"] = [{k: v for k, v in t.items() if k not in ("open_utc", "close_utc")} for t in sorted(sel, key=lambda t: t["close_utc"])]
                    A["recon"] = engine.reconcile(c, trades)
                    A["day_notes"] = {r["date"]: dict(r) for r in c.execute("SELECT * FROM day_notes")}
                    return self.send(200, A)
            if p.startswith("/api/trade/") and p.endswith("/fills"):
                key = p.split("/")[3]
                with LOCK, db() as c:
                    trades, _ = all_trades(c)
                    t = next((x for x in trades if x["key"] == key), None)
                    if not t: return self.send(404, {"error": "not found"})
                    ph = ",".join("?" * len(t["fills"]))
                    rows = [dict(r) for r in c.execute("SELECT fill_id,side,qty,price,commission,pt FROM fills WHERE fill_id IN (%s) ORDER BY utc" % ph, t["fills"])]
                    return self.send(200, rows)
            if p == "/api/export/trades.csv":
                with LOCK, db() as c:
                    trades, _ = all_trades(c)
                    trades = filtered(trades, q); buf = io.StringIO()
                    w = csv.writer(buf); w.writerow(TRADE_COLS); w.writerows(trade_rows(sorted(trades, key=lambda t: t["open_utc"])))
                    return self.send(200, buf.getvalue().encode(), "text/csv", {"Content-Disposition": 'attachment; filename="trade_log.csv"'})
            if p == "/api/backup":
                with LOCK, db() as c:
                    dump = {t: [dict(r) for r in c.execute("SELECT * FROM %s" % t)] for t in
                            ("imports", "fills", "perf_pairs", "trade_notes", "day_notes", "settings")}
                    return self.send(200, json.dumps(dump).encode(), "application/json",
                                     {"Content-Disposition": 'attachment; filename="journal-backup-%s.json"' % datetime.now().strftime("%Y%m%d")})
            return self.static(p)
        except Exception as e:  # surface errors to the UI
            return self.send(500, {"error": str(e)})

    def static(self, p):
        p = "/index.html" if p in ("/", "") else p
        f = (STATIC / p.lstrip("/")).resolve()
        if STATIC not in f.parents or not f.is_file():
            return self.send(404, {"error": "not found"})
        return self.send(200, f.read_bytes(), mimetypes.guess_type(f.name)[0] or "application/octet-stream")

    def do_POST(self):
        if not self.host_ok(): return self.send(403, {"error": "forbidden"})
        p = urlparse(self.path).path
        try:
            b = self.body()
            with LOCK, db() as c:
                if p == "/api/import":
                    res = engine.import_text(c, b["name"], b["text"], engine.get_point_values(c))
                    autosave(c)
                    return self.send(200, res)
                if p.startswith("/api/trade/"):
                    key = p.split("/")[3]
                    risk = b.get("risk")
                    risk = float(risk) if risk not in (None, "") else None
                    c.execute("""INSERT INTO trade_notes(key,setup,mistake,risk,notes,rating) VALUES(?,?,?,?,?,?)
                                 ON CONFLICT(key) DO UPDATE SET setup=excluded.setup, mistake=excluded.mistake,
                                 risk=excluded.risk, notes=excluded.notes, rating=excluded.rating""",
                              (key, b.get("setup", "").strip(), b.get("mistake", "").strip(), risk, b.get("notes", ""), int(b.get("rating") or 0)))
                    c.commit()
                    return self.send(200, {"ok": True})
                if p.startswith("/api/day/"):
                    d = p.split("/")[3]
                    c.execute("""INSERT INTO day_notes(date,notes,mood) VALUES(?,?,?)
                                 ON CONFLICT(date) DO UPDATE SET notes=excluded.notes, mood=excluded.mood""",
                              (d, b.get("notes", ""), int(b.get("mood") or 0)))
                    c.commit()
                    return self.send(200, {"ok": True})
                if p == "/api/settings":
                    pv = {k.strip().upper(): float(v) for k, v in b["point_values"].items() if k.strip()}
                    c.execute("INSERT OR REPLACE INTO settings VALUES('point_values',?)", (json.dumps(pv),))
                    c.commit(); autosave(c)
                    return self.send(200, {"ok": True})
                if p == "/api/import/delete":
                    iid = int(b["id"])
                    c.execute("DELETE FROM fills WHERE import_id=?", (iid,))
                    c.execute("DELETE FROM perf_pairs WHERE import_id=?", (iid,))
                    c.execute("DELETE FROM imports WHERE id=?", (iid,))
                    c.commit(); autosave(c)
                    return self.send(200, {"ok": True})
                if p == "/api/restore":
                    for t in ("imports", "fills", "perf_pairs", "trade_notes", "day_notes", "settings"):
                        c.execute("DELETE FROM %s" % t)
                        for r in b.get(t, []):
                            cols = list(r)
                            c.execute("INSERT INTO %s(%s) VALUES(%s)" % (t, ",".join(cols), ",".join("?" * len(cols))), [r[k] for k in cols])
                    c.commit(); autosave(c)
                    return self.send(200, {"ok": True})
                if p == "/api/reset":
                    if b.get("confirm") != "DELETE":
                        return self.send(400, {"error": "confirmation missing"})
                    autosave(c)  # final safety copy goes to backups/
                    for t in ("imports", "fills", "perf_pairs", "trade_notes", "day_notes"):
                        c.execute("DELETE FROM %s" % t)
                    c.commit(); autosave(c)
                    return self.send(200, {"ok": True})
            return self.send(404, {"error": "not found"})
        except Exception as e:
            return self.send(400, {"error": str(e)})


def main():
    global DATA
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", help="folder for the journal database (default ~/Edgebook)")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-browser", action="store_true")
    a = ap.parse_args()
    if a.data: DATA = Path(a.data).expanduser()
    DATA.mkdir(parents=True, exist_ok=True)
    engine.connect(DATA / "journal.db").close()
    for port in range(a.port, a.port + 10):
        try:
            srv = ThreadingHTTPServer(("127.0.0.1", port), H); break
        except OSError:
            continue
    else:
        sys.exit("No free port found")
    url = "http://127.0.0.1:%d" % port
    print("Edgebook running at %s\nData folder: %s\nPress Ctrl+C to stop." % (url, DATA))
    if not a.no_browser: threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
