#!/usr/bin/env python3
"""Generate SYNTHETIC Tradovate-style Fills + Performance CSVs for trying Edgebook.

Nothing here is real trading: a seeded random generator produces a made-up month for an account
called DEMO-ACCOUNT (Edgebook shows a "Demo data" badge whenever only that account is loaded).
The numbers are tuned so screenshots show a strong, but fictional, month.

    python3 samples/make_sample_data.py                -> samples/sample_fills.csv, samples/sample_performance.csv
    python3 samples/make_sample_data.py --search       -> find a seed that meets the target profile
"""
import argparse
import csv
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

PT = ZoneInfo("America/Los_Angeles")
OUT = Path(__file__).parent
SEED = 3  # found with --search: ~$30k net, ~60% win rate, 3 red days
PRODUCTS = {"MNQ": ("MNQZ6", 2, 0.5, "Micro E-mini NASDAQ-100"), "NQ": ("NQZ6", 20, 1.75, "E-Mini NASDAQ 100")}
DAYS = [datetime(2026, 9, d, tzinfo=PT) for d in range(1, 31) if datetime(2026, 9, d).weekday() < 5 and d != 7]  # 21 sessions


def simulate(seed):
    rng = random.Random(seed)
    fid, price, fills, trades = 682000000000, 21450.0, [], []

    def add(ts, side, qty, px, prod):
        nonlocal fid
        fid += rng.randint(3, 9)
        contract, _, cpc, _ = PRODUCTS[prod]
        fills.append(dict(id=fid, ts=ts, side=side, qty=qty, px=px, contract=contract, product=prod, comm=cpc * qty))

    for d in DAYS:
        edge = rng.choice([0.80, 0.72, 0.66, 0.62, 0.58, 0.50, 0.40])   # some days are simply bad
        t = d.replace(hour=6, minute=32)
        for k in range(rng.randint(9, 15)):
            t += timedelta(minutes=rng.randint(3, 24), seconds=rng.randint(0, 59))
            if t.hour >= 13:
                break
            prod = "NQ" if rng.random() < 0.3 else "MNQ"
            size = rng.choice([1, 2, 2, 3]) if prod == "NQ" else rng.choice([6, 8, 10, 10, 12, 15, 20])
            side = "Buy" if rng.random() < 0.55 else "Sell"
            sgn = 1 if side == "Buy" else -1
            late = t.hour >= 11
            win = rng.random() < (edge - (0.12 if late else 0))
            pts = abs(rng.gauss(9.5, 4)) + 2 if win else -(abs(rng.gauss(5.5, 2)) + 1.5)
            price += rng.gauss(0, 6)
            entry = round(price * 4) / 4
            split = rng.random() < 0.4 and size >= 2
            parts = [size - size // 2, size // 2] if split else [size]
            tt, vals = t, []
            for q in parts:
                add(tt, side, q, entry, prod)
                tt += timedelta(seconds=rng.randint(1, 15))
            tt += timedelta(seconds=rng.randint(25, 420))
            outs = [size - size // 2, size // 2] if size >= 4 and win and rng.random() < .5 else [size]
            gross = 0.0
            for j, q in enumerate(outs):
                p = pts * (0.65 if j == 0 and len(outs) > 1 else 1.25 if len(outs) > 1 else 1)
                ex = round((entry + sgn * p) * 4) / 4
                add(tt, "Sell" if side == "Buy" else "Buy", q, ex, prod)
                gross += (ex - entry) * sgn * q * PRODUCTS[prod][1]
                tt += timedelta(seconds=rng.randint(5, 60))
            trades.append((d, gross - PRODUCTS[prod][2] * size * 2, gross))
            t, price = tt, entry + sgn * pts
    return fills, trades


def stats(trades):
    net = sum(t[1] for t in trades)
    wr = sum(t[1] > 0 for t in trades) / len(trades)
    days = {}
    for d, n, _ in trades:
        days[d] = days.get(d, 0) + n
    return net, wr, sum(v < 0 for v in days.values()), len(days)


def search():
    for s in range(1, 5000):
        net, wr, red, nd = stats(simulate(s)[1])
        if 30000 <= net <= 31500 and 0.60 <= wr <= 0.66 and 3 <= red <= 5:
            print("seed", s, "net", round(net), "win rate", round(wr * 100, 1), "red days", red, "of", nd)
            return s
    raise SystemExit("no seed found")


def write(seed):
    fills, trades = simulate(seed)
    fills.sort(key=lambda f: (f["ts"], f["id"]))
    hdr = ["_id", "_orderId", "_contractId", "_timestamp", "_tradeDate", "_action", "_qty", "_price", "_active", "_accountId",
           "Fill ID", "Order ID", "Timestamp", "Date", "Account", "B/S", "Quantity", "Price", "_priceFormat", "_priceFormatType",
           "_tickSize", "Contract", "Product", "Product Description", "commission"]
    with open(OUT / "sample_fills.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(hdr)
        for f in fills:
            utc = f["ts"].astimezone(timezone.utc)
            w.writerow([f["id"], f["id"] - 3, 1000001, utc.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3] + "Z",
                        (utc + timedelta(hours=3)).strftime("%Y-%m-%d"), 1 if f["side"] == "Sell" else 0, f["qty"], f["px"], "true",
                        12345678, f["id"], f["id"] - 3, f["ts"].strftime("%m/%d/%Y %H:%M:%S"), f["ts"].strftime("%-m/%-d/%y"),
                        "DEMO-ACCOUNT", " " + f["side"], f["qty"], "%.2f" % f["px"], -2, 0, 0.25, f["contract"], f["product"],
                        PRODUCTS[f["product"]][3], f["comm"]])
    # Performance report: pair buys with sells FIFO per contract at fill level
    books, pairs = {}, []
    for f in fills:
        lots, q, sgn = books.setdefault(f["contract"], []), f["qty"], 1 if f["side"] == "Buy" else -1
        while q:
            if not lots or lots[0][0] == sgn:
                lots.append([sgn, q, f]); q = 0
            else:
                take = min(q, lots[0][1]); o = lots[0][2]
                b, s = (f, o) if sgn == 1 else (o, f)
                pairs.append((b, s, take, (s["px"] - b["px"]) * take * PRODUCTS[f["product"]][1]))
                lots[0][1] -= take; q -= take
                if lots[0][1] == 0: lots.pop(0)
    pairs.sort(key=lambda p: max(p[0]["ts"], p[1]["ts"]))
    with open(OUT / "sample_performance.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["symbol", "_priceFormat", "_priceFormatType", "_tickSize", "buyFillId", "sellFillId", "qty", "buyPrice", "sellPrice", "pnl",
                    "boughtTimestamp", "soldTimestamp", "duration"])
        for b, s, q, pnl in pairs:
            p = "$%.2f" % pnl if pnl >= 0 else "$(%.2f)" % -pnl
            w.writerow([b["contract"], -2, 0, 0.25, b["id"], s["id"], q, "%.2f" % b["px"], "%.2f" % s["px"], p,
                        b["ts"].strftime("%m/%d/%Y %H:%M:%S"), s["ts"].strftime("%m/%d/%Y %H:%M:%S"), ""])
    net, wr, red, nd = stats(trades)
    print("fills", len(fills), "| trades", len(trades), "| net $%.0f" % net, "| win rate %.1f%%" % (wr * 100), "| red days", red, "of", nd)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--search", action="store_true")
    ap.add_argument("--seed", type=int, default=None)
    a = ap.parse_args()
    write(search() if a.search else (a.seed if a.seed is not None else SEED))
