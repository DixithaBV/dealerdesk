import csv, math, os, sys, unittest
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from forecasting import reorder as R  # noqa: E402


class ForecastFileTests(unittest.TestCase):
    def test_forecast_csv_schema_and_coverage(self):
        rows = list(csv.DictReader(open(os.path.join(ROOT, "ml", "forecast.csv"))))
        self.assertEqual(list(rows[0].keys()), ["sku", "week_start", "forecast_units"])
        skus = {r["sku"] for r in csv.DictReader(open(os.path.join(ROOT, "data", "lead_times.csv")))}
        self.assertEqual(len(skus), 40)
        self.assertEqual({(r["sku"], r["week_start"]) for r in rows}, {(s, w) for s in skus for w in R.WEEKS})
        self.assertEqual(len(rows), 160)
        for r in rows:
            v = float(r["forecast_units"])
            self.assertTrue(math.isfinite(v) and v >= 0)

    def test_reorder_formula(self):
        # sigma of [10,12,14] = 2 ; L=2 ; safety = ceil(1.65*2*sqrt(2)) = ceil(4.667) = 5
        e = R.reorder_entry("X", 2, {w: 30.0 for w in R.WEEKS}, [10, 12, 14], 40)
        self.assertEqual((e["lead_time_demand"], e["safety_stock"], e["reorder_point"], e["reorder_qty"]), (60.0, 5, 65.0, 25))
        self.assertEqual(R.reorder_entry("X", 1, {w: 1.0 for w in R.WEEKS}, [5, 5], 99)["reorder_qty"], 0)

    def test_all_40_entries_from_files(self):
        fc, leads = R.load_forecast(os.path.join(ROOT, "ml")), R.load_lead_times(os.path.join(ROOT, "data"))
        rec = R.load_recent_sales(os.path.join(ROOT, "data"))
        res = [R.reorder_entry(s, L, fc[s], rec[s], 0) for s, L in leads]
        self.assertEqual(len(res), 40)
        self.assertTrue(all(r["reorder_qty"] >= 0 for r in res))
        self.assertLessEqual(len(rec["BRK-1105"]), 6)  # new SKU: only its own weeks are used


if __name__ == "__main__":
    unittest.main()
