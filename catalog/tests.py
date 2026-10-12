from django.test import TestCase
from rest_framework.test import APIClient

from core.testing import make_dealer, make_product


class CatalogApiTests(TestCase):
    def setUp(self):
        self.c = APIClient()
        make_product("BRK-0001", "1459.50", 7, fitment="Bajaj Pulsar 150")

    def test_health_and_product_shape(self):
        self.assertEqual(self.c.get("/api/health/").json(), {"status": "ok"})
        r = self.c.get("/api/products/BRK-0001/").json()
        self.assertEqual((r["price"], r["stock"]), ("1459.50", 7))

    def test_pagination_and_filters(self):
        make_product("OIL-0001", "300.00", 1, category="Engine & Oils")
        b = self.c.get("/api/products/?page_size=1").json()
        self.assertEqual((b["count"], len(b["results"])), (2, 1))
        self.assertIsNotNone(b["next"])
        self.assertEqual(self.c.get("/api/products/?vehicle=pulsar").json()["count"], 1)
        self.assertEqual(self.c.get("/api/products/?search=oil-0").json()["count"], 1)
        self.assertEqual(self.c.get("/api/products/?category=Brakes").json()["count"], 1)

    def test_create_duplicate_and_validation(self):
        body = {"sku": "NEW-0001", "name": "N", "price": "10.50"}
        self.assertEqual(self.c.post("/api/products/", body, format="json").status_code, 201)
        r = self.c.post("/api/products/", body, format="json")
        self.assertEqual((r.status_code, r.json()["error"]["code"]), (409, "DUPLICATE"))
        for bad in ("0", "-1", "10.555", "abc"):
            r = self.c.post("/api/products/", {**body, "sku": "X" + bad, "price": bad}, format="json")
            self.assertEqual((r.status_code, r.json()["error"]["code"]), (400, "VALIDATION_ERROR"), bad)

    def test_patch_price_and_sku_immutable(self):
        r = self.c.patch("/api/products/BRK-0001/", {"price": "1500.00"}, format="json")
        self.assertEqual(r.json()["price"], "1500.00")
        self.assertEqual(self.c.patch("/api/products/BRK-0001/", {"sku": "OTHER"}, format="json").status_code, 400)

    def test_inventory_put(self):
        r = self.c.put("/api/inventory/BRK-0001/", {"quantity": 25, "reason": "count"}, format="json")
        self.assertEqual(r.json(), {"sku": "BRK-0001", "quantity": 25})
        for bad in (-1, 1.5, "5", None, True):
            self.assertEqual(self.c.put("/api/inventory/BRK-0001/", {"quantity": bad}, format="json").status_code, 400, bad)
        self.assertEqual(self.c.put("/api/inventory/NOPE/", {"quantity": 1}, format="json").status_code, 404)

    def test_dealers(self):
        make_dealer()
        r = self.c.post("/api/dealers/", {"dealer_code": "D-9", "name": "Nine"}, format="json")
        self.assertEqual(r.status_code, 201)
        self.assertEqual(self.c.post("/api/dealers/", {"dealer_code": "D-9", "name": "x"}, format="json").status_code, 409)
        self.assertEqual(self.c.post("/api/dealers/", {"name": "x"}, format="json").status_code, 400)
        self.assertEqual(self.c.get("/api/dealers/999999/").json()["error"]["code"], "NOT_FOUND")
