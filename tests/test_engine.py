import csv
import io
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from edgebook import engine

HDR = ["_timestamp", "_tradeDate", "Fill ID", "Order ID", "Account", "B/S", "Quantity", "Price", "Contract", "Product", "commission"]
T0 = datetime(2026, 10, 1, 16, 0, tzinfo=timezone.utc)  # 09:00 PT


def fills_csv(rows):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(HDR)
    for i, (sec, side, qty, px, prod) in enumerate(rows, 1):
        ts = (T0 + timedelta(seconds=sec)).strftime("%Y-%m-%d %H:%M:%S.000Z")
        w.writerow([ts, "2026-10-01", 1000 + i, 500 + i, "ACC", " " + side, qty, px, prod + "Z6", prod, 0.5 * qty])
    return buf.getvalue()


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.db = engine.connect(Path(tempfile.mkdtemp()) / "t.db")
        self.pv = engine.get_point_values(self.db)

    def trades(self, rows):
        engine.import_text(self.db, "t.csv", fills_csv(rows), self.pv)
        return engine.build_trades(self.db, self.pv)

    def test_simple_long(self):
        (t,), open_pos = self.trades([(0, "Buy", 2, 100.0, "MNQ"), (60, "Sell", 2, 105.0, "MNQ")])
        self.assertEqual(open_pos, [])
        self.assertEqual(t["dir"], "Long")
        self.assertAlmostEqual(t["gross"], 5 * 2 * 2)       # 5 pts x 2 lots x $2
        self.assertAlmostEqual(t["fees"], 2.0)              # 0.5 per contract per side
        self.assertAlmostEqual(t["net"], 18.0)
        self.assertEqual(t["hold_s"], 60)

    def test_short_scale_in_and_out(self):
        (t,), _ = self.trades([(0, "Sell", 1, 100.0, "MNQ"), (5, "Sell", 1, 102.0, "MNQ"),
                               (30, "Buy", 1, 99.0, "MNQ"), (40, "Buy", 1, 98.0, "MNQ")])
        self.assertEqual(t["dir"], "Short")
        self.assertEqual(t["max_q"], 2)
        self.assertAlmostEqual(t["avg_in"], 101.0)
        self.assertAlmostEqual(t["gross"], ((100 - 99) + (102 - 98)) * 2)

    def test_reversal_splits_into_two_trades(self):
        trades, open_pos = self.trades([(0, "Buy", 2, 100.0, "MNQ"), (30, "Sell", 4, 101.0, "MNQ"), (90, "Buy", 2, 100.0, "MNQ")])
        self.assertEqual([t["dir"] for t in trades], ["Long", "Short"])
        self.assertEqual(open_pos, [])
        self.assertAlmostEqual(trades[0]["gross"], 1 * 2 * 2)
        self.assertAlmostEqual(trades[1]["gross"], 1 * 2 * 2)

    def test_open_position_is_not_a_trade(self):
        trades, open_pos = self.trades([(0, "Buy", 3, 100.0, "MNQ")])
        self.assertEqual(trades, [])
        self.assertEqual(open_pos[0]["qty"], 3)

    def test_reimport_skips_duplicates(self):
        text = fills_csv([(0, "Buy", 1, 100.0, "MNQ"), (10, "Sell", 1, 101.0, "MNQ")])
        engine.import_text(self.db, "a.csv", text, self.pv)
        res = engine.import_text(self.db, "a.csv", text, self.pv)
        self.assertEqual((res["new"], res["duplicates"]), (0, 2))
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM fills").fetchone()[0], 2)

    def test_point_values_differ_by_product(self):
        (a,), _ = self.trades([(0, "Buy", 1, 100.0, "NQ"), (10, "Sell", 1, 101.0, "NQ")])
        self.assertAlmostEqual(a["gross"], 20.0)

    def test_times_are_pacific(self):
        (t,), _ = self.trades([(0, "Buy", 1, 100.0, "MNQ"), (10, "Sell", 1, 101.0, "MNQ")])
        self.assertTrue(t["open"].startswith("2026-10-01 09:00:00"))

    def test_unrecognised_file_rejected(self):
        with self.assertRaises(ValueError):
            engine.import_text(self.db, "x.csv", "a,b\n1,2\n", self.pv)

    def test_analyze_metrics(self):
        rows = [(0, "Buy", 1, 100.0, "MNQ"), (10, "Sell", 1, 110.0, "MNQ"),     # +20 gross
                (100, "Buy", 1, 100.0, "MNQ"), (110, "Sell", 1, 95.0, "MNQ")]   # -10 gross
        trades, _ = self.trades(rows)
        A = engine.analyze(engine.merge_notes(self.db, trades))
        M = A["metrics"]
        self.assertEqual(M["trades"], 2)
        self.assertAlmostEqual(M["gross"], 10.0)
        self.assertAlmostEqual(M["net"], 8.0)
        self.assertAlmostEqual(M["win_rate"], 50.0)
        self.assertAlmostEqual(M["pf"], 19 / 11)

    def test_notes_give_r_multiple(self):
        trades, _ = self.trades([(0, "Buy", 1, 100.0, "MNQ"), (10, "Sell", 1, 110.0, "MNQ")])
        self.db.execute("INSERT INTO trade_notes(key,risk) VALUES(?,?)", (trades[0]["key"], 10.0))
        t = engine.merge_notes(self.db, trades)[0]
        self.assertAlmostEqual(t["r"], 1.9)


if __name__ == "__main__":
    unittest.main()
