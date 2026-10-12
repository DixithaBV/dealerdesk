from django.conf import settings
from django.db import connection, transaction

from catalog.models import Inventory, Product
from core.exceptions import APIError

from . import feed

FIELDS = ("name", "category", "brand", "vehicle_fitment", "description")
LOCK_ID = 727_001


def run_sync():
    try:
        items, pages, made = feed.fetch_all(settings.SUPPLIER_API_URL, settings.SUPPLIER_API_KEY,
                                            max_attempts=settings.SUPPLIER_MAX_ATTEMPTS)
    except feed.SupplierUnavailable as e:
        raise APIError(502, "SUPPLIER_UNAVAILABLE", f"Supplier feed could not be fetched completely: {e}")
    unique, rejected = feed.clean(items)
    created = updated = unchanged = 0
    with transaction.atomic():  # nothing is written unless every page was fetched (above) and this block succeeds
        with connection.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(%s)", [LOCK_ID])  # two simultaneous syncs queue up
        existing = {p.sku: p for p in Product.objects.filter(sku__in=list(unique))}
        new_products, changed = [], []
        for sku, it in unique.items():
            p = existing.get(sku)
            vals = {f: (str(it[f]) if it.get(f) is not None else None) for f in FIELDS}
            if p is None:
                new_products.append(Product(sku=sku, name=vals["name"] or sku, category=vals["category"] or "",
                                            brand=vals["brand"] or "", vehicle_fitment=vals["vehicle_fitment"] or "",
                                            description=vals["description"] or "", price=it["_price"]))
                continue
            diff = False
            for f, v in vals.items():
                if v is not None and v != getattr(p, f):
                    setattr(p, f, v); diff = True
            if it["_price"] != p.price:
                p.price = it["_price"]; diff = True
            if diff:
                changed.append(p)
            else:
                unchanged += 1
        Product.objects.bulk_create(new_products)
        Inventory.objects.bulk_create(
            [Inventory(product=p, quantity=0) for p in Product.objects.filter(sku__in=[n.sku for n in new_products])],
            ignore_conflicts=True)  # stock 0 for new products; existing stock is never touched
        if changed:
            for p in changed:
                p.save(update_fields=list(FIELDS) + ["price", "updated_at"])
        created, updated = len(new_products), len(changed)
    return {"created": created, "updated": updated, "unchanged": unchanged, "rejected": rejected,
            "pages_fetched": pages, "requests_made": made}
