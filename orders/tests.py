import threading
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

from django.db import connection
from django.test import TestCase, TransactionTestCase
from rest_framework.test import APIClient

from catalog.models import Inventory
from core.testing import make_dealer, make_product

from . import services as svc
from .money import line_amounts


class MoneyTests(TestCase):
    def test_half_up_per_line(self):
        self.assertEqual(line_amounts(Decimal("10.25"), 1), (Decimal("10.25"), Decimal("1.85"), Decimal("12.10")))  # 1.845 -> 1.85
        self.assertEqual(line_amounts(Decimal("1459.50"), 3), (Decimal("4378.50"), Decimal("788.13"), Decimal("5166.63")))


class OrderApiTests(TestCase):
    def setUp(self):
        self.c = APIClient()
        self.d = make_dealer()
        make_product("AAA-0001", "10.25", 5)
        make_product("BBB-0001", "200.00", 100)

    def post(self, items, **kw):
        return self.c.post("/api/orders/", {"dealer_id": self.d.id, "items": items}, format="json", **kw)

    def test_create_validation(self):
        for body in ({"dealer_id": self.d.id, "items": []},
                     {"dealer_id": self.d.id, "items": [{"sku": "AAA-0001", "quantity": 0}]},
                     {"dealer_id": self.d.id, "items": [{"sku": "NOPE", "quantity": 1}]},
                     {"dealer_id": self.d.id, "items": [{"sku": "AAA-0001", "quantity": 1}, {"sku": "AAA-0001", "quantity": 2}]},
                     {"dealer_id": 99999, "items": [{"sku": "AAA-0001", "quantity": 1}]}):
            r = self.c.post("/api/orders/", body, format="json")
            self.assertEqual((r.status_code, r.json()["error"]["code"]), (400, "VALIDATION_ERROR"), body)

    def test_draft_totals_and_live_price_then_locked_on_confirm(self):
        o = self.post([{"sku": "AAA-0001", "quantity": 1}, {"sku": "BBB-0001", "quantity": 2}]).json()
        self.assertEqual((o["status"], o["subtotal"], o["tax_total"], o["grand_total"]), ("DRAFT", "410.25", "73.85", "484.10"))
        self.assertRegex(o["order_number"], r"^ORD-\d{8}-0001$")
        self.c.patch("/api/products/BBB-0001/", {"price": "300.00"}, format="json")
        self.assertEqual(self.c.get(f"/api/orders/{o['order_number']}/").json()["subtotal"], "610.25")  # DRAFT follows price
        self.assertEqual(self.c.post(f"/api/orders/{o['order_number']}/confirm/").status_code, 200)
        self.c.patch("/api/products/BBB-0001/", {"price": "999.00"}, format="json")
        self.assertEqual(self.c.get(f"/api/orders/{o['order_number']}/").json()["subtotal"], "610.25")  # locked

    def test_lifecycle_and_stock(self):
        n = self.post([{"sku": "AAA-0001", "quantity": 2}]).json()["order_number"]
        self.assertEqual(Inventory.objects.get(product__sku="AAA-0001").quantity, 5)  # draft: no effect
        self.assertEqual(self.c.post(f"/api/orders/{n}/confirm/").json()["status"], "CONFIRMED")
        self.assertEqual(Inventory.objects.get(product__sku="AAA-0001").quantity, 3)
        r = self.c.put(f"/api/orders/{n}/", {"items": [{"sku": "AAA-0001", "quantity": 1}]}, format="json")
        self.assertEqual((r.status_code, r.json()["error"]["code"]), (409, "ORDER_LOCKED"))
        self.assertEqual(self.c.post(f"/api/orders/{n}/cancel/").json()["status"], "CANCELLED")
        self.assertEqual(Inventory.objects.get(product__sku="AAA-0001").quantity, 5)
        self.assertEqual(self.c.post(f"/api/orders/{n}/cancel/").json()["error"]["code"], "INVALID_TRANSITION")
        self.assertEqual(Inventory.objects.get(product__sku="AAA-0001").quantity, 5)  # not restored twice

    def test_dispatch_deliver_and_no_cancel_after_dispatch(self):
        n = self.post([{"sku": "BBB-0001", "quantity": 1}]).json()["order_number"]
        self.assertEqual(self.c.post(f"/api/orders/{n}/dispatch/").status_code, 409)
        self.c.post(f"/api/orders/{n}/confirm/")
        self.assertEqual(self.c.post(f"/api/orders/{n}/dispatch/").json()["status"], "DISPATCHED")
        self.assertEqual(self.c.post(f"/api/orders/{n}/cancel/").status_code, 409)
        self.assertEqual(self.c.post(f"/api/orders/{n}/deliver/").json()["status"], "DELIVERED")

    def test_insufficient_stock_lists_every_short_line_and_changes_nothing(self):
        make_product("CCC-0001", "5.00", 1)
        n = self.post([{"sku": "AAA-0001", "quantity": 9}, {"sku": "CCC-0001", "quantity": 4}, {"sku": "BBB-0001", "quantity": 1}]).json()["order_number"]
        r = self.c.post(f"/api/orders/{n}/confirm/")
        e = r.json()["error"]
        self.assertEqual((r.status_code, e["code"]), (409, "INSUFFICIENT_STOCK"))
        self.assertEqual({d["sku"] for d in e["details"]}, {"AAA-0001", "CCC-0001"})
        self.assertIn("Available: 5, Requested: 9", e["message"])
        self.assertEqual(Inventory.objects.get(product__sku="BBB-0001").quantity, 100)

    def test_idempotency_sequential(self):
        a = self.post([{"sku": "BBB-0001", "quantity": 1}], HTTP_IDEMPOTENCY_KEY="k1")
        b = self.post([{"sku": "BBB-0001", "quantity": 1}], HTTP_IDEMPOTENCY_KEY="k1")
        self.assertEqual((a.status_code, b.status_code), (201, 200))
        self.assertEqual(a.json()["order_number"], b.json()["order_number"])
        c = self.post([{"sku": "BBB-0001", "quantity": 2}], HTTP_IDEMPOTENCY_KEY="k1")
        self.assertEqual((c.status_code, c.json()["error"]["code"]), (409, "IDEMPOTENCY_CONFLICT"))

    def test_list_filters(self):
        self.post([{"sku": "BBB-0001", "quantity": 1}])
        self.assertEqual(self.c.get(f"/api/orders/?dealer_id={self.d.id}&status=DRAFT").json()["count"], 1)
        self.assertEqual(self.c.get("/api/orders/?status=CONFIRMED").json()["count"], 0)


def in_threads(fn, n):
    barrier = threading.Barrier(n)

    def run(i):
        try:
            barrier.wait()
            return fn(i)
        except Exception as e:  # collected, not raised, so one failure doesn't hide the others
            return e
        finally:
            connection.close()
    with ThreadPoolExecutor(n) as ex:
        return list(ex.map(run, range(n)))


class ConcurrencyTests(TransactionTestCase):
    """Real PostgreSQL row locks: these need the real database, so they are TransactionTestCase with threads."""

    def setUp(self):
        self.d = make_dealer()

    def test_never_oversells(self):
        make_product("HOT-0001", "50.00", 5)
        numbers = [svc.create_order(self.d.id, [{"sku": "HOT-0001", "quantity": 1}])[0] for _ in range(12)]
        res = in_threads(lambda i: svc.confirm(numbers[i]), 12)
        ok = [r for r in res if isinstance(r, str)]
        bad = [r for r in res if not isinstance(r, str)]
        self.assertEqual(len(ok), 5)
        self.assertTrue(all(getattr(e, "code", "") == "INSUFFICIENT_STOCK" for e in bad), bad)
        self.assertEqual(Inventory.objects.get(product__sku="HOT-0001").quantity, 0)

    def test_concurrent_cancel_restores_once(self):
        make_product("CXL-0001", "50.00", 10)
        n = svc.create_order(self.d.id, [{"sku": "CXL-0001", "quantity": 4}])[0]
        svc.confirm(n)
        res = in_threads(lambda i: svc.cancel(n), 8)
        self.assertEqual(sum(isinstance(r, str) for r in res), 1)
        self.assertEqual(Inventory.objects.get(product__sku="CXL-0001").quantity, 10)

    def test_same_idempotency_key_at_once_creates_one_order(self):
        make_product("IDM-0001", "50.00", 10)
        res = in_threads(lambda i: svc.create_order(self.d.id, [{"sku": "IDM-0001", "quantity": 1}], "same-key"), 10)
        self.assertTrue(all(isinstance(r, tuple) for r in res), res)
        self.assertEqual(len({r[0] for r in res}), 1)
        self.assertEqual(sum(1 for r in res if r[1]), 1)

    def test_order_numbers_unique_and_sequential(self):
        make_product("SEQ-0001", "50.00", 10)
        res = in_threads(lambda i: svc.create_order(self.d.id, [{"sku": "SEQ-0001", "quantity": 1}])[0], 15)
        self.assertEqual(len(set(res)), 15, res)
        self.assertEqual(sorted(int(r[-4:]) for r in res), list(range(1, 16)))
