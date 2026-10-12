import os, sys

from django.conf import settings
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from catalog.models import Inventory, Product
from core.testing import make_product

sys.path.insert(0, os.path.join(settings.BASE_DIR, "supplier_mock"))
import mock_supplier as ms  # noqa: E402


class SyncTests(TestCase):
    def serve(self, **kw):
        feed = ms.build_public_feed(os.path.join(settings.DATA_DIR, "catalogue.csv"))
        mock = ms.SupplierMock(feed, "k", **kw)
        httpd = ms.serve(mock, port=0)
        self.addCleanup(httpd.shutdown)
        return feed, mock, f"http://127.0.0.1:{httpd.server_address[1]}"

    def test_sync_applies_then_is_idempotent_and_never_touches_stock(self):
        from django.core.management import call_command
        call_command("seed_data", verbosity=0)
        stock_before = dict(Inventory.objects.values_list("product__sku", "quantity"))
        feed, mock, url = self.serve(throttle_every=4, retry_after=1, transient={2: [500]})
        with override_settings(SUPPLIER_API_URL=url, SUPPLIER_API_KEY="k"):
            r = APIClient().post("/api/sync/supplier/")
            self.assertEqual(r.status_code, 200, r.content)
            b = r.json()
            self.assertEqual(len(b["rejected"]), 3)
            self.assertEqual(b["created"], 12)
            self.assertEqual(b["created"] + b["updated"] + b["unchanged"], len(set(i["sku"] for i in feed if i["sku"] and i["price"] not in ("N/A", "12.345"))))
            again = APIClient().post("/api/sync/supplier/").json()
            self.assertEqual((again["created"], again["updated"]), (0, 0))
        after = dict(Inventory.objects.filter(product__sku__in=stock_before).values_list("product__sku", "quantity"))
        self.assertEqual(stock_before, after)
        self.assertEqual(Inventory.objects.get(product__sku="BRK-5000").quantity, 0)

    def test_outage_changes_nothing_and_returns_502(self):
        make_product("ZZZ-0001", "10.00", 1)
        feed, mock, url = self.serve(outage_pages=[1])
        with override_settings(SUPPLIER_API_URL=url, SUPPLIER_API_KEY="k"):
            r = APIClient().post("/api/sync/supplier/")
        self.assertEqual((r.status_code, r.json()["error"]["code"]), (502, "SUPPLIER_UNAVAILABLE"))
        self.assertEqual(Product.objects.count(), 1)

    def test_wrong_key_is_502(self):
        feed, mock, url = self.serve()
        with override_settings(SUPPLIER_API_URL=url, SUPPLIER_API_KEY="wrong"):
            self.assertEqual(APIClient().post("/api/sync/supplier/").status_code, 502)
