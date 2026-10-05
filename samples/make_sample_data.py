#!/usr/bin/env python3
"""Generate synthetic Tradovate-style Fills + Performance CSVs for trying Edgebook.

No real trades: prices are a random walk and results are made up (seeded, so output is repeatable).
    python3 samples/make_sample_data.py          -> samples/sample_fills.csv, samples/sample_performance.csv
"""
import csv
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

PT = ZoneInfo("America/Los_Angeles")
OUT = Path(__file__).parent
rng = random.Random(7)
fid = 682000000000
fills, price = [], 21450.0


def nid():
    global fid
    fid += rng.randint(3, 9)
    return fid


def add(ts, side, qty, px, contract="MNQZ6", product="MNQ"):
    comm = (0.5 if product == "MNQ" else 1.75) * qty
    f = dict(id=nid(), ts=ts, side=side, qty=qty, px=px, contract=contract, product=product, comm=comm)
    fills.append(f)
    return f


start = datetime(2026, 9, 14, 6, 35, tzinfo=PT)
day = 0
while day < 14:
    d = start + timedelta(days=day)
    day += 1
    if d.weekday() >= 5:
        continue
    t = d
    n_trades = rng.randint(6, 16)
    # a calm morning edge that fades into an undisciplined afternoon
    for k in range(n_trades):
        t += timedelta(minutes=rng.randint(2, 25), seconds=rng.randint(0, 59))
        if t.hour >= 13:
            t = t.replace(hour=12, minute=rng.randint(0, 40))
        late = k > n_trades * 0.65
        side = rng.choice(["Buy", "Buy", "Sell"])
        size = rng.choice([1, 2, 2, 3, 4]) + (2 if late else 0)
        drift = rng.gauss(0.5 if not late else -1.5, 6)
        sgn = 1 if side == "Buy" else -1
        price += rng.gauss(0, 4)
        entry = round(price * 4) / 4
        exit_px = round((entry + sgn * drift) * 4) / 4
        parts = [size] if size < 3 or rng.random() < .6 else [size - size // 2, size // 2]
        tt = t
        for q in parts:
            add(tt, side, q, entry)
            tt += timedelta(seconds=rng.randint(1, 20))
        tt += timedelta(seconds=rng.randint(20, 400))
        add(tt, "Sell" if side == "Buy" else "Buy", size, exit_px)
        t = tt
        price = exit_px

fills.sort(key=lambda f: f["ts"])
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
                    "Micro E-mini NASDAQ-100", f["comm"]])

# Performance: pair buys with sells FIFO at fill level, like Tradovate's report
pos, lots, pairs = 0, [], []
for f in fills:
    q, sgn = f["qty"], 1 if f["side"] == "Buy" else -1
    while q:
        if not lots or lots[0][0] == sgn:
            lots.append([sgn, q, f]); q = 0
        else:
            take = min(q, lots[0][1]); o = lots[0][2]
            buy, sell = (f, o) if sgn == 1 else (o, f)
            pairs.append((buy, sell, take, (sell["px"] - buy["px"]) * take * 2))
            lots[0][1] -= take; q -= take
            if lots[0][1] == 0: lots.pop(0)
with open(OUT / "sample_performance.csv", "w", newline="") as fh:
    w = csv.writer(fh)
    w.writerow(["symbol", "_priceFormat", "_priceFormatType", "_tickSize", "buyFillId", "sellFillId", "qty", "buyPrice", "sellPrice", "pnl",
                "boughtTimestamp", "soldTimestamp", "duration"])
    for b, s, q, pnl in pairs:
        p = "$%.2f" % pnl if pnl >= 0 else "$(%.2f)" % -pnl
        w.writerow(["MNQZ6", -2, 0, 0.25, b["id"], s["id"], q, "%.2f" % b["px"], "%.2f" % s["px"], p,
                    b["ts"].strftime("%m/%d/%Y %H:%M:%S"), s["ts"].strftime("%m/%d/%Y %H:%M:%S"), ""])
print("fills:", len(fills), "perf pairs:", len(pairs))
