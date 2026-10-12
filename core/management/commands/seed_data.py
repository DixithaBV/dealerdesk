"""Load data/catalogue.csv and data/dealers.csv. Safe to run any number of times:
existing SKUs / dealer codes are left untouched (so re-seeding never resets live stock)."""
import csv
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

from catalog.models import Dealer, Inventory, Product


def _money(v):
    try:
        d = Decimal(str(v).strip().replace(",", ""))
    except InvalidOperation:
        return None
    return d.quantize(Decimal("0.01")) if d > 0 else None


def _read(path):
    with open(path, newline="", encoding="utf-8-sig") as fh:  # utf-8-sig strips a BOM if present
        return [{(k or "").strip(): (v or "").strip() for k, v in row.items()} for row in csv.DictReader(fh)]


class Command(BaseCommand):
    help = "Load the files in data/ into the database. Safe to run more than once."

    @transaction.atomic
    def handle(self, *args, **options):
        d = settings.DATA_DIR
        skipped = 0
        have = set(Product.objects.values_list("sku", flat=True))
        new_products, stock = [], {}
        for r in _read(d / "catalogue.csv"):
            sku, price = r.get("sku", ""), _money(r.get("price", ""))
            if not sku or price is None or sku in have:
                skipped += 1 if (not sku or price is None) else 0
                continue
            have.add(sku)
            try:
                stock[sku] = max(0, int(float(r.get("stock") or 0)))
            except ValueError:
                stock[sku] = 0
            new_products.append(Product(sku=sku, name=r.get("name") or sku, category=r.get("category", ""),
                                        brand=r.get("brand", ""), vehicle_fitment=r.get("vehicle_fitment", ""),
                                        price=price, description=r.get("description", "")))
        Product.objects.bulk_create(new_products)
        created = {p.sku: p for p in Product.objects.filter(sku__in=stock.keys())}
        Inventory.objects.bulk_create([Inventory(product=created[s], quantity=q) for s, q in stock.items()],
                                      ignore_conflicts=True)
        # Products that somehow lack an inventory row get one (stock 0).
        missing = Product.objects.filter(inventory__isnull=True)
        Inventory.objects.bulk_create([Inventory(product=p, quantity=0) for p in missing], ignore_conflicts=True)

        codes = set(Dealer.objects.values_list("dealer_code", flat=True))
        new_dealers = []
        for r in _read(d / "dealers.csv"):
            code = r.get("dealer_code", "")
            if not code or code in codes:
                continue
            codes.add(code)
            try:
                limit = Decimal(r.get("credit_limit") or "0").quantize(Decimal("0.01"))
            except InvalidOperation:
                limit = Decimal("0.00")
            new_dealers.append(Dealer(dealer_code=code, name=r.get("name", code), city=r.get("city", ""),
                                      phone=r.get("phone", ""), email=r.get("email", ""), gstin=r.get("gstin", ""),
                                      credit_limit=limit))
        Dealer.objects.bulk_create(new_dealers)
        self.stdout.write(self.style.SUCCESS(
            f"seed_data: +{len(new_products)} products, +{len(new_dealers)} dealers "
            f"(totals: {Product.objects.count()} products, {Dealer.objects.count()} dealers; skipped {skipped} bad rows)"))
