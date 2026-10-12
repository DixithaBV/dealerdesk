"""Runs without Django or a database:  python -m unittest discover -s tests -t ."""
import os, sys, unittest
from decimal import Decimal

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [ROOT, os.path.join(ROOT, "supplier_mock")]
import mock_supplier as ms  # noqa: E402
from supplier import feed  # noqa: E402


def run(mock, **kw):
    httpd = ms.serve(mock, port=0)
    try:
        port = httpd.server_address[1]
        return feed.fetch_all(f"http://127.0.0.1:{port}", "k", sleep=lambda s: __import__("time").sleep(min(s, 1.1)), **kw)
    finally:
        httpd.shutdown()


class FeedTests(unittest.TestCase):
    def setUp(self):
        self.feed = ms.build_public_feed(os.path.join(ROOT, "data", "catalogue.csv"))

    def test_fetches_everything_through_rate_limits_and_a_500(self):
        mock = ms.SupplierMock(self.feed, "k", throttle_every=4, retry_after=1, transient={2: [500]})
        items, pages, made = run(mock)
        self.assertEqual(len(items), len(self.feed))
        self.assertEqual(pages, -(-len(self.feed) // 20))
        self.assertGreater(made, pages)

    def test_outage_raises_after_5_attempts_on_that_page(self):
        mock = ms.SupplierMock(self.feed, "k", outage_pages=[1])
        with self.assertRaises(feed.SupplierUnavailable):
            run(mock)
        self.assertEqual(sum(1 for r in mock.log if r["page"] == 1 and r["status"] == 503), 5)

    def test_bad_key_is_not_retried(self):
        mock = ms.SupplierMock(self.feed, "other-key")
        with self.assertRaises(feed.SupplierUnavailable):
            run(mock)
        self.assertEqual(len(mock.log), 1)

    def test_clean_rejects_invalid_and_keeps_latest_duplicate(self):
        unique, rejected = feed.clean(self.feed)
        reasons = sorted(r["reason"] for r in rejected)
        self.assertEqual(reasons, ["invalid price", "invalid price", "missing sku"])
        skus = [i["sku"] for i in self.feed if i.get("sku")]
        for sku in {s for s in skus if skus.count(s) > 1}:
            copies = [i for i in self.feed if i.get("sku") == sku and feed.parse_price(i["price"])]
            newest = max(copies, key=lambda i: feed.parse_ts(i["updated_at"]))
            self.assertEqual(unique[sku]["_price"], feed.parse_price(newest["price"]))

    def test_price_rules(self):
        ok = lambda v: feed.parse_price(v) is not None
        self.assertTrue(ok("12.50") and ok(12.5) and ok("100"))
        self.assertFalse(ok("12.345") or ok("N/A") or ok("0") or ok("-3.00") or ok(None) or ok("NaN") or ok(True))
        self.assertEqual(feed.parse_price("1499.0"), Decimal("1499.00"))


if __name__ == "__main__":
    unittest.main()
